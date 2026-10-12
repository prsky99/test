"""에이전트 헬스체크.

프로토콜별로 "실제로 서비스할 수 있는지"를 확인한다.
- x402: 결제 없이 요청하면 402와 유효한 결제 조건(accepts)을 돌려줘야 정상(healthy). 가격이 바뀌었으면 갱신.
- MCP(streamable HTTP): JSON-RPC initialize에 result로 응답하면 정상. 401/403(인증 필요)은 응답 가능(reachable).
- A2A(직접 등록): agent card(/.well-known/agent.json)가 열리면 정상.
5xx·타임아웃·연결 실패·404/410은 실패. 3번 연속 실패하면 down(추천에서 제외)으로 표시한다.
down 에이전트도 계속 같은 주기로 점검해 회복되면 바로 healthy로 되돌린다.
실패가 7일 넘게 이어지면 retired로 표시하고 점검·추천에서 완전히 제외한다.

예의: 같은 호스트에는 동시에 하나씩, 요청 사이에 간격을 두고, User-Agent로 신원을 밝힌다.
엔드포인트가 아주 많은 호스트(한 곳에 수천 개)는 그 간격으로 한 바퀴 도는 데 걸리는 시간만큼 점검 주기를 늘린다.
"""

import base64
import json
import logging
import random
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..broker.discovery import DiscoveryError, check_public_url
from ..gateway.crawler import usdc_price
from ..gateway.store import Store

log = logging.getLogger("agent_market.collector.health")

USER_AGENT = "agent-collector/0.1 (+health check; no payment is made)"
MCP_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "agent-collector", "version": "0.1"}},
}
MAX_BODY = 64 * 1024


@dataclass
class CheckResult:
    outcome: str  # healthy | reachable | fail
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    observed_price: int | None = None
    observed_pay_to: str | None = None


def parse_payment_required(resp: httpx.Response, body: bytes) -> list[dict] | None:
    """402 응답에서 x402 결제 조건 목록을 꺼낸다 (v1: JSON 본문, v2: PAYMENT-REQUIRED 헤더)."""
    candidates = []
    try:
        candidates.append(json.loads(body))
    except ValueError:
        pass
    for name in ("payment-required", "x-payment-required"):
        if value := resp.headers.get(name):
            try:
                candidates.append(json.loads(base64.b64decode(value + "=" * (-len(value) % 4))))
            except (ValueError, TypeError):
                pass
    for c in candidates:
        if isinstance(c, dict) and isinstance(c.get("accepts"), list) and c["accepts"]:
            return c["accepts"]
    return None


@dataclass(frozen=True)
class Schedule:
    interval: float = 3600  # 일반 에이전트와 down 에이전트: 매시간
    in_use_interval: float = 900  # 고객에게 소개된 에이전트, 실패가 시작된 에이전트: 15분마다
    down_after: int = 3
    retire_after: float = 7 * 86400  # 7일 넘게 계속 실패하면 제외
    jitter: float = 0.1


