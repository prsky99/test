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
                 max_age: float = 86400, workers: int = 8, per_host_delay: float = 1.0):
        self.store = store
        self._fixed_http = http
        self.allow_private = allow_private
        self.max_age = max_age
        self.workers = workers
        self.per_host_delay = per_host_delay

    def probe(self, url: str, http: httpx.Client) -> list[dict]:
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
        try:
            http.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
            listed = parse_jsonrpc(http.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)) or {}
        finally:
            if sid:
                try:
                    http.delete(url, headers=headers)
                except httpx.HTTPError:
                    pass
        tools = (listed.get("result") or {}).get("tools")
        if not isinstance(tools, list):
            raise ValueError("tools/list failed")
        return tools

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
                    caps, err = cons.from_tools(self.probe(r["url"], http)), None
                except (httpx.PoolTimeout, httpx.ProxyError):
                    caps, err = None, "local"
                except (httpx.HTTPError, DiscoveryError, ValueError) as exc:
                    caps, err = None, f"{type(exc).__name__}: {exc}"[:300]
                with lock:
                    results.append((r, caps, err))

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(work, by_host.values()))
        finally:
            if http is not self._fixed_http:
                http.close()

        failed = sum(1 for _, caps, _ in results if caps is None)
        outage = len(results) >= 20 and failed / len(results) >= 0.8
        stats = defaultdict(int)
        for r, caps, err in results:
            if caps is None and (outage or err == "local"):
                stats["postponed"] += 1  # 우리 쪽 문제일 수 있어 기록하지 않고 다음에 다시
                continue
            self.store.record_capability(r["id"], caps, err)
            stats["ok" if caps else "failed"] += 1
            if caps and (caps["languages"] or caps["regions"]):
                stats["with_language_or_region"] += 1
        return {"checked": len(results), "local_network_problem": outage, **stats}
