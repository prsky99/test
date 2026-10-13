"""MCP 인증 방법 조사: 인증이 필요한 MCP 서버가 '어떻게' 인증받는지 알아내 저장한다.

우리는 자격 증명을 보내지 않는다. 서버가 공개한 정보만 읽는다 (MCP Authorization 표준, RFC 9728/8414/7591).
1. 인증 없이 initialize → 401 응답의 WWW-Authenticate 헤더 (scheme, resource_metadata, scope)와 본문 메시지
2. 보호 리소스 메타데이터 (/.well-known/oauth-protected-resource[/경로]) → 인증 서버, 지원 scope, 문서
3. 인증 서버 메타데이터 (/.well-known/oauth-authorization-server, openid-configuration)
   → 토큰·인가 주소, 클라이언트 자동 등록(DCR) 주소, 지원 grant, PKCE, CIMD
4. 레지스트리에 선언된 헤더 (이름·설명), 401 본문·헤더 설명·웹사이트에 적힌 키 발급처 URL

판별 결과
- method: oauth2 | api_key | bearer | none(실제로는 인증 없이 동작) | unknown
- autonomy: agent_autonomous (에이전트 혼자 등록·토큰 발급: client_credentials + 자동 등록/CIMD)
            | human_once (사람이 한 번 승인·키 발급: authorization_code·device_code·API 키)
            | none_needed | unknown
"""

import json
import logging
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from ..broker.discovery import DiscoveryError, check_public_url, public_client
from ..gateway.store import Store
from .capabilities import HEADERS, INIT, parse_jsonrpc

log = logging.getLogger("agent_market.collector.auth")

USER_AGENT = "agent-collector/0.1 (+auth method discovery; no credentials are sent)"
MAX_JSON = 256 * 1024
_URL = re.compile(r"https?://[^\s\"'<>)\]]+")
_KEYWORDS_API_KEY = re.compile(r"\b(api[ _-]?key|apikey|x-api-key|access key|personal access token|pat)\b", re.I)
AS_FIELDS = ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint", "device_authorization_endpoint",
             "grant_types_supported", "code_challenge_methods_supported", "token_endpoint_auth_methods_supported",
             "scopes_supported", "client_id_metadata_document_supported")


def compact(value, max_list: int = 20, max_str: int = 500):
    """저장용으로 줄인다: 긴 목록(예: scope 수백 개)과 긴 문자열을 잘라 JSON이 항상 온전하게 남도록."""
    if isinstance(value, dict):
        return {k: compact(v, max_list, max_str) for k, v in value.items()}
    if isinstance(value, list):
        return [compact(v, max_list, max_str) for v in value[:max_list]]
    if isinstance(value, str):
        return value[:max_str]
    return value


def parse_www_authenticate(value: str | None) -> dict:
    """'Bearer resource_metadata="...", scope="a b", error="invalid_token"' → {"scheme": "Bearer", "resource_metadata": ...}"""
    if not value:
        return {}
    scheme, _, rest = value.strip().partition(" ")
    params = {k.lower(): v for k, v in re.findall(r'([A-Za-z_]+)\s*=\s*"([^"]*)"', rest)}
    params.update({k.lower(): v for k, v in re.findall(r'([A-Za-z_]+)\s*=\s*([^",\s]+)', rest) if k.lower() not in params})
    return {"scheme": scheme, **params}


def well_known(base: str, name: str) -> list[str]:
    """RFC 8414/9728 방식(경로를 .well-known 뒤에 붙임)과 루트 방식 둘 다."""
    p = urlparse(base)
    origin, path = f"{p.scheme}://{p.netloc}", p.path.rstrip("/")
    urls = [f"{origin}/.well-known/{name}{path}"] if path else []
    urls.append(f"{origin}/.well-known/{name}")
    return urls


def urls_in(*texts: str | None) -> list[str]:
    found = []
    for t in texts:
        for u in _URL.findall(t or ""):
            u = u.rstrip(".,;:")
            if u not in found:
                found.append(u)
    return found[:5]


def classify_auth(status: int | None, www: dict, prm: dict | None, asm: dict | None, headers: list[dict], body: str) -> tuple[str, str]:
    if status == 200:
        return "none", "none_needed"
    if prm or asm:
        grants = set((asm or {}).get("grant_types_supported") or ["authorization_code"])
        can_register = bool((asm or {}).get("registration_endpoint") or (asm or {}).get("client_id_metadata_document_supported"))
        if "client_credentials" in grants and can_register:
            return "oauth2", "agent_autonomous"
        return "oauth2", "human_once"
    names = {str(h.get("name", "")).lower() for h in headers}
    descs = " ".join(str(h.get("description") or "") for h in headers)
    if (names - {"authorization"}) or www.get("scheme", "").lower() in ("apikey", "azureapimanagementkey") \
            or _KEYWORDS_API_KEY.search(f"{descs} {body}"):
        return "api_key", "human_once"
    if www.get("scheme", "").lower() == "bearer" or "authorization" in names:
        return "bearer", "human_once"
    if www.get("scheme", "").lower() == "basic":
        return "basic", "human_once"
    return "unknown", "unknown"


