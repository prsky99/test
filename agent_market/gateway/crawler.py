"""공개 레지스트리에서 에이전트/유료 API를 수집하고, 추천 전에 살아 있는지 확인한다.

소스
- x402 Bazaar (Coinbase CDP 공개 discovery API): USDC로 호출당 결제받는 에이전트·API. 30일 호출 수 등 품질 지표 포함.
- MCP Registry (modelcontextprotocol.io): 원격 MCP 서버 (대부분 무료 도구).
- 직접 등록된 에이전트 (agent card, 기존 브로커 형식).
모두 API 키 없이 접근 가능하다.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .classify import classify
from .store import Store

log = logging.getLogger("agent_market.gateway.crawler")

X402_DISCOVERY = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"

# (네트워크, USDC 컨트랙트) — 가격을 USDC로 비교할 수 있는 경우만 price_usdc를 채운다.
USDC_ASSETS = {
    "eip155:8453": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "eip155:84532": "0x036cbd53842c5426634e7929541ec2318f3dcf7e",
    "eip155:42161": "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
    "eip155:137": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
    "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "epjfwdd5aufqssqem2qn1xzybapc8g4wegggkzwytdt1v",
}
LEGACY_NETWORKS = {"base": "eip155:8453", "base-sepolia": "eip155:84532", "polygon": "eip155:137", "arbitrum": "eip155:42161", "solana": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"}


def _ts(value) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _name_from_url(url: str) -> str:
    p = urlparse(url)
    return (p.hostname or url) + (p.path if p.path not in ("", "/") else "")


def usdc_price(accepts: list[dict]) -> tuple[int, str | None, str] | None:
    """결제 조건(accepts) 중 USDC로 비교 가능한 최저 가격 (금액, 받는 주소, 네트워크)."""
    best = None
    for a in accepts:
        if not isinstance(a, dict):
            continue
        net = LEGACY_NETWORKS.get(a.get("network"), a.get("network"))
        try:
            amount = int(a.get("amount") or a.get("maxAmountRequired"))
        except (TypeError, ValueError):
            continue
        if net and USDC_ASSETS.get(net) == str(a.get("asset", "")).lower() and (best is None or amount < best[0]):
            best = (amount, a.get("payTo"), net)
    return best


def parse_x402_item(item: dict) -> dict | None:
    url = item.get("resource")
    if not isinstance(url, str) or not url.startswith("https://") or any(c in url for c in "{}<>"):
        return None
    accepts = [a for a in item.get("accepts") or [] if isinstance(a, dict)]
    if not accepts:
        return None
    networks = {LEGACY_NETWORKS.get(a.get("network"), a.get("network")) for a in accepts if a.get("network")}
    best = usdc_price(accepts)
    quality = item.get("quality") or {}
    info = ((item.get("extensions") or {}).get("bazaar") or {}).get("info") or {}
    description = str(item.get("description") or "")
    name = _name_from_url(url)
    return {
        "key": f"x402:{url}",
        "source": "x402-bazaar",
        "kind": "x402",
        "url": url,
        "name": name,
        "description": description,
        "category": classify(f"{name} {description}"),
        "networks": sorted(networks),
        "price_usdc": best[0] if best else None,
        "pay_to": best[1] if best else None,
        "method": (info.get("input") or {}).get("method"),
        "details": {"accepts": accepts[:4], "input": info.get("input"), "x402Version": item.get("x402Version")},
        "calls_30d": quality.get("l30DaysTotalCalls"),
        "payers_30d": quality.get("l30DaysUniquePayers"),
        "last_called": _ts(quality.get("lastCalledAt")),
    }


def parse_mcp_item(item: dict) -> dict | None:
    server = item.get("server") or {}
    meta = (item.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
    if meta.get("status", "active") != "active" or meta.get("isLatest") is False:
        return None
    # {tenant} 같은 템플릿 변수가 든 주소는 사용자가 값을 채워야 해서 바로 쓸 수도, 점검할 수도 없다
    remotes = [r for r in server.get("remotes") or []
               if str(r.get("url", "")).startswith("https://") and not any(c in str(r["url"]) for c in "{}<>")]
    if not remotes:
        return None
    name = str(server.get("title") or server.get("name") or "")
    description = str(server.get("description") or "")
    return {
        "key": f"mcp:{server.get('name')}",
        "source": "mcp-registry",
        "kind": "mcp",
        "url": remotes[0]["url"],
        "name": name,
        "description": description,
        "category": classify(f"{name} {description}"),
        "networks": [],
        "price_usdc": 0,
        "pay_to": None,
        "method": None,
        "details": {"registry_name": server.get("name"), "version": server.get("version"), "remotes": remotes[:3],
                    "website": server.get("websiteUrl"), "repository": (server.get("repository") or {}).get("url")},
        "calls_30d": None,
        "payers_30d": None,
        "last_called": _ts(meta.get("updatedAt")),
    }


class Crawler:
    """레지스트리를 한 바퀴씩 수집한다. 수집 에이전트는 한 바퀴가 끝나면 바로 다음 바퀴를 시작한다.

    부하 관리
    - 페이지 사이에 page_delay(기본 1초)를 둬서 초당 요청 수를 일정하게 유지한다. 에이전트가 늘면
      한 바퀴가 길어질 뿐 순간 부하는 늘지 않는다.
    - MCP Registry는 updated_since로 바뀐 것만 받고(증분), 삭제 확인용 전체 수집은 full_interval(기본 24시간)마다.
      x402 Bazaar는 변경분 조회를 지원하지 않아 매 바퀴 전체를 훑는다.
    - 내용이 그대로인 항목은 DB에 다시 쓰지 않는다(확인 시각만 갱신). 페이지 단위로 한 번에 커밋한다.
    - 진행 위치를 저장해 재시작해도 이어서 수집한다.
    - 전체 수집 2번 연속으로 보이지 않은 에이전트만 비활성화한다(수집 중 목록 순서가 바뀌어 한 번 놓친 것은 무시).
    """

    RESUME_WINDOW = 6 * 3600  # 이보다 오래된 진행 위치는 버리고 새로 시작

    def __init__(self, store: Store, http: httpx.Client | None = None, page_delay: float = 1.0, max_pages: int = 5000,
                 full_interval: float = 86400, should_stop=None):
        self.store = store
        self._fixed_http = http  # 없으면 바퀴마다 새 연결을 만든다 (오래된 연결이 망가지는 것 방지)
        self.http = http
        self.page_delay = page_delay
        self.max_pages = max_pages
        self.full_interval = full_interval
        self.retry_delay = 2.0
        self.should_stop = should_stop or (lambda: False)
        self._lock = threading.Lock()

    def crawl_all(self) -> dict:
        """모든 소스를 한 바퀴 수집. 이미 수집 중이면 {"busy": True}."""
        if not self._lock.acquire(blocking=False):
            return {"busy": True}
        try:
            if self._fixed_http is None:
                self.http = httpx.Client(timeout=30.0, headers={"user-agent": "agent-gateway/0.1"})
            report = {}
            for name in ("x402-bazaar", "mcp-registry"):
                started = time.time()
                try:
                    report[name] = self._pass(name)
                except Exception as exc:  # 한 소스가 실패해도 다른 소스는 계속 (진행 위치는 남아 다음에 이어 감)
                    log.exception("crawl %s failed", name)
                    report[name] = {"ok": False, "error": str(exc)[:300], "seconds": round(time.time() - started, 1)}
                self.store.record_crawl_run(name, report[name])
                if self.should_stop():
                    break
            self.store.set_meta("last_crawl", {"at": time.time(), "report": report})
            return report
        finally:
            if self._fixed_http is None and self.http is not None:
                self.http.close()
            self._lock.release()

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(4):
            try:
                resp = self.http.get(url, params=params)
            except httpx.TransportError:  # 시간 초과·연결 끊김: 한 페이지 때문에 바퀴 전체를 버리지 않도록 재시도
                if attempt == 3:
                    raise
                time.sleep(self.retry_delay * 2 ** attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    def _mode(self, name: str) -> str:
        if name == "x402-bazaar":
            return "full"
        last_full = self.store.get_meta(f"crawl_last_full:{name}")
        return "incremental" if last_full and time.time() - last_full < self.full_interval else "full"

    def _pass(self, name: str) -> dict:
        key = f"crawl_pass:{name}"
        mode = self._mode(name)
        state = self.store.get_meta(key)
        resumed = bool(state and state.get("mode") == mode and time.time() - state["started"] < self.RESUME_WINDOW)
        if not resumed:
            state = {"mode": mode, "started": time.time(), "position": None, "pages": 0,
                     "seen": 0, "new": 0, "changed": 0, "unchanged": 0}
            if mode == "incremental":  # 지난번 수집 시작 5분 전부터 바뀐 것 (겹쳐서 놓치지 않게)
                since = (self.store.get_meta(f"crawl_last_start:{name}") or time.time() - self.full_interval) - 300
                state["since"] = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fetch = self._x402_page if name == "x402-bazaar" else self._mcp_page

        while state["pages"] < self.max_pages:
            records, next_position = fetch(state)
            counts = self.store.upsert_page(records)
            state["pages"] += 1
            state["seen"] += len(records)
            for k, v in counts.items():
                state[k] += v
            state["position"] = next_position
            self.store.set_meta(key, state)  # 진행 위치 저장 (재시작 시 이어서)
            if next_position is None:
                break
            if self.should_stop():
                return {"ok": True, "interrupted": True, **self._summary(state, resumed)}
            time.sleep(self.page_delay)

        deactivated = 0
        if mode == "full":
            previous = self.store.get_meta(f"crawl_prev_full_start:{name}")
            if previous:  # 이전 전체 수집 시작 이후 한 번도 안 보임 = 2번 연속 안 보임
                deactivated = self.store.deactivate_unseen(name, previous)
            self.store.set_meta(f"crawl_prev_full_start:{name}", state["started"])
            self.store.set_meta(f"crawl_last_full:{name}", time.time())
        self.store.set_meta(f"crawl_last_start:{name}", state["started"])
        self.store.set_meta(key, None)
        return {"ok": True, "deactivated": deactivated, **self._summary(state, resumed)}

    @staticmethod
    def _summary(state: dict, resumed: bool) -> dict:
        return {"mode": state["mode"], "resumed": resumed, "pages": state["pages"], "seen": state["seen"], "new": state["new"],
                "changed": state["changed"], "unchanged": state["unchanged"], "seconds": round(time.time() - state["started"], 1)}

    def _x402_page(self, state: dict) -> tuple[list[dict], int | None]:
        offset, limit = state["position"] or 0, 100
        data = self._get(X402_DISCOVERY, {"limit": limit, "offset": offset})
        items = data.get("items") or []
        records = [p for p in (parse_x402_item(i) for i in items) if p]
        total = (data.get("pagination") or {}).get("total", 0)
        offset += limit
        return records, (offset if items and offset < total else None)

    def _mcp_page(self, state: dict) -> tuple[list[dict], str | None]:
        params = {"limit": 100, "version": "latest"}  # 서버마다 최신 버전만 (전체 버전 목록은 5배 이상 길다)
        if state["position"]:
            params["cursor"] = state["position"]
        if state.get("since"):
            params["updated_since"] = state["since"]
        data = self._get(MCP_REGISTRY, params)
        records = [p for p in (parse_mcp_item(i) for i in data.get("servers") or []) if p]
        return records, (data.get("metadata") or {}).get("nextCursor") or None


class Prober:
    """게이트웨이가 추천 직전에 쓰는 점검. 수집 에이전트가 최근에 점검했으면 그 결과를 그대로 쓴다."""

    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False, max_age: float = 3600, checker=None):
        from ..collector.health import HealthChecker

        self.store = store
        self.max_age = max_age
        self.checker = checker or HealthChecker(store, http=http, allow_private=allow_private)

    def probe(self, resource: dict, force: bool = False) -> bool | None:
        """True: 방금 점검해서 정상, False: 지금 사용 불가, None: 최근 점검 결과가 정상이라 생략."""
        if not force and resource.get("last_check_at") and time.time() - resource["last_check_at"] < self.max_age:
            return None if resource.get("health_status") in ("healthy", "reachable") else False
        state = self.checker.check_and_record(resource)
        resource.update(self.store.resource(resource["id"]) or {})
        return state.get("status") in ("healthy", "reachable")
