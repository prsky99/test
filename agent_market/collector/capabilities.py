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

from ..broker.discovery import DiscoveryError, check_public_url
from ..gateway import constraints as cons
from ..gateway.store import Store
from . import usage

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
        """initialize → tools/list (→ 안전한 도구 하나 tools/call) → 세션 종료.

        trial_for(compact_tools) 가 (tool, arguments)를 돌려주면 같은 세션에서 그 도구를 실제로 호출해 본다.
        """
        if not self.allow_private:
            check_public_url(url)
        init = http.post(url, json=INIT, headers=HEADERS)
        result = (parse_jsonrpc(init) or {}).get("result") or {}
        if not result:
            raise ValueError(f"initialize failed (HTTP {init.status_code})")
        headers = dict(HEADERS)
        if sid := init.headers.get("mcp-session-id"):
            headers["mcp-session-id"] = sid
        if pv := result.get("protocolVersion"):
            headers["mcp-protocol-version"] = pv
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
            if data.get("error"):
                out.update(ok=False, error=str(data["error"].get("message") or data["error"])[:300])
            else:
                res = data.get("result") or {}
                out.update(ok=not res.get("isError") and bool(res), sample_output=usage.result_text(res) or None)
                if res.get("isError"):
                    out["error"] = (usage.result_text(res) or "tool returned an error")[:300]
                elif not res:
                    out["error"] = f"no result (HTTP {resp.status_code})"
        except httpx.HTTPError as exc:
            out.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
        out["latency_ms"] = int((time.monotonic() - started) * 1000)
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

    def _record_usage(self, r: dict, probed: dict) -> tuple[bool, dict | None]:
        tools = usage.compact_tools(probed["tools"])
        digest = usage.tools_hash(tools)
        old = json.loads(r.get("usage_tools") or "null")
        changes = usage.diff_tools(old, tools) if old is not None and r.get("usage_tools_hash") != digest else None
        trial = probed.get("trial")
        last_trial = trial or json.loads(r.get("trial_info") or "null")
        if last_trial and last_trial.get("tool") not in {t["name"] for t in tools}:
            last_trial = None  # 시험했던 도구가 없어졌으면 그 결과는 더 이상 안내에 쓰지 않음
        transport = next((rm.get("type") for rm in (json.loads(r.get("details") or "{}").get("remotes") or [])), "streamable-http")
        guide = usage.build_guide(r["url"], transport, probed.get("protocol_version"), tools, r.get("category"),
                                  last_trial, changes, probed.get("server_info"), probed.get("instructions"))
        guide["updated_at"] = time.time()
        changed = self.store.record_usage(r["id"], tools, digest, guide, changes, trial)
        return changed and old is not None, trial

    def run_due(self, limit: int = 100) -> dict:
        due = self.store.due_for_capability(time.time(), self.max_age, limit)
        if not due:
            return {"checked": 0}
        by_host: dict[str, list[dict]] = defaultdict(list)
        for r in due:
            by_host[r.get("host") or r["url"]].append(r)
        http = self._fixed_http or httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0, pool=30.0), follow_redirects=False)
        results, lock = [], threading.Lock()

        def work(resources: list[dict]) -> None:
            for i, r in enumerate(resources):
                if i:
                    time.sleep(self.per_host_delay)
                try:
                    probed, err = self.probe(r["url"], http, trial_for=self._trial_decider(r)), None
                except (httpx.PoolTimeout, httpx.ProxyError):
                    probed, err = None, "local"
                except (httpx.HTTPError, DiscoveryError, ValueError) as exc:
                    probed, err = None, f"{type(exc).__name__}: {exc}"[:300]
                with lock:
                    results.append((r, probed, err))

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(work, by_host.values()))
        finally:
            if http is not self._fixed_http:
                http.close()

        failed = sum(1 for _, probed, _ in results if probed is None)
        outage = len(results) >= 20 and failed / len(results) >= 0.8
        stats = defaultdict(int)
        for r, probed, err in results:
            if probed is None and (outage or err == "local"):
                stats["postponed"] += 1  # 우리 쪽 문제일 수 있어 기록하지 않고 다음에 다시
                continue
            caps = cons.from_tools(probed["tools"]) if probed else None
            self.store.record_capability(r["id"], caps, err)
            stats["ok" if caps else "failed"] += 1
            if caps and (caps["languages"] or caps["regions"]):
                stats["with_language_or_region"] += 1
            if probed:
                changed, trial = self._record_usage(r, probed)
                stats["usage_changed"] += int(changed)
                if trial:
                    stats["trial_ok" if trial.get("ok") else "trial_failed"] += 1
        return {"checked": len(results), "local_network_problem": outage, **stats}
