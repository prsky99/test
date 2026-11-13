"""MCP & REST & x402 Proxy Execution Gateway with Schema Hash Pinning & Virtual Escrow.

Executes verified, safe MCP tools, OpenAPI REST endpoints, and x402 paid APIs.
Prevents MCP Rug-Pulls and Tool Poisoning by validating remote schema hashes
against the gateway's pinned baseline hash before execution.
Integrates with Clearinghouse for zero-trust A402 virtual escrow and SLA verification.
"""

import json
import logging
import time
from typing import Any
import httpx

from ..broker.discovery import DiscoveryError
from .http_security import bounded_client, validate_public_url as check_public_url
from ..collector import usage
from ..collector.capabilities import HEADERS, INIT, parse_jsonrpc
from ..gateway.store import Store
from .clearinghouse import Clearinghouse, InsufficientCreditsError
from .rest_adapter import OpenApiAdapter
from .execution_policy import admit, admit_tool, validate_arguments, ExecutionDenied
from ..observability import journal_for, current_attempt, attempt_scope, provider_dispatch, result_state

log = logging.getLogger("agent_market.concierge.proxy")


class McpProxy:
    def __init__(self, store: Store, allow_private: bool = False, http: httpx.Client | None = None,
                 clearinghouse: Clearinghouse | None = None):
        self.store = store
        self.journal = journal_for(store)
        self.allow_private = allow_private
        self._http = http
        self.clearinghouse = clearinghouse or Clearinghouse(store)

    def _client(self, public=False) -> httpx.Client:
        return bounded_client(self._http, allow_private=self.allow_private and not public, timeout=15.0)

    def execute(self, resource_id: int, tool_name: str, arguments: dict[str, Any] | None = None,
                account_id: str | None = None, payment: dict[str, Any] | None = None, *, public=False) -> dict[str, Any]:
        if current_attempt(self.store):
            return self._execute_recorded(resource_id,tool_name,arguments,account_id,payment,public=public)
        operation=self.journal.begin('execution','legacy',resource_id=resource_id)
        try:
            attempt=operation.attempt(resource_id)
            with attempt_scope(attempt):
                result=self._execute_recorded(resource_id,tool_name,arguments,account_id,payment,public=public)
                attempt.finish(result_state(result),result.get('error_code'),result.get('transport_ok'),result.get('protocol_valid'))
            operation.finish(result_state(result),result.get('error_code'))
            return result
        except Exception:
            operation.finish('failed','EXECUTION_FAILED')
            raise

    def _execute_recorded(self,resource_id,tool_name,arguments,account_id,payment,*,public=False):
        from ..execution_authority import require_enabled
        try:require_enabled(self.store,'invoke')
        except ExecutionDenied as exc:return {'ok':False,'error':str(exc),'error_code':exc.error_code}
        from ..capability_registry import Registry
        registry=Registry(self.store);version=registry.current(resource_id);started=time.time()
        result=self._execute_registered(resource_id,tool_name,arguments,account_id,payment,public=public)
        attempt=current_attempt(self.store)
        def record_evidence():
            if version and not (attempt and attempt.detached) and (result.get('hash_verified') or result.get('error_code') in ('SCHEMA_CHANGED','UPSTREAM_TIMEOUT','UPSTREAM_NETWORK','UPSTREAM_TOOL_ERROR','UPSTREAM_PROTOCOL')):
                registry.record(version,scope='execution',outcome='succeeded' if result.get('ok') else 'unknown' if result.get('error_code') in ('UPSTREAM_TIMEOUT','UPSTREAM_NETWORK') else 'failed',
                    started=started,finished=time.time(),operation_ref=attempt.id if attempt else None,code=result.get('error_code'),guard=(lambda:not attempt.detached) if attempt else None)
        owned = getattr(self, '_owned_data_dispatch', None)
        if owned is not None and owned.applies(resource_id):
            owned.bookkeep(resource_id, result, record_evidence)
        else:
            record_evidence()
        return result

    def _execute_registered(self, resource_id: int, tool_name: str, arguments: dict[str, Any] | None = None,
                account_id: str | None = None, payment: dict[str, Any] | None = None, *, public=False) -> dict[str, Any]:
        """Safely executes an MCP, REST, or x402 tool with schema hash pinning and virtual escrow."""
        arguments = {} if arguments is None else arguments
        res = self.store.resource(resource_id)
        if not res:
            return {"ok": False, "error": f"Resource {resource_id} not found.", "error_code":"RESOURCE_UNAVAILABLE"}
        if not res.get("active"):
            return {"ok": False, "error": f"Resource {resource_id} is currently inactive.", "error_code":"RESOURCE_UNAVAILABLE"}
        from ..capability_registry import known_schema_failure
        if known_schema_failure(self.store, res):
            return {'ok':False,'error':'The registered capability schema needs review before execution.',
                    'error_code':'SCHEMA_CHANGED'}
        try:
            admit(res, public=public, authorize_charge=True)
            if res.get('kind') == 'mcp':
                admit_tool(res, tool_name, arguments)
        except ExecutionDenied as exc:
            return {'ok':False,'error':str(exc),'error_code':exc.error_code}

        kind = res.get("kind")
        if kind == 'x402' and payment is not None:
            from .payment_wire import payment_headers, PaymentWireError
            try:payment_headers(payment)
            except PaymentWireError as exc:
                return {'ok':False,'payment_required':True,'error_code':exc.code,
                        'error':'Invalid payment proof headers.','validation_stage':'format',
                        'status_code':400,'retry_safe':True,'provider_dispatched':False}
        details = res.get("details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except ValueError:
                details = {}
        details = details or {}

        # 1. Check price and Escrow reservation
        price_usdc = res.get("price_usdc") or 0
        hold_id: str | None = None
        if price_usdc > 0:
            if not account_id:
                return {
                    "ok": False,
                    "payment_required": True,
                    "error_code": "AUTH_REQUIRED",
                    "price_usdc": price_usdc,
                    # Every condition in order, so an agent does not assume payment alone is enough.
                    "requirements": ["credit_account", "available_balance"]
                                    + (["or_x402_payment_proof"] if kind == 'x402' else []),
                    "error": f"Resource {resource_id} cannot run yet. Required, in order: (1) a credit account "
                             f"(account_id or visitor_token); (2) at least {price_usdc} micro-USDC available in it"
                             + ("; or instead an x402 payment proof for this listing" if kind == 'x402' else "")
                             + ". Compact MCP execution also needs a customer-approved informational grant."
                }
            try:
                hold_id = self.clearinghouse.escrow_hold(account_id, price_usdc, resource_id, tool_name)
            except InsufficientCreditsError as exc:
                return {
                    "ok": False,
                    "payment_required": True,
                    "error_code": "AUTH_REQUIRED",
                    "price_usdc": price_usdc,
                    "error": f"Insufficient available credits: {exc}"
                }

        # 2. Dispatch execution by resource kind
        if kind == "mcp":
            observed={'transport_ok':False,'protocol_valid':False}
            exec_res = self._execute_mcp(res, tool_name, arguments, public=public, observed=observed)
            exec_res.update(observed)
        elif kind == "x402":
            exec_res = self._execute_x402(res, tool_name, arguments, payment)
        elif kind in ("rest", "openapi") or "openapi_spec" in details:
            exec_res = self._execute_rest(res, tool_name, arguments, details, payment)
        else:
            if hold_id:
                self.clearinghouse.escrow_refund(hold_id, reason=f"Unsupported kind: {kind}")
            return {"ok": False, "error": f"Unsupported resource kind: '{kind}'."}

        # 3. Post-execution SLA verification & Escrow settlement
        if hold_id:
            if exec_res.get('retry_safe') is False:
                exec_res['payment']={'hold_id':hold_id,'status':'held',
                    'reconciliation_required':True,'automatic_refund':False}
            elif exec_res.get("ok"):
                settled = self.clearinghouse.escrow_settle(hold_id, exec_res)
                exec_res["payment"] = settled
            else:
                refunded = self.clearinghouse.escrow_refund(hold_id, reason=exec_res.get("error", "Execution failed"))
                exec_res["payment"] = refunded

        return exec_res

    def _execute_mcp(self, res: dict[str, Any], tool_name: str, arguments: dict[str, Any], *, public=False, observed=None) -> dict[str, Any]:
        from ..owned_data_agents import docs
        if docs.is_docs(res):
            # Kept outside resolve_local, whose module is part of the reviewed research/news digest.
            return docs.execute_local(self.store, res, tool_name, arguments, observed)
        from ..owned_data_agents.dispatch import resolve_local
        try:
            owned = resolve_local(self, res)
        except ExecutionDenied as exc:
            return {'ok':False,'error':str(exc),'error_code':exc.error_code}
        if owned is not None:
            return owned.execute(res, tool_name, arguments, observed)
        resource_id = res["id"]
        url = res["url"]
        if not self.allow_private or public and self._http is None:
            try:
                check_public_url(url)
            except DiscoveryError as exc:
                return {"ok": False, "error": f"SSRF Protection: {exc}", "error_code": "POLICY_DENIED"}

        # Registered Tool Schema & Safety Check
        tools = json.loads(res.get("usage_tools") or "[]")
        tool_spec = next((t for t in tools if t.get("name") == tool_name), None)
        if not tool_spec:
            return {"ok": False, "error": f"Tool '{tool_name}' is not in the registered capability schema for resource {resource_id}.", "error_code": "TOOL_UNAVAILABLE"}

        if not usage.is_relay_safe_tool(tool_spec):  # the same relay judgment as safe_registered_tool (PM 11-13)
            return {"ok": False, "error": f"Tool '{tool_name}' is classified as potentially destructive or requiring credentials. Execution refused.", "error_code": "UNSAFE_TOOL"}

        from ..provider_rest import BOOK, RateLimited
        resting = BOOK.remaining(url)
        if resting:
            # 11-14 (PM 04:5x): this provider answered 429; wait out its Retry-After before calling it again.
            return {'ok': False, 'error': 'The agent asked for a pause before the next call.', 'error_code': 'RESOURCE_UNAVAILABLE',
                    'retry_after': resting, 'retry_safe': True, 'provider_dispatched': False}

        pinned_hash = res.get("usage_tools_hash")
        client = self._client(public=public)
        headers = dict(HEADERS)
        started = time.monotonic()
        remote_tools: list[dict] | None = None
        sid: str | None = None

        def decoded(response, expected_id):
            data=parse_jsonrpc(response) or {}
            valid=(data.get('jsonrpc')=='2.0' and type(data.get('id')) is type(expected_id)
                   and data.get('id')==expected_id and ('result' in data)!=('error' in data))
            if observed is not None:observed.update(transport_ok=200<=response.status_code<300,protocol_valid=valid)
            waited=BOOK.note(url,response)
            if waited:raise RateLimited(waited)
            if not 200<=response.status_code<300 or not valid:
                raise ValueError('Invalid MCP protocol response')
            return data

        try:
            # Remote Handshake & Hash Pinning Check (Anti-Rug-Pull)
            try:
                disc_resp = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}, headers=headers)
                disc_data = decoded(disc_resp, 1)
                if isinstance(disc_data.get("result"), dict) and disc_data["result"]:
                    pv = disc_data["result"].get("protocolVersion")
                    if pv:
                        headers["mcp-protocol-version"] = str(pv)
                    listed = decoded(client.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                                                  "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": str(pv or "2026-07-28")}}},
                                                       headers=headers), 2)
                    remote_tools = (listed.get("result") or {}).get("tools")
            except RateLimited:
                raise   # never follow a 429 with the initialize handshake
            except Exception:
                log.debug('Optional MCP discovery unavailable; checking registered tools.')

            if remote_tools is None:
                init_resp = client.post(url, json=INIT, headers=HEADERS)
                init_data = decoded(init_resp, INIT['id'])
                init_res = init_data.get("result")
                if not isinstance(init_res, dict):
                    return {"ok": False, "error": f"MCP handshake failed (HTTP {init_resp.status_code}): {init_data.get('error') or 'no result'}", "error_code": "UPSTREAM_PROTOCOL"}
                if sid_val := init_resp.headers.get("mcp-session-id"):
                    sid = sid_val
                    headers["mcp-session-id"] = sid
                if pv := init_res.get("protocolVersion"):
                    headers["mcp-protocol-version"] = str(pv)

                client.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
                listed = decoded(client.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers), 2)
                remote_tools = (listed.get("result") or {}).get("tools")

            if not isinstance(remote_tools, list):
                return {"ok": False, "error": "Remote MCP server failed to list available tools.", "error_code": "UPSTREAM_PROTOCOL"}

            current_compact = usage.compact_tools(remote_tools)
            if res.get('usage_full_hash'):
                from ..capability_registry import full_tools,digest
                if digest(full_tools(remote_tools))!=res['usage_full_hash']:
                    with self.store.tx() as db:
                        db.execute("UPDATE resources SET health_status='quarantined' WHERE id=?",(resource_id,))
                    return {'ok':False,'error':'The full registered capability schema changed. Survey and review it before retrying.','error_code':'SCHEMA_CHANGED'}
            current_hash = usage.tools_hash(current_compact)
            if pinned_hash and current_hash != pinned_hash:
                changes = usage.diff_tools(tools, current_compact)
                # An unordered tools/list may reorder identical definitions.
                # Keep the recorded pin and version unchanged; the full-schema
                # check above and the original compact pin must still match.
                if (sorted(tools, key=lambda t:t['name']) != sorted(current_compact, key=lambda t:t['name'])
                        or usage.tools_hash(tools) != pinned_hash):
                    log.warning("Rug-pull detected on resource %s (%s): hash %s != %s, changes: %s",
                                resource_id, url, pinned_hash, current_hash, changes)
                    with self.store.tx() as db:
                        db.execute("UPDATE resources SET health_status='quarantined' WHERE id=?", (resource_id,))
                    return {
                        "ok": False,
                        "rug_pull": True,
                        "error_code": "SCHEMA_CHANGED",
                        "error": "Security Alert: Remote MCP tool schema changed without verification (Rug-Pull detected). Execution blocked and resource quarantined.",
                        "pinned_hash": pinned_hash,
                        "current_hash": current_hash,
                        "changes": changes,
                    }

            remote_spec = next((t for t in remote_tools if isinstance(t,dict) and t.get('name')==tool_name),None)
            if remote_spec is None:
                return {'ok':False,'error':'The registered tool is unavailable.','error_code':'TOOL_UNAVAILABLE'}
            validate_arguments(remote_spec, arguments)
            from ..capability_registry import version_parts
            fresh=self.store.resource(resource_id)
            if not fresh or not fresh.get('active') or version_parts(fresh)!=version_parts(res):
                return {'ok':False,'error':'The approved connection changed during discovery.','error_code':'SCHEMA_CHANGED'}
            call_body = usage.jsonrpc_call(tool_name, arguments)
            provider_dispatch()
            call_resp = client.post(url, json=call_body, headers=headers,
                                    timeout=httpx.Timeout(15.0, connect=5.0))
            elapsed_ms = int((time.monotonic() - started) * 1000)
            call_data = decoded(call_resp, call_body['id'])
            err = call_data.get("error")
            if err:
                err_text = str(err.get("message") or err if isinstance(err, dict) else err)[:500]
                return {"ok": False, "error": err_text, "latency_ms": elapsed_ms, "hash_verified": True, "error_code": "UPSTREAM_TOOL_ERROR"}

            result_obj = call_data.get("result")
            if not isinstance(result_obj, dict):
                return {"ok": False, "error": f"Invalid response from tool (HTTP {call_resp.status_code})", "latency_ms": elapsed_ms, "error_code": "UPSTREAM_PROTOCOL"}

            if result_obj.get("isError"):
                err_text = (usage.result_text(result_obj) or "Tool returned an error")[:500]
                return {"ok": False, "error": err_text, "result": result_obj, "latency_ms": elapsed_ms, "hash_verified": True, "error_code": "UPSTREAM_TOOL_ERROR"}

            with self.store.tx() as db:
                db.execute("""UPDATE resources SET calls_30d=COALESCE(calls_30d,0)+1, 
                              last_called=? WHERE id=?""", (time.time(), resource_id))

            sample_text = usage.result_text(result_obj)
            return {
                "ok": True,
                "resource_id": resource_id,
                "tool": tool_name,
                "result": result_obj,
                "sample_output": sample_text[:500] if sample_text else None,
                "latency_ms": elapsed_ms,
                "hash_verified": True,
            }

        except ExecutionDenied as exc:
            return {'ok':False,'error':str(exc),'error_code':exc.error_code}
        except RateLimited as exc:
            return {'ok':False,'error':'The agent is limiting requests (HTTP 429).','error_code':'RESOURCE_UNAVAILABLE',
                    'retry_after':exc.seconds,'retry_safe':True}
        except ValueError:
            return {'ok':False,'error':'The agent returned an invalid protocol response.','error_code':'UPSTREAM_PROTOCOL'}
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return {"ok": False, "error": f"Network/HTTP Error: {type(exc).__name__}: {exc}", "latency_ms": elapsed_ms,
                    "error_code": "UPSTREAM_TIMEOUT" if isinstance(exc,httpx.TimeoutException) else "UPSTREAM_NETWORK"}
        finally:
            if sid:
                try:
                    client.delete(url, headers=headers)
                except httpx.HTTPError:
                    pass
            client.close()

    def _execute_x402(self, res: dict[str, Any], tool_name: str, arguments: dict[str, Any],
                      payment: dict[str, Any] | None = None) -> dict[str, Any]:
        resource_id = res["id"]
        url = res["url"]
        if not self.allow_private:
            try:
                check_public_url(url)
            except DiscoveryError as exc:
                return {"ok": False, "error": f"SSRF Protection: {exc}"}

        method = (res.get("method") or "POST").upper()
        client = self._client()
        from .payment_wire import payment_headers, settlement_response, validate_receipt_binding, PaymentWireError
        try:proof_headers=payment_headers(payment)
        except PaymentWireError as exc:
            client.close()
            return {'ok':False,'error':'Invalid payment proof headers.','error_code':exc.code,
                    'status_code':400,'validation_stage':'format','retry_safe':True}
        headers={"Content-Type":"application/json",**proof_headers}

        started = time.monotonic()
        try:
            req_kwargs: dict[str, Any] = {"headers": headers, "timeout": httpx.Timeout(15.0, connect=5.0)}
            if method in ("POST", "PUT", "PATCH"):
                req_kwargs["json"] = arguments
            else:
                req_kwargs["params"] = arguments

            provider_dispatch()
            resp = client.request(method, url, **req_kwargs)
            elapsed_ms = int((time.monotonic() - started) * 1000)

            try:
                data = resp.json()
            except Exception:
                data = resp.text

            receipt=None; payment_fault=None; retry_safe=True
            try:
                receipt=settlement_response(resp)
                validate_receipt_binding(receipt, proof_headers)
            except PaymentWireError:payment_fault='PAYMENT_RECEIPT_UNCONFIRMED';retry_safe=False
            if receipt and not receipt['success']:
                payment_fault='PAYMENT_SETTLEMENT_PENDING' if receipt.get('errorReason')=='settlement_pending' else 'PAYMENT_SETTLEMENT_UNCONFIRMED'
                retry_safe=False
            if proof_headers and receipt and receipt['success'] and not resp.is_success:
                payment_fault='PAYMENT_RESOURCE_OUTCOME_UNCONFIRMED';retry_safe=False
            if resp.is_success and 'payment-signature' in proof_headers and receipt is None:
                payment_fault='PAYMENT_RECEIPT_UNCONFIRMED';retry_safe=False
            if proof_headers and not resp.is_success and resp.status_code!=402:
                payment_fault=payment_fault or 'PAYMENT_OUTCOME_UNCONFIRMED';retry_safe=False
            challenge=None
            if resp.status_code==402:
                from .managed_gateway import challenge as read_challenge
                challenge=read_challenge(resp)
                preflight_reasons={'invalid_payload','invalid_x402_version','invalid_network','invalid_scheme',
                    'unsupported_scheme','invalid_payment_requirements','insufficient_funds',
                    'invalid_exact_evm_payload_signature','invalid_exact_evm_payload_recipient_mismatch',
                    'invalid_exact_evm_payload_authorization_value_mismatch',
                    'invalid_exact_evm_payload_authorization_valid_after',
                    'invalid_exact_evm_payload_authorization_valid_before'}
                if proof_headers and (challenge is None or challenge.get('error') not in preflight_reasons):
                    payment_fault=payment_fault or 'PAYMENT_OUTCOME_UNCONFIRMED';retry_safe=False
            is_ok = resp.is_success and payment_fault is None
            sample_text = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)

            if is_ok:
                with self.store.tx() as db:
                    db.execute("""UPDATE resources SET calls_30d=COALESCE(calls_30d,0)+1,
                                  last_called=? WHERE id=?""", (time.time(), resource_id))

            return {
                "ok": is_ok,
                "status_code": resp.status_code,
                "resource_id": resource_id,
                "tool": tool_name,
                "url": url,
                "result": data,
                "sample_output": sample_text[:500] if sample_text else None,
                "latency_ms": elapsed_ms,
                "error": payment_fault or (f"HTTP {resp.status_code}" if not is_ok else None),
                "error_code": payment_fault or ((challenge.get('error') if challenge.get('error') in preflight_reasons else 'PAYMENT_REQUIRED') if challenge else None),
                "payment_required": bool(challenge), "payment_requirements": challenge,
                "payment_response": receipt, "settlement_verified": False,
                "retry_safe": retry_safe,
            }
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return {"ok":False,"error":"The payment request outcome is unconfirmed.",
                    "error_code":"PAYMENT_OUTCOME_UNCONFIRMED","retry_safe":False,"latency_ms":elapsed_ms}
        finally:
            client.close()

    def _execute_rest(self, res: dict[str, Any], tool_name: str, arguments: dict[str, Any],
                      details: dict[str, Any], payment: dict[str, Any] | None = None) -> dict[str, Any]:
        resource_id = res["id"]
        spec = details.get("openapi_spec") or {
            "paths": {res["url"]: {"get": {"operationId": tool_name}}}
        }
        adapter = OpenApiAdapter(spec, base_url=res.get("url"), allow_private=self.allow_private, http=self._client())
        req_headers = payment.get("headers") if (payment and isinstance(payment, dict)) else None
        exec_res = adapter.execute(tool_name, arguments, headers=req_headers)
        if exec_res.get("ok"):
            with self.store.tx() as db:
                db.execute("""UPDATE resources SET calls_30d=COALESCE(calls_30d,0)+1,
                              last_called=? WHERE id=?""", (time.time(), resource_id))
        exec_res["resource_id"] = resource_id
        return exec_res
