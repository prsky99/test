"""에이전트 헬스체크.

프로토콜별로 "실제로 서비스할 수 있는지"를 확인한다.
- x402: 결제 없이 요청하면 402와 유효한 결제 조건(accepts)을 돌려줘야 정상(healthy). 가격이 바뀌었으면 갱신.
- MCP(streamable HTTP): JSON-RPC initialize에 result로 응답하면 정상. 401/403(인증 필요)은 응답 가능(reachable).
- A2A: agent card(/.well-known/agent-card.json, 구 agent.json)가 열리고 A2A card 모양이면 정상.
5xx·타임아웃·연결 실패·404/410은 실패. 3번 연속 실패하면 down(추천에서 제외)으로 표시한다.
down 에이전트도 계속 같은 주기로 점검해 회복되면 바로 healthy로 되돌린다.
실패가 7일 넘게 이어지면 retired로 표시하고 점검·추천에서 완전히 제외한다.

우리 쪽 네트워크 문제(연결 풀 대기 초과, 프록시 오류)는 에이전트 실패로 기록하지 않는다.
한 묶음에서 대부분(80% 이상)이 동시에 실패하면 서로 다른 수백 개 호스트가 한꺼번에 죽었다기보다
우리 쪽 문제로 보고, 실패 결과를 버리고 잠시 뒤 다시 점검한다. 묶음마다 새 HTTP 연결을 써서
망가진 연결(죽은 프록시 터널 등)이 계속 남지 않게 한다.

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

from ..broker.discovery import DiscoveryError, check_public_url, public_client
from ..config import DEFAULT_HEALTH_INTERVAL_SECONDS
from ..gateway.crawler import usdc_price
from ..gateway.store import Store
from ..observation_guards import GuardError

log = logging.getLogger("agent_market.collector.health")

USER_AGENT = "agent-collector/0.1 (+health check; no payment is made)"
MCP_DISCOVER = {
    "jsonrpc": "2.0", "id": 1, "method": "server/discover",
    "params": {},
}
MCP_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2026-07-28", "capabilities": {}, "clientInfo": {"name": "agent-collector", "version": "0.1"}},
}
MAX_BODY = 64 * 1024
LEASE = 900  # 고른 뒤 결과를 기록할 때까지 '점검 중'으로 잡아 두는 시간


@dataclass
class CheckResult:
    outcome: str  # healthy | reachable | fail
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    observed_price: int | None = None
    observed_pay_to: str | None = None
    local: bool = False  # 우리 쪽 문제 (에이전트 실패로 기록하지 않음)
    auth: bool | None = None  # MCP: 인증이 필요한지 (401/403 → True, 인증 없이 initialize 성공 → False)


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
    interval: float = DEFAULT_HEALTH_INTERVAL_SECONDS  # 일반·down 에이전트: 기본 6시간마다
    in_use_interval: float = 900  # 고객에게 소개된 에이전트, 실패가 시작된 에이전트: 15분마다
    down_after: int = 3
    retire_after: float = 7 * 86400  # 7일 넘게 계속 실패하면 제외
    jitter: float = 0.1


class HealthChecker:
    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False,
                 schedule: Schedule = Schedule(), workers: int = 32, per_host_delay: float = 1.0, per_host_cap: int = 10,
                 outage_ratio: float = 0.8, outage_min: int = 20):
        self.store = store
        self._fixed_http = http  # 테스트 등에서 주입한 클라이언트. 없으면 묶음마다 새로 만든다.
        self.outage_ratio = outage_ratio
        self.outage_min = outage_min
        self.allow_private = allow_private
        self.schedule = schedule
        self.workers = workers
        self.per_host_delay = per_host_delay
        self.per_host_cap = per_host_cap  # 한 묶음에서 호스트당 최대 점검 수 (한 호스트가 묶음을 붙잡지 않게)
        self._host_sizes: Counter = Counter()
        self._host_sizes_at = 0.0
        # 여러 묶음을 동시에 돌릴 때: 고르는 순간 '점검 중'으로 잡아 두고(lease), 다른 묶음이 점검 중인 호스트는 고르지 않는다
        self._claim_lock = threading.Lock()
        self._busy_hosts: set[str] = set()

    def host_sizes(self) -> Counter:
        """호스트별 점검 대상 엔드포인트 수 (10분마다 갱신)."""
        if time.time() - self._host_sizes_at > 600:
            native = getattr(self.store, 'health_host_sizes', None)
            rows = native() if callable(native) else self.store.query("SELECT host, COUNT(*) AS n FROM resources WHERE active=1 AND health_status != 'retired' GROUP BY host")
            self._host_sizes = Counter({r["host"]: r["n"] for r in rows})
            self._host_sizes_at = time.time()
        return self._host_sizes

    def _new_client(self) -> httpx.Client:
        if self._fixed_http is not None:
            return self._fixed_http
        return public_client(self.allow_private, timeout=httpx.Timeout(8.0, connect=5.0, pool=30.0), follow_redirects=False,
                             headers={"user-agent": USER_AGENT}, limits=httpx.Limits(max_connections=200, max_keepalive_connections=50))

    def _close(self, client: httpx.Client) -> None:
        if client is not self._fixed_http:
            client.close()

    # ---------------- 단건 점검 ----------------
    def check(self, resource: dict, http: httpx.Client | None = None) -> CheckResult:
        own = http is None
        http = http or self._new_client()
        try:
            return self._check(resource, http)
        finally:
            if own:
                self._close(http)

    def _check(self, resource: dict, http: httpx.Client) -> CheckResult:
        url = resource["url"]
        if not self.allow_private:
            try:
                check_public_url(url)
            except DiscoveryError as exc:
                return CheckResult("fail", error=f"blocked: {exc}")
        started = time.monotonic()
        try:
            if resource["kind"] == "mcp":
                result = self._check_mcp(http, url)
            elif resource["kind"] == "a2a":
                result = self._check_a2a(http, resource)
            else:
                result = self._check_x402(http, resource)
        except (httpx.PoolTimeout, httpx.ProxyError) as exc:
            result = CheckResult("fail", error=f"local: {type(exc).__name__}", local=True)
        except httpx.TimeoutException:
            result = CheckResult("fail", error="timeout")
        except httpx.HTTPError as exc:
            result = CheckResult("fail", error=f"{type(exc).__name__}: {exc}"[:300])
        except DiscoveryError as exc:
            result = CheckResult("fail", error=f"blocked: {exc}"[:300])
        except Exception as exc:  # 잘못된 URL 등: 점검을 멈추지 않고 실패로 기록
            log.warning("health check error for %s: %s", url, exc)
            result = CheckResult("fail", error=f"{type(exc).__name__}: {exc}"[:300])
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    def _read(self, resp: httpx.Response, limit: int = MAX_BODY) -> bytes:
        body = b""
        for chunk in resp.iter_bytes():
            body += chunk
            if len(body) >= limit:
                break
        return body

    def _check_x402(self, http: httpx.Client, resource: dict) -> CheckResult:
        method = (resource.get("method") or "GET").upper()
        kwargs = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
        with http.stream(method if method in ("GET", "POST", "PUT", "PATCH") else "GET", resource["url"], **kwargs) as resp:
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

    def _check_mcp(self, http: httpx.Client, url: str) -> CheckResult:
        headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
        # 1. 최신 2026-07-28 사양: server/discover (무상태)
        with http.stream("POST", url, json=MCP_DISCOVER, headers=headers) as resp:
            body = self._read(resp)
            session = resp.headers.get("mcp-session-id")
        code = resp.status_code
        if session:  # 점검용 세션이 생겼으면 바로 정리
            try:
                http.delete(url, headers={"mcp-session-id": session})
            except httpx.HTTPError:
                pass
        if code == 200 and b'"result"' in body:
            return CheckResult("healthy", code, auth=False)
        if code in (401, 403):
            return CheckResult("reachable", code, error="auth required", auth=True)
        # server/discover를 모르는 기존 서버는 -32601(Method not found)이나 에러를 반환할 수 있으므로 initialize로 폴백
        # 2. 구형 사양: initialize (세션 핸드셰이크)
        with http.stream("POST", url, json=MCP_INIT, headers=headers) as resp:
            body = self._read(resp)
            session = resp.headers.get("mcp-session-id")
        code = resp.status_code
        if session:  # 점검용으로 만든 세션은 바로 정리
            try:
                http.delete(url, headers={"mcp-session-id": session})
            except httpx.HTTPError:
                pass
        if code == 200 and b'"result"' in body:
            return CheckResult("healthy", code, auth=False)
        if code in (401, 403):
            return CheckResult("reachable", code, error="auth required", auth=True)
        if code in (404, 410) or code >= 500:
            return CheckResult("fail", code, error=f"HTTP {code}")
        return CheckResult("reachable", code, error=f"HTTP {code}")

    def _check_a2a(self, http: httpx.Client, resource: dict) -> CheckResult:
        """agent card가 열리고 A2A card 모양(name·skills)이면 정상. 조사에서 찾은 card 주소가 있으면 그것만 본다."""
        from .a2a import card_candidates
        details = {}
        try:
            details = json.loads(resource.get("details") or "{}")
            if not isinstance(details, dict):
                details = {}
        except Exception:
            details = {}
        found = None
        try:
            guide = json.loads(resource.get("usage_guide") or "{}")
            if isinstance(guide, dict):
                found = guide.get("agent_card")
        except Exception:
            pass
        urls = [found] if found else card_candidates(resource["url"], details.get("agent_card") if isinstance(details, dict) else None)[:3]
        last = None
        last_err = None
        for url in urls:
            if not self.allow_private:
                try:
                    check_public_url(url)
                except DiscoveryError as exc:
                    last_err = f"blocked: {exc}"
                    continue
            with http.stream("GET", url, headers={"accept": "application/json"}) as resp:
                body = self._read(resp, 512 * 1024)
            last = resp.status_code
            if resp.status_code == 200:
                try:
                    data = json.loads(body)
                except ValueError:
                    continue
                if isinstance(data, dict) and data.get("name") and isinstance(data.get("skills"), list):
                    return CheckResult("healthy", 200)
        if last is None:
            return CheckResult("fail", None, error=(last_err or "no reachable A2A card URL")[:300])
        if last >= 500 or last in (404, 410) or last == 200:
            return CheckResult("fail", last, error="no A2A agent card" if last == 200 else f"HTTP {last}")
        return CheckResult("reachable", last, error=f"HTTP {last}")

    # ---------------- Schedule & Recording ----------------
    def next_check_at(self, state_failures: int, in_use: bool, now: float, host_size: int = 1) -> float:
        s = self.schedule
        # Cannot be shorter than the time required to complete one full cycle of the same host
        host_min = host_size * (self.per_host_delay + 0.5) * 1.2
        interval = max(s.interval, host_min)
        if state_failures >= s.down_after:
            delay = interval
        elif in_use:
            delay = s.in_use_interval
        elif state_failures:
            # Prevent dense clusters of failing endpoints on large hosts from collapsing schedule
            delay = max(s.in_use_interval, host_min) if host_size > 10 else s.in_use_interval
        else:
            delay = interval
        return now + delay * (1 + random.uniform(-s.jitter, s.jitter))

    def check_and_record(self, resource: dict, in_use: bool = False) -> dict:
        try:
            guard = self.store.observation_guard(resource["id"], "health", expected_resource=resource)
            result = self.check(resource)
            with self.store.observation_transaction(guard):
                if result.local:
                    self.store.postpone([resource["id"]], time.time() + 300)
                    return {"status": resource.get("health_status"), "previous": resource.get("health_status"),
                            "postponed": True, "accepted": False}
                return {**self.record(resource, result, in_use), "accepted": True}
        except GuardError:
            return {"status": None, "previous": resource.get("health_status"), "accepted": False, "stale": True}

    def record(self, resource: dict, result: CheckResult, in_use: bool = False) -> dict:
        failures = 0 if result.outcome != "fail" else (resource.get("consecutive_failures") or 0) + 1
        host_size = self.host_sizes().get(resource.get("host") or urlparse(resource["url"]).hostname, 1)
        state = self.store.record_health(
            resource["id"], result.outcome, result.status_code, result.latency_ms, result.error,
            next_check_at=self.next_check_at(failures, in_use, time.time(), host_size), down_after=self.schedule.down_after,
            retire_after=self.schedule.retire_after,
            observed_price=result.observed_price, observed_pay_to=result.observed_pay_to, auth_observed=result.auth,
        )
        if state.get("previous") not in (None, "unknown") and state.get("status") != state.get("previous"):
            log.info("agent %s (%s): %s -> %s", resource["id"], resource["url"], state["previous"], state["status"])
        return state

    # ---------------- 일괄 점검 ----------------
    def run_due(self, limit: int = 500, kind: str | list[str] | tuple[str, ...] | None = None) -> dict:
        """점검 시각이 된 에이전트들을 호스트별로 묶어 병렬 점검한다. 호스트당 per_host_cap개까지만 담는다.
        kind가 지정되면 해당 에이전트 종류(a2a, mcp, x402 등)만 분산 점검한다."""
        def host(r):
            return r.get("host") or urlparse(r["url"]).hostname or r["url"]

        with self._claim_lock:
            due = [r for r in self.store.due_for_check(time.time(), limit * 2, per_host=self.per_host_cap, kind=kind)
                   if host(r) not in self._busy_hosts][:limit]
            claimed = {host(r) for r in due}
            self._busy_hosts |= claimed
            if due:  # 결과를 기록하기 전까지 다른 묶음이 다시 고르지 않게. 프로세스가 죽어도 LEASE 뒤에 다시 점검됨
                self.store.postpone([r["id"] for r in due], time.time() + LEASE)
        try:
            res = self._run_batch(due, host)
            if kind:
                res["kind"] = kind if isinstance(kind, str) else ",".join(kind)
            return res
        finally:
            with self._claim_lock:
                self._busy_hosts -= claimed

    def _run_batch(self, due: list[dict], host) -> dict:
        by_host: dict[str, list[dict]] = defaultdict(list)
        for r in due:
            by_host[host(r)].append(r)
        if not due:
            return {"checked": 0, "accepted": 0, "stale": 0}
        in_use = self.store.in_use_ids()
        results = []
        lock = threading.Lock()
        http = self._new_client()

        def work(resources: list[dict]) -> None:
            for i, r in enumerate(resources):
                if i:
                    time.sleep(self.per_host_delay)
                guard = None
                try:
                    guard = self.store.observation_guard(r["id"], "health", expected_resource=r)
                    result = self.check(r, http)
                except GuardError:
                    result = None
                except Exception:
                    log.exception("health check crashed for %s", r["url"])
                    result = CheckResult("fail", error="checker crashed", local=True)
                with lock:
                    results.append((r, result, guard))

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(work, by_host.values()))
        finally:
            self._close(http)

        net_candidates = [(r, res) for r, res, guard in results
                          if guard is not None and res is not None and r.get("health_status") not in ("failing", "down")]
        net_fails = sum(1 for _, res in net_candidates if res.outcome == "fail" and res.status_code is None)
        outage = len(net_candidates) >= self.outage_min and net_fails / len(net_candidates) >= self.outage_ratio
        if outage:
            log.warning("local network problem suspected: %d/%d checks failed in one batch; not recording failures", net_fails, len(net_candidates))
        stats = defaultdict(int, accepted=0, stale=0)
        for r, res, guard in results:
            if guard is None or res is None:
                stats["stale"] += 1
                continue
            try:
                with self.store.observation_transaction(guard):
                    if res.local or (outage and res.outcome == "fail"):
                        self.store.postpone([r["id"]], time.time() + 300)
                        postponed = True
                        state = None
                    else:
                        state = self.record(r, res, in_use=r["id"] in in_use)
                        postponed = False
            except GuardError:
                stats["stale"] += 1
                continue
            if postponed:
                stats["postponed"] += 1
                continue
            stats["accepted"] += 1
            stats[state.get("status", "error")] += 1
            if state.get("price_changed"):
                stats["price_changed"] += 1
            if state.get("previous") in ("healthy", "reachable") and state.get("status") == "down":
                stats["went_down"] += 1
            if state.get("previous") == "down" and state.get("status") in ("healthy", "reachable"):
                stats["recovered"] += 1
            if state.get("status") == "retired" and state.get("previous") != "retired":
                stats["retired"] += 1
        return {"checked": len(due), "hosts": len(by_host), "local_network_problem": outage, **stats}

    # ---------------- 스캐빈저 (7일 이상 retired 에이전트 재점검) ----------------
    def probe_lightweight(self, resource: dict, http: httpx.Client) -> tuple[bool, int | None, str | None]:
        """초경량 프로브 (Zero-payload HEAD / Ping).
        200, 402, 401, 403, 405 등 '서버가 응답함' 코드가 나오면 True(부활 후보).
        404, 410, 500, 타임아웃, 연결 거부면 False(계속 휴면).
        """
        url = resource["url"]
        if not self.allow_private:
            try:
                check_public_url(url)
            except DiscoveryError as exc:
                return False, None, f"blocked: {exc}"
        try:
            # 1. HEAD 요청 먼저 시도 (바디 0바이트)
            resp = http.head(url, timeout=5.0)
            code = resp.status_code
            if code in (200, 204, 301, 302, 401, 402, 403, 405):
                return True, code, None
            if code in (404, 410) or code >= 500:
                return False, code, f"HTTP {code}"
        except (httpx.RequestError, Exception):
            pass

        # 2. HEAD 실패 또는 미지원 시 초경량 GET (최대 1KB)
        try:
            with http.stream("GET", url, timeout=5.0) as resp:
                code = resp.status_code
                self._read(resp, limit=1024)
            if code in (200, 204, 301, 302, 401, 402, 403, 405):
                return True, code, None
            return False, code, f"HTTP {code}"
        except httpx.TimeoutException:
            return False, None, "timeout"
        except Exception as exc:
            return False, None, f"{type(exc).__name__}: {exc}"[:200]

    def scavenge_retired(self, limit: int = 50) -> dict:
        """7일 이상 실패한 retired 에이전트들을 점검하여 복구된 서버를 탐지(Revival)."""
        now = time.time()
        due = self.store.due_for_scavenge(now, limit=limit, per_host=1)
        if not due:
            return {"scavenged": 0, "revived": 0, "still_dead": 0}

        revived, dead, stale, postponed = 0, 0, 0, 0
        http = self._new_client()
        try:
            for r in due:
                try:
                    guard = self.store.observation_guard(r["id"], "health", expected_resource=r)
                    observed_at = time.time()
                    alive, code, err = self.probe_lightweight(r, http)
                    res = self.check(r, http) if alive else None
                    with self.store.observation_transaction(guard):
                        if res is not None and res.local:
                            self.store.postpone([r["id"]], time.time() + 300)
                            outcome = "postponed"
                        elif res is not None and res.outcome in ("healthy", "reachable"):
                            self.record(r, res, in_use=False)
                            if not r.get("active") and (r.get("inactive_reason") or "").startswith("unhealthy:"):
                                if hasattr(self.store, "activate_revived_resource"):
                                    self.store.activate_revived_resource(r["id"])
                            outcome = "revived"
                        else:
                            self.store.record_scavenge_failure(r["id"], observed_at, err or (f"HTTP {code}" if code is not None else None))
                            outcome = "dead"
                    if outcome == "postponed": postponed += 1
                    elif outcome == "revived":
                        revived += 1
                        log.info("REVIVAL: agent #%s (%s) revived from retired! status: %s (code %s)",
                                 r["id"], r["url"], res.outcome, res.status_code)
                    else: dead += 1
                except GuardError:
                    stale += 1
        finally:
            self._close(http)

        return {"scavenged": len(due), "revived": revived, "still_dead": dead,
                "accepted": revived + dead, "stale": stale, "postponed": postponed}
