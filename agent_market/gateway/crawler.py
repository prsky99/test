"""공개 레지스트리에서 에이전트/유료 API를 수집하고, 추천 전에 살아 있는지 확인한다.

소스
- x402 Bazaar (Coinbase CDP 공개 discovery API): USDC로 호출당 결제받는 에이전트·API. 30일 호출 수 등 품질 지표 포함.
- MCP Registry (modelcontextprotocol.io): 원격 MCP 서버 (대부분 무료 도구).
- 직접 등록된 에이전트 (agent card, 기존 브로커 형식).
모두 API 키 없이 접근 가능하다.
"""

import logging
import time
from datetime import datetime
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
        "details": {"registry_name": server.get("name"), "version": server.get("version"), "remotes": remotes[:3]},
        "calls_30d": None,
        "payers_30d": None,
        "last_called": _ts(meta.get("updatedAt")),
    }


class Crawler:
    def __init__(self, store: Store, http: httpx.Client | None = None, page_delay: float = 0.3, max_pages: int = 400):
        self.store = store
        self.http = http or httpx.Client(timeout=30.0, headers={"user-agent": "agent-gateway/0.1"})
        self.page_delay = page_delay
        self.max_pages = max_pages

    def crawl_all(self) -> dict:
        report = {}
        for name, fn in (("x402-bazaar", self.crawl_x402), ("mcp-registry", self.crawl_mcp)):
            started = time.time()
            try:
                count = fn()
                # 이번 수집에서 보이지 않은 에이전트는 목록에서 내려간 것으로 보고 비활성화
                removed = self.store.deactivate_unseen(name, started - 1)
                new = self.store.query("SELECT COUNT(*) AS n FROM resources WHERE source=? AND first_seen>=?", (name, started - 1))[0]["n"]
                report[name] = {"ok": True, "seen": count, "new": new, "deactivated": removed, "seconds": round(time.time() - started, 1)}
            except Exception as exc:  # 한 소스가 실패해도 다른 소스는 계속
                log.exception("crawl %s failed", name)
                report[name] = {"ok": False, "error": str(exc)[:300], "seconds": round(time.time() - started, 1)}
            self.store.record_crawl_run(name, report[name])
        self.store.set_meta("last_crawl", {"at": time.time(), "report": report})
        return report

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(4):
            resp = self.http.get(url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    def crawl_x402(self) -> int:
        seen, offset, limit = 0, 0, 100
        for _ in range(self.max_pages):
            data = self._get(X402_DISCOVERY, {"limit": limit, "offset": offset})
            items = data.get("items") or []
            for item in items:
                parsed = parse_x402_item(item)
                if parsed:
                    self.store.upsert_resource(parsed)
                    seen += 1
            total = (data.get("pagination") or {}).get("total", 0)
            offset += limit
            if not items or offset >= total:
                break
            time.sleep(self.page_delay)
        return seen

    def crawl_mcp(self) -> int:
        seen, cursor = 0, None
        for _ in range(self.max_pages):
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = self._get(MCP_REGISTRY, params)
            for item in data.get("servers") or []:
                parsed = parse_mcp_item(item)
                if parsed:
                    self.store.upsert_resource(parsed)
                    seen += 1
            cursor = (data.get("metadata") or {}).get("nextCursor")
            if not cursor:
                break
            time.sleep(self.page_delay)
        return seen


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