def instructions(method: str, info: dict, protocol: str = "MCP") -> list[str]:
    """요청한 에이전트가 따라 할 수 있는 짧은 안내 (영어: 에이전트 간 공용어). protocol: MCP | A2A"""
    if method == "none":
        return ["No authentication needed: connect and call initialize directly." if protocol == "MCP"
                else f"No authentication needed: send {protocol} requests directly."]
    if method == "oauth2":
        o = info.get("oauth", {})
        steps = []
        if o.get("registration_endpoint"):
            steps.append(f"Register an OAuth client via Dynamic Client Registration: POST {o['registration_endpoint']}.")
        elif o.get("client_id_metadata_document_supported"):
            steps.append("Use a Client ID Metadata Document URL as your client_id (CIMD supported).")
        else:
            steps.append("Obtain an OAuth client_id from the provider (no automatic registration advertised).")
        grants = o.get("grant_types_supported") or ["authorization_code"]
        if "client_credentials" in grants:
            steps.append(f"Get a token without a human: client_credentials grant at {o.get('token_endpoint')}.")
        if "urn:ietf:params:oauth:grant-type:device_code" in grants and o.get("device_authorization_endpoint"):
            steps.append(f"Or device flow: request a code at {o['device_authorization_endpoint']} and have a human approve it.")
        if "authorization_code" in grants:
            pkce = " with PKCE (S256)" if "S256" in (o.get("code_challenge_methods_supported") or []) else ""
            steps.append(f"Or authorization_code{pkce}: a human approves once at {o.get('authorization_endpoint')}, "
                         f"then exchange the code at {o.get('token_endpoint')}.")
        if o.get("resource"):
            steps.append(f"Request the token for resource={o['resource']}" + (f" with scope '{' '.join(o['scopes'])}'." if o.get("scopes") else "."))
        steps.append(f"Send it as 'Authorization: Bearer <access_token>' on every {protocol} request.")
        return steps
    if method in ("api_key", "bearer", "basic"):
        k = info.get("api_key", {})
        header = k.get("header") or "Authorization"
        fmt = "Bearer <key>" if header.lower() == "authorization" and method != "basic" else "<key>"
        steps = ["Get an API key from the provider" + (f": {', '.join(k['where_to_get'][:2])}" if k.get("where_to_get") else ".")]
        steps.append(f"Send it as '{header}: {fmt}' on every {protocol} request.")
        if info.get("scope") == "tool":
            steps.append("Note: initialize/tools/list work without it, but tool calls are rejected until you authenticate.")
        if k.get("query_param") and protocol == "A2A" and not k.get("header"):
            steps[-1] = f"Send it as the query parameter '{k.get('param_name')}' on every {protocol} request."
        elif k.get("query_param"):
            steps.append("The server also accepts the key as a query parameter (prefer the header).")
        return steps
    return ["Authentication is required but the method could not be determined; check the provider's documentation."]