class HealthChecker:
    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False,
                 schedule: Schedule = Schedule(), workers: int = 32, per_host_delay: float = 1.0, per_host_cap: int = 10):
        self.store = store
        self.http = http or httpx.Client(
            timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=False, headers={"user-agent": USER_AGENT}
        )
        self.allow_private = allow_private
        self.schedule = schedule
        self.workers = workers
        self.per_host_delay = per_host_delay
        self.per_host_cap = per_host_cap  # 한 묶음에서 호스트당 최대 점검 수 (한 호스트가 묶음을 붙잡지 않게)
        self._host_sizes: Counter = Counter()
        self._host_sizes_at = 0.0

    def host_sizes(self) -> Counter:
        """호스트별 점검 대상 엔드포인트 수 (10분마다 갱신)."""
        if time.time() - self._host_sizes_at > 600:
            rows = self.store.query("SELECT url FROM resources WHERE active=1 AND health_status != 'retired'")
            self._host_sizes = Counter(urlparse(r["url"]).hostname or r["url"] for r in rows)
            self._host_sizes_at = time.time()
        return self._host_sizes

    # ---------------- 단건 점검 ----------------
    def check(self, resource: dict) -> CheckResult:
        url = resource["url"]
        if not self.allow_private:
            try:
                check_public_url(url)
            except DiscoveryError as exc:
                return CheckResult("fail", error=f"blocked: {exc}")
        started = time.monotonic()
        try:
            if resource["kind"] == "mcp":
                result = self._check_mcp(url)
            elif resource["kind"] == "a2a":
                result = self._check_a2a(resource)
            else:
                result = self._check_x402(resource)
        except httpx.TimeoutException:
            result = CheckResult("fail", error="timeout")
        except httpx.HTTPError as exc:
            result = CheckResult("fail", error=f"{type(exc).__name__}: {exc}"[:300])
        except Exception as exc:  # 잘못된 URL 등: 점검을 멈추지 않고 실패로 기록
            log.warning("health check error for %s: %s", url, exc)
            result = CheckResult("fail", error=f"{type(exc).__name__}: {exc}"[:300])
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    def _read(self, resp: httpx.Response) -> bytes:
        body = b""
        for chunk in resp.iter_bytes():
            body += chunk
            if len(body) >= MAX_BODY:
                break
        return body

    def _check_x402(self, resource: dict) -> CheckResult:
        method = (resource.get("method") or "GET").upper()
        kwargs = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
        with self.http.stream(method if method in ("GET", "POST", "PUT", "PATCH") else "GET", resource["url"], **kwargs) as resp:
            body = self._read(resp)
        code = resp.status_code
        if code == 402:
            accepts = parse_payment_required(resp, body)
            if accepts:
                price = usdc_price(accepts)
                return CheckResult("healthy", code, observed_price=price[0] if price else None,
                                   observed_pay_to=price[1] if price else None)
            return CheckResult("reachable", code, error="402 without parseable payment requirements")
        if 200 <= code < 300:
            return CheckResult("healthy", code)
        if code in (404, 410) or code >= 500:
            return CheckResult("fail", code, error=f"HTTP {code}")
        return CheckResult("reachable", code, error=f"HTTP {code}")  # 400/405 등: 살아 있지만 결제 조건 확인 불가

    def _check_mcp(self, url: str) -> CheckResult:
        headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
        with self.http.stream("POST", url, json=MCP_INIT, headers=headers) as resp:
            body = self._read(resp)
            session = resp.headers.get("mcp-session-id")
        code = resp.status_code
        if session:  # 점검용으로 만든 세션은 바로 정리
            try:
                self.http.delete(url, headers={"mcp-session-id": session})
            except httpx.HTTPError:
                pass
        if code == 200 and b'"result"' in body:
            return CheckResult("healthy", code)
        if code in (401, 403):
            return CheckResult("reachable", code, error="auth required")
        if code in (404, 410) or code >= 500:
            return CheckResult("fail", code, error=f"HTTP {code}")
        return CheckResult("reachable", code, error=f"HTTP {code}")

    def _check_a2a(self, resource: dict) -> CheckResult:
        card = json.loads(resource.get("details") or "{}").get("agent_card")
        if not card:
            return self._check_x402(resource)
        resp = self.http.get(card)
        if resp.status_code == 200:
            return CheckResult("healthy", 200)
        return CheckResult("fail" if resp.status_code >= 500 or resp.status_code in (404, 410) else "reachable",
                           resp.status_code, error=f"HTTP {resp.status_code}")

    # ---------------- 기록·일정 ----------------
    def next_check_at(self, state_failures: int, in_use: bool, now: float, host_size: int = 1) -> float:
        s = self.schedule
        # 같은 호스트를 per_host_delay 간격으로 한 바퀴 도는 데 걸리는 시간보다 짧게 잡을 수는 없다
        interval = max(s.interval, host_size * (self.per_host_delay + 0.5) * 1.2)
        if state_failures >= s.down_after:
            delay = interval  # down도 계속 점검해 회복을 반영
        elif in_use or state_failures:
            delay = s.in_use_interval  # 소개 중이거나 실패가 막 시작되면 빨리 재확인
        else:
            delay = interval
        return now + delay * (1 + random.uniform(-s.jitter, s.jitter))

    def check_and_record(self, resource: dict, in_use: bool = False) -> dict:
        result = self.check(resource)
        failures = 0 if result.outcome != "fail" else (resource.get("consecutive_failures") or 0) + 1
        host_size = self.host_sizes().get(urlparse(resource["url"]).hostname or resource["url"], 1)
        state = self.store.record_health(
            resource["id"], result.outcome, result.status_code, result.latency_ms, result.error,
            next_check_at=self.next_check_at(failures, in_use, time.time(), host_size), down_after=self.schedule.down_after,
            retire_after=self.schedule.retire_after,
            observed_price=result.observed_price, observed_pay_to=result.observed_pay_to,
        )
        if state.get("previous") not in (None, "unknown") and state.get("status") != state.get("previous"):
            log.info("agent %s (%s): %s -> %s", resource["id"], resource["url"], state["previous"], state["status"])
        return state

    # ---------------- 일괄 점검 ----------------
    def run_due(self, limit: int = 500) -> dict:
        """점검 시각이 된 에이전트들을 호스트별로 묶어 병렬 점검한다. 호스트당 per_host_cap개까지만 담는다."""
        candidates = self.store.due_for_check(time.time(), limit * 4)
        by_host: dict[str, list[dict]] = defaultdict(list)
        due = []
        for r in candidates:
            host = urlparse(r["url"]).hostname or r["url"]
            if len(by_host[host]) < self.per_host_cap and len(due) < limit:
                by_host[host].append(r)
                due.append(r)
        by_host = {h: rs for h, rs in by_host.items() if rs}
        if not due:
            return {"checked": 0}
        in_use = self.store.in_use_ids()
        stats = defaultdict(int)
        lock = threading.Lock()

        def bump(key: str) -> None:
            with lock:
                stats[key] += 1

        def work(resources: list[dict]) -> None:
            for i, r in enumerate(resources):
                if i:
                    time.sleep(self.per_host_delay)
                try:
                    state = self.check_and_record(r, in_use=r["id"] in in_use)
                except Exception:
                    log.exception("health check crashed for %s", r["url"])
                    continue
                bump(state.get("status", "error"))
                if state.get("price_changed"):
                    bump("price_changed")
                if state.get("previous") in ("healthy", "reachable") and state.get("status") == "down":
                    bump("went_down")
                if state.get("previous") == "down" and state.get("status") in ("healthy", "reachable"):
                    bump("recovered")
                if state.get("status") == "retired" and state.get("previous") != "retired":
                    bump("retired")

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(work, by_host.values()))
        return {"checked": len(due), "hosts": len(by_host), **stats}
