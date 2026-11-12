"""MCP 기능 조사: 인증 없이 응답하는 MCP 서버의 도구 목록(tools/list)을 하루 한 번 받아
지원 언어·나라·통화(도구 파라미터의 선택지·기본값)와 도구 수를 기록한다.

서버당 요청 4번(initialize → initialized 알림 → tools/list → 세션 종료)이라 헬스체크보다 무겁다.
그래서 하루 한 번, 호스트당 1~2개씩, 적은 동시 실행으로 천천히 돈다.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import httpx

from ..broker.discovery import DiscoveryError, check_public_url, public_client
from ..gateway import constraints as cons
from ..gateway.store import Store
from ..observation_guards import GuardError
from . import evaluation, usage
from .percentile_cache import score_percentile as cached_percentile

log = logging.getLogger("agent_market.collector.capabilities")

USER_AGENT = "agent-collector/0.1 (+capability survey; no payment is made)"
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json", "user-agent": USER_AGENT}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "agent-collector", "version": "0.1"}}}
MAX_BODY = 2 * 1024 * 1024


def parse_jsonrpc(resp: httpx.Response) -> dict | None:
    """JSON 또는 SSE(text/event-stream) 응답에서 JSON-RPC 결과를 꺼낸다."""
    text = resp.text[:MAX_BODY]
    if "text/event-stream" in resp.headers.get("content-type", ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:])
                except ValueError:
                    continue
                if isinstance(data, dict) and ("result" in data or "error" in data):
                    return data
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class CapabilityProber:
    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False,
                 max_age: float = 86400, workers: int = 8, per_host_delay: float = 1.0,
                 trial_max_age: float = 7 * 86400, trials: bool = True):
        self.store = store
        self._fixed_http = http
        self.allow_private = allow_private
        self.max_age = max_age
        self.workers = workers
        self.per_host_delay = per_host_delay
        self.trial_max_age = trial_max_age  # 도구 목록이 그대로면 이 주기로만 다시 실제 호출
        self.trials = trials

    def probe(self, url: str, http: httpx.Client, trial_for=None) -> dict:
        """server/discover (무상태) 또는 initialize → tools/list (→ 안전한 도구 하나 tools/call) → 세션 종료.

        trial_for(compact_tools) 가 (tool, arguments)를 돌려주면 같은 세션에서 그 도구를 실제로 호출해 본다.
        """
        if not self.allow_private:
            check_public_url(url)
        headers = dict(HEADERS)
        # 1. 최신 2026-07-28 사양: server/discover 시도 (무상태)
        try:
            disc_resp = http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}, headers=headers)
            disc_data = parse_jsonrpc(disc_resp) or {}
            disc_res = disc_data.get("result")
            if isinstance(disc_res, dict) and disc_res:
                pv = disc_res.get("protocolVersion")
                if pv:
                    headers["mcp-protocol-version"] = str(pv)
                listed = parse_jsonrpc(http.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                                             "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": str(pv or "2026-07-28")}}},
                                                 headers=headers)) or {}
                tools = (listed.get("result") or {}).get("tools")
                if isinstance(tools, list):
                    picked = trial_for(usage.compact_tools(tools)) if trial_for else None
                    trial = self._trial(url, http, headers, *picked) if picked else None
                    return {"tools": tools, "protocol_version": pv or "2026-07-28", "server_info": disc_res.get("serverInfo"),
                            "instructions": disc_res.get("instructions"), "trial": trial}
        except Exception:
            pass  # 기존 서버이거나 오류 발생 시 initialize로 폴백

        # 2. 구형 사양: initialize -> notifications/initialized -> tools/list (세션 핸드셰이크)
        init = http.post(url, json=INIT, headers=HEADERS)
        result = (parse_jsonrpc(init) or {}).get("result") or {}
        if not result:
            raise ValueError(f"initialize failed (HTTP {init.status_code})")
        headers = dict(HEADERS)
        if sid := init.headers.get("mcp-session-id"):
            headers["mcp-session-id"] = sid
        if pv := result.get("protocolVersion"):
            headers["mcp-protocol-version"] = str(pv)  # 숫자로 주는 비표준 서버도 있음
        trial = None
        try:
            http.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
            listed = parse_jsonrpc(http.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)) or {}
            tools = (listed.get("result") or {}).get("tools")
            if not isinstance(tools, list):
                raise ValueError("tools/list failed")
            picked = trial_for(usage.compact_tools(tools)) if trial_for else None
            if picked:
                trial = self._trial(url, http, headers, *picked)
        finally:
            if sid:
                try:
                    http.delete(url, headers=headers)
                except httpx.HTTPError:
                    pass
        return {"tools": tools, "protocol_version": result.get("protocolVersion"), "server_info": result.get("serverInfo"),
                "instructions": result.get("instructions"), "trial": trial}

    def _trial(self, url: str, http: httpx.Client, headers: dict, tool: dict, arguments: dict) -> dict:
        started = time.monotonic()
        out = {"tool": tool["name"], "arguments": arguments, "at": time.time()}
        try:
            resp = http.post(url, json=usage.jsonrpc_call(tool["name"], arguments), headers=headers,
                             timeout=httpx.Timeout(20.0, connect=5.0))
            data = parse_jsonrpc(resp) or {}
            if not 200<=resp.status_code<300 or data.get('jsonrpc')!='2.0' or type(data.get('id')) is not int or data['id']!=3:
                data={'error':{'message':'Invalid tool execution protocol response.'}}
            err = data.get("error")
            if err:  # 표준은 {"code","message"}지만 문자열로 주는 서버도 있음
                out.update(ok=False, error=str(err.get("message") or err if isinstance(err, dict) else err)[:300])
            else:
                res = data.get("result") if isinstance(data.get("result"), dict) else {}
                out.update(ok=not res.get("isError") and bool(res), sample_output=usage.result_text(res) or None,
                           output_chars=len(json.dumps(res, ensure_ascii=False)))
                if res.get("isError"):
                    out["error"] = (usage.result_text(res) or "tool returned an error")[:300]
                elif not res:
                    out["error"] = f"no result (HTTP {resp.status_code})"
        except httpx.HTTPError as exc:
            out.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
        out["latency_ms"] = int((time.monotonic() - started) * 1000)
        out['finished_at']=time.time()
        return out

    def _trial_decider(self, resource: dict):
        """도구 목록이 바뀌었거나 마지막 실제 호출이 오래됐을 때만 시험 호출할 도구를 고른다."""
        if not self.trials:
            return None
        last = json.loads(resource.get("trial_info") or "null") or {}

        def decide(tools: list[dict]):
            stale = not last or time.time() - last.get("at", 0) > self.trial_max_age
            if not stale and usage.tools_hash(tools) == resource.get("usage_tools_hash"):
                return None
            return usage.pick_trial(tools, resource.get("category"))
        return decide

    def _record_usage(self, r: dict, probed: dict) -> tuple[bool, dict | None, dict | None, dict | None]:
        """사용 안내 저장. (도구 목록 변경 여부, 이번 시험 호출, 변경 내역, 안내에 쓴 마지막 시험 호출)"""
        tools = usage.compact_tools(probed["tools"])
        digest = usage.tools_hash(tools)
        old = json.loads(r.get("usage_tools") or "null")
        changes = usage.diff_tools(old, tools) if old is not None and r.get("usage_tools_hash") != digest else None
        if changes and not any(changes.values()):
            changes = None
        if changes:
            from . import cap_changes
            cap_changes.record(r, old, tools, changes)  # 11-12 PM: words lost by a re-survey, file only
        trial = probed.get("trial")
        last_trial = trial or json.loads(r.get("trial_info") or "null")
        if last_trial and last_trial.get("tool") not in {t["name"] for t in tools}:
            last_trial = None  # 시험했던 도구가 없어졌으면 그 결과는 더 이상 안내에 쓰지 않음
        transport = next((rm.get("type") for rm in (json.loads(r.get("details") or "{}").get("remotes") or [])), "streamable-http")
        guide = usage.build_guide(r["url"], transport, probed.get("protocol_version"), tools, r.get("category"),
                                  last_trial, changes, probed.get("server_info"), probed.get("instructions"))
        guide["updated_at"] = time.time()
        changed = self.store.record_usage(r["id"], tools, digest, guide, changes, trial, full_tools=probed['tools'])
        if trial and trial.get('at') and trial.get('finished_at'):
            try:
                from ..capability_registry import Registry
                registry=Registry(self.store);version=registry.current(self.store.resource(r['id']))
                if version:registry.record(version,scope='execution',outcome='succeeded' if trial.get('ok') else 'failed',started=trial['at'],finished=trial['finished_at'])
            except GuardError:
                raise
            except Exception as exc:
                log.debug("capability registry record failed for %s: %s", r["id"], exc)
                raise
        if trial and not trial.get("ok") and usage.is_auth_error(trial.get("error")):
            self.store.mark_tool_level_auth(r["id"])  # 도구 단계 인증 → 인증 방법 조사로 넘김
        return changed and old is not None, trial, changes, last_trial

    def _evaluate(self, r: dict, probed: dict, changes: dict | None, last_trial: dict | None) -> dict | None:
        compact = usage.compact_tools(probed["tools"])
        metadata = {"protocol_version": probed.get("protocol_version"), "server_info": probed.get("server_info"),
                    "instructions": probed.get("instructions")}
        try:
            ev = evaluation.evaluate(r, probed["tools"], compact, metadata, trial=last_trial, changes=changes)
        except GuardError:
            raise
        except Exception:
            log.warning("capability evaluation calculation unavailable")
            self.store.record_evaluation_unavailable(r["id"])
            return None
        # 품질 정책: 7일 헬스체크와 실제 호출 시험으로 등급 상한을 정한다
        since = time.time() - evaluation.POLICY_WINDOW_DAYS * 86400
        ev = evaluation.apply_quality_policy({**r, "trial_info": last_trial}, ev,
                                             self.store.health_counts([r["id"]], since).get(r["id"]))
        ev["percentile"] = cached_percentile(self.store, ev["score"], "mcp")  # 평가된 서버 중 이보다 점수가 낮은 비율
        self.store.record_evaluation(r["id"], ev)
        return ev

    def requeue_outdated_evaluations(self) -> int:
        """평가 규칙(evaluation.VERSION)이 바뀌었으면 이미 조사한 서버를 다시 조사 대상으로 돌린다.
        도구 원본은 저장하지 않으므로(설명이 잘린 정리본만 저장) 다시 받아서 평가한다."""
        if self.store.get_meta("evaluation_version") == evaluation.VERSION:
            return 0
        with self.store.tx() as db:
            n = db.execute("""UPDATE resources SET cap_checked_at=NULL WHERE kind='mcp' AND cap_checked_at IS NOT NULL
                              AND cap_error IS NULL""").rowcount
            db.execute("UPDATE resources SET eval_at=NULL WHERE eval_coverage='static'")
        self.store.set_meta("evaluation_version", evaluation.VERSION)
        log.info("evaluation rules v%s: %d servers queued for re-evaluation", evaluation.VERSION, n)
        return n

    def evaluate_static_due(self, limit: int = 500) -> int:
        """인증이 필요한 서버는 네트워크 요청 없이 출처 정적 평가만 한다."""
        due = self.store.due_for_static_evaluation(time.time(), self.max_age, limit)
        accepted = 0
        for r in due:
            try:
                guard = self.store.observation_guard(r["id"], "evaluation", expected_resource=r)
                result = evaluation.evaluate_static(r)
                with self.store.observation_transaction(guard):
                    self.store.record_evaluation(r["id"], result)
                accepted += 1
            except GuardError:
                continue
        return accepted

    def run_due(self, limit: int = 100) -> dict:
        due = self.store.due_for_capability(time.time(), self.max_age, limit)
        if not due:
            return {"checked": 0, "accepted": 0, "stale": 0}
        by_host: dict[str, list[dict]] = defaultdict(list)
        for r in due:
            by_host[r.get("host") or r["url"]].append(r)
        http = self._fixed_http or public_client(self.allow_private, timeout=httpx.Timeout(12.0, connect=5.0, pool=30.0), follow_redirects=False)
        results, lock = [], threading.Lock()

        def work(resources: list[dict]) -> None:
            for i, r in enumerate(resources):
                if i:
                    time.sleep(self.per_host_delay)
                guard = None
                try:
                    guard = self.store.observation_guard(r["id"], "survey", expected_resource=r)
                    probed, err = self.probe(r["url"], http, trial_for=self._trial_decider(r)), None
                except GuardError:
                    probed, err = None, "stale"
                except (httpx.PoolTimeout, httpx.ProxyError):
                    probed, err = None, "local"
                except (httpx.HTTPError, DiscoveryError, ValueError) as exc:
                    probed, err = None, f"{type(exc).__name__}: {exc}"[:300]
                except Exception as exc:  # 비표준 응답 등: 이 서버만 실패로 기록하고 묶음은 계속
                    log.warning("capability probe error for %s: %r", r["url"], exc)
                    probed, err = None, f"{type(exc).__name__}: {exc}"[:300]
                with lock:
                    results.append((r, probed, err, guard))

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(work, by_host.values()))
        finally:
            if http is not self._fixed_http:
                http.close()

        attempted = sum(guard is not None for _, _, _, guard in results)
        failed = sum(1 for _, probed, _, guard in results if guard is not None and probed is None)
        outage = attempted >= 20 and failed / attempted >= 0.8
        stats = defaultdict(int, accepted=0, stale=0)
        for r, probed, err, guard in results:
            if guard is None:
                stats["stale"] += 1
                continue
            delta = defaultdict(int)
            try:
                with self.store.observation_transaction(guard):
                    if probed is None and (outage or err == "local"):
                        delta["postponed"] += 1
                    else:
                        caps = cons.from_tools(probed["tools"]) if probed else None
                        self.store.record_capability(r["id"], caps, err)
                        delta["accepted"] += 1
                        delta["ok" if caps else "failed"] += 1
                        if caps and (caps["languages"] or caps["regions"]):
                            delta["with_language_or_region"] += 1
                        if probed:
                            changed, trial, changes, last_trial = self._record_usage(r, probed)
                            delta["usage_changed"] += int(changed)
                            if trial:
                                delta["trial_ok" if trial.get("ok") else "trial_failed"] += 1
                            ev = self._evaluate(r, probed, changes, last_trial)
                            if ev is None:
                                delta["evaluation_unavailable"] += 1
                            else:
                                delta[f"grade_{ev['grade']}"] += 1
                                if ev["security"] == "quarantine": delta["quarantined"] += 1
            except GuardError:
                stats["stale"] += 1
                continue
            except Exception as exc:
                log.warning("capability result bundle failed for %s: %r", r["url"], exc)
                stats["record_error"] += 1
                continue
            for key, value in delta.items(): stats[key] += value
        return {"checked": len(results), "local_network_problem": outage, **stats}