class AuthDiscoverer:
    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False,
                 max_age: float = 7 * 86400, workers: int = 8, per_host_delay: float = 1.0):
        self.store = store
        self._fixed_http = http
        self.allow_private = allow_private
        self.max_age = max_age
        self.workers = workers
        self.per_host_delay = per_host_delay
        self._cache: dict[str, tuple[float, dict | None]] = {}  # 메타데이터 URL → (시각, JSON) — 같은 인증 서버를 여러 MCP가 공유
        self._cache_lock = threading.Lock()

    def _json(self, http: httpx.Client, url: str) -> dict | None:
        with self._cache_lock:
            hit = self._cache.get(url)
            if hit and time.time() - hit[0] < 3600:
                return hit[1]
        data = None
        try:
            if not self.allow_private:
                check_public_url(url)
            resp = http.get(url, headers={"accept": "application/json", "user-agent": USER_AGENT})
            if resp.status_code == 200 and len(resp.content) <= MAX_JSON:
                parsed = resp.json()
                data = parsed if isinstance(parsed, dict) else None
        except (httpx.HTTPError, DiscoveryError, ValueError):
            data = None
        with self._cache_lock:
            self._cache[url] = (time.time(), data)
        return data

    def discover(self, resource: dict, http: httpx.Client) -> dict:
        url = resource["url"]
        if not self.allow_private:
            check_public_url(url)
        resp = http.post(url, json=INIT, headers={**HEADERS, "user-agent": USER_AGENT})
        status, body = resp.status_code, resp.text[:2000]
        if status == 200 and not (parse_jsonrpc(resp) or {}).get("result"):
            status = None  # 200이지만 MCP 응답이 아님
        tool_level = resource.get("auth_scope") == "tool"
        if tool_level and status == 200:
            # 연결은 되지만 도구 호출에서 인증 요구: 도구 호출 때 받은 오류 메시지로 판단
            status = None
            trial = json.loads(resource.get("trial_info") or "null") or {}
            body = str(trial.get("error") or "")[:2000]
        www = parse_www_authenticate(resp.headers.get("www-authenticate"))

        prm, prm_url = None, None
        candidates = ([www["resource_metadata"]] if www.get("resource_metadata") else []) + well_known(url, "oauth-protected-resource")
        if status != 200:
            for u in candidates:
                if (prm := self._json(http, u)) and (prm.get("authorization_servers") or prm.get("resource")):
                    prm_url = u
                    break
                prm = None

        asm, as_url = None, None
        if status != 200:
            bases = list((prm or {}).get("authorization_servers") or []) + ([] if prm else [url])  # 메타데이터가 없으면 구 방식(서버 자체)
            for base in bases[:3]:
                for u in well_known(base, "oauth-authorization-server") + well_known(base, "openid-configuration"):
                    if (asm := self._json(http, u)) and asm.get("token_endpoint"):
                        as_url = u
                        break
                    asm = None
                if asm:
                    break

        details = json.loads(resource.get("details") or "{}") if isinstance(resource.get("details"), str) else (resource.get("details") or {})
        headers = [h for r in details.get("remotes") or [] for h in (r.get("headers") or [])]
        method, autonomy = classify_auth(status, www, prm, asm, headers, body)

        info: dict = {"http_status": status, "www_authenticate": {k: v for k, v in www.items() if k != "resource_metadata"} or None,
                      "scope": "tool" if tool_level else "connection"}
        if method == "oauth2":
            info["oauth"] = {
                "resource": (prm or {}).get("resource"),
                "protected_resource_metadata": prm_url,
                "authorization_servers": (prm or {}).get("authorization_servers"),
                "authorization_server_metadata": as_url,
                "scopes": (prm or {}).get("scopes_supported") or ([www["scope"]] if www.get("scope") else None),
                "documentation": (prm or {}).get("resource_documentation"),
                **{k: (asm or {}).get(k) for k in AS_FIELDS},
            }
        if method in ("api_key", "bearer", "basic"):
            declared = next((h for h in headers if str(h.get("name", "")).lower() != "authorization"), None) or (headers[0] if headers else {})
            info["api_key"] = {
                "header": declared.get("name") or ("Authorization" if method != "api_key" else None),
                "description": declared.get("description"),
                "where_to_get": urls_in(*(h.get("description") for h in headers), body) or
                                [u for u in (details.get("website"),) if u],
                "query_param": bool(re.search(r"query param", body, re.I)),
                "server_message": body[:300] if status in (401, 403) or tool_level else None,
            }
        info["website"] = details.get("website")
        info["instructions"] = instructions(method, info)
        return {"method": method, "autonomy": autonomy, "info": compact(info)}

    def run_due(self, limit: int = 100) -> dict:
        due = self.store.due_for_auth(time.time(), self.max_age, limit)
        if not due:
            return {"checked": 0}
        by_host: dict[str, list[dict]] = defaultdict(list)
        for r in due:
            by_host[r.get("host") or r["url"]].append(r)
        http = self._fixed_http or public_client(self.allow_private, timeout=httpx.Timeout(10.0, connect=5.0, pool=30.0), follow_redirects=False)
        results, lock = [], threading.Lock()

        def work(resources: list[dict]) -> None:
            for i, r in enumerate(resources):
                if i:
                    time.sleep(self.per_host_delay)
                try:
                    found, err = self.discover(r, http), None
                except (httpx.PoolTimeout, httpx.ProxyError):
                    found, err = None, "local"
                except (httpx.HTTPError, DiscoveryError, ValueError) as exc:
                    found, err = None, f"{type(exc).__name__}: {exc}"[:300]
                except Exception as exc:  # 비표준 메타데이터 등: 이 서버만 실패로 기록
                    log.warning("auth discovery error for %s: %r", r["url"], exc)
                    found, err = None, f"{type(exc).__name__}: {exc}"[:300]
                with lock:
                    results.append((r, found, err))

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(work, by_host.values()))
        finally:
            if http is not self._fixed_http:
                http.close()
        failed = sum(1 for _, f, _ in results if f is None)
        outage = len(results) >= 20 and failed / len(results) >= 0.8
        stats = defaultdict(int)
        for r, found, err in results:
            if found is None and (outage or err == "local"):
                stats["postponed"] += 1
                continue
            self.store.record_auth(r["id"], found, err)
            stats[found["method"] if found else "failed"] += 1
            if found and found["autonomy"] == "agent_autonomous":
                stats["agent_autonomous"] += 1
        return {"checked": len(results), "local_network_problem": outage, **stats}
