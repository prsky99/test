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

from ..broker.discovery import DiscoveryError, check_public_url
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


def parse_x402_item(item: dict) -> dict | None:
    url = item.get("resource")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    accepts = [a for a in item.get("accepts") or [] if isinstance(a, dict)]
    if not accepts:
        return None
    networks, best = set(), None
    for a in accepts:
        net = LEGACY_NETWORKS.get(a.get("network"), a.get("network"))
        if not net:
            continue
        networks.add(net)
        try:
            amount = int(a.get("amount") or a.get("maxAmountRequired"))
        except (TypeError, ValueError):
            continue
        if USDC_ASSETS.get(net) == str(a.get("asset", "")).lower() and (best is None or amount < best[0]):
            best = (amount, a.get("payTo"), net)
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
    remotes = [r for r in server.get("remotes") or [] if str(r.get("url", "")).startswith("https://")]
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
                removed = self.store.deactivate_unseen(name, started - 1)
                report[name] = {"ok": True, "seen": count, "deactivated": removed, "seconds": round(time.time() - started, 1)}
            except Exception as exc:  # 한 소스가 실패해도 다른 소스는 계속
                log.exception("crawl %s failed", name)
                report[name] = {"ok": False, "error": str(exc)[:300]}
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
    """추천 직전에 후보 엔드포인트가 응답하는지 확인한다 (5xx·타임아웃이면 실패)."""

    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False, max_age: float = 3600):
        self.store = store
        self.http = http or httpx.Client(timeout=8.0, follow_redirects=False, headers={"user-agent": "agent-gateway/0.1"})
        self.allow_private = allow_private
        self.max_age = max_age

    def probe(self, resource: dict, force: bool = False) -> bool | None:
        if not force and resource.get("probed_at") and time.time() - resource["probed_at"] < self.max_age:
            return None  # 최근에 확인함
        url = resource["url"]
        try:
            if not self.allow_private:
                check_public_url(url)
            started = time.monotonic()
            resp = self.http.get(url)
            ok = resp.status_code < 500
            latency = int((time.monotonic() - started) * 1000)
        except (DiscoveryError, httpx.HTTPError, ValueError):
            ok, latency = False, None
        self.store.record_probe(resource["id"], ok, latency)
        resource.update(probed_at=time.time())
        resource["probe_ok" if ok else "probe_fail"] = resource.get("probe_ok" if ok else "probe_fail", 0) + 1
        resource["probe_latency_ms"] = latency
        return ok
