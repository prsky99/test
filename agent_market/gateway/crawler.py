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

from ..broker.categories import CATEGORIES
from .classify import classify
from .store import Store

log = logging.getLogger("agent_market.gateway.crawler")

X402_DISCOVERY = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
A2A_REGISTRY = "https://a2aregistry.org/api/agents"
A2A_REGISTRY_FALLBACK = "https://api.a2a-registry.org/public/agents"

# (네트워크, USDC 컨트랙트) — 가격을 USDC로 비교할 수 있는 경우만 price_usdc를 채운다.
USDC_ASSETS = {
    "eip155:8453": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "eip155:84532": "0x036cbd53842c5426634e7929541ec2318f3dcf7e",
    "eip155:42161": "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
    "eip155:137": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
    "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v",
}
# Test networks: their USDC has no value, so a price there is never shown as a real price
# (427 active x402 listings took payment only on Base Sepolia, 2026-11-10).
TEST_NETWORKS = frozenset({"eip155:84532"})


def test_networks_only(networks) -> bool:
    """True when every payment network is a test network (stored as ',a,b,' or a list)."""
    names = [n for n in (networks.split(',') if isinstance(networks, str) else networks or []) if n]
    return bool(names) and all(LEGACY_NETWORKS.get(n, n) in TEST_NETWORKS for n in names)
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
        if net in TEST_NETWORKS:
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
        "price_usdc": (best[0] or None) if best else None,  # a 402 asking for 0: amount unknown, not free
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


def parse_a2a_item(item: dict) -> dict | None:
    url = item.get("url") or item.get("wellKnownURI") or item.get("manifestUrl")
    if not isinstance(url, str) or not url.startswith("https://") or any(c in url for c in "{}<>"):
        return None
    name = str(item.get("name") or item.get("displayName") or item.get("packageName") or "")[:200]
    description = str(item.get("description") or "")[:2000]
    # The registry's own labels (developer-tools, demo-test, ...) are not our categories:
    # stored as-is they hid listings from category pages until the card check reclassified them.
    cat = item.get("category") if item.get("category") in CATEGORIES else classify(f"{name} {description}")

    skills = item.get("skills")[:20] if isinstance(item.get("skills"), list) else []
    caps = item.get("capabilities") if isinstance(item.get("capabilities"), (dict, list)) else None
    pricing = item.get("pricing")

    ts_val = _ts(item.get("updated_at")) or _ts(item.get("created_at"))
    if ts_val is None and item.get("createdAt"):
        try:
            ts_val = float(item["createdAt"])
        except (ValueError, TypeError):
            pass

    return {
        "key": f"a2a:{url}",
        "source": "a2a-registry",
        "kind": "a2a",
        "url": url,
        "name": name,
        "description": description,
        "category": cat,
        "networks": [],
        "price_usdc": 0 if not pricing else None,
        "pay_to": None,
        "method": "POST",
        "details": {
            "agent_card": item.get("wellKnownURI") or item.get("manifestUrl"),
            "skills": skills,
            "capabilities": caps,
            "version": item.get("version") or item.get("protocolVersion"),
            "author": item.get("author") or item.get("provider"),
            "homepage": item.get("homepage"),
            "repository": item.get("repository"),
        },
        "calls_30d": None,
        "payers_30d": None,
        "last_called": ts_val,
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
    - Discovery membership never changes local activity or health ownership.
    - Bounded offset passes rotate through the catalog instead of rereading only its prefix.
    """

    RESUME_WINDOW = 6 * 3600  # 이보다 오래된 진행 위치는 버리고 새로 시작

    def __init__(self, store: Store, http: httpx.Client | None = None, page_delay: float = 1.0, max_pages: int = 5000,
                 full_interval: float = 86400, should_stop=None,
                 incremental_x402_max_pages: int = 10, incremental_mcp_max_pages: int = 25,
                 incremental_a2a_max_pages: int = 5,
                 sources: tuple[str, ...] = ("x402-bazaar", "mcp-registry", "a2a-registry")):
        self.store = store
        self._fixed_http = http  # 없으면 바퀴마다 새 연결을 만든다 (오래된 연결이 망가지는 것 방지)
        self.http = http
        self.page_delay = page_delay
        self.max_pages = max_pages
        self.full_interval = full_interval
        self.incremental_x402_max_pages = incremental_x402_max_pages
        self.incremental_mcp_max_pages = incremental_mcp_max_pages
        self.incremental_a2a_max_pages = incremental_a2a_max_pages
        self.sources = sources
        self.retry_delay = 2.0
        self.should_stop = should_stop or (lambda: False)
        self._lock = threading.Lock()

    def crawl_all(self, force_full: bool = False) -> dict:
        """모든 소스를 한 바퀴 수집. 이미 수집 중이면 {"busy": True}."""
        if not self._lock.acquire(blocking=False):
            return {"busy": True}
        try:
            if self._fixed_http is None:
                self.http = httpx.Client(
                    timeout=30.0,
                    headers={"user-agent": "A2A-Discovery-Crawler/1.0 (+https://agentconcierge.biz/; respectful indexing bot; contact: contact@agentconcierge.biz)"}
                )
            report = {}
            for name in self.sources:
                started = time.time()
                try:
                    report[name] = self._pass(name, force_full=force_full)
                except httpx.HTTPError as exc:  # 외부 레지스트리 일시 장애·시간 초과: 진행 위치는 유지하고 다음 주기에 재개
                    log.warning("crawl %s interrupted by upstream HTTP error (%s): %s", name, type(exc).__name__, exc)
                    report[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "seconds": round(time.time() - started, 1)}
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
            except httpx.TransportError as exc:  # 시간 초과·연결 끊김: 한 페이지 때문에 바퀴 전체를 버리지 않도록 재시도
                if attempt == 3:
                    raise
                delay = self.retry_delay * (2 ** attempt)
                log.warning("Transport error %s from %s; retrying in %.1fs (attempt %d/4)", type(exc).__name__, url, delay, attempt + 1)
                time.sleep(delay)
                continue

            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                delay = max(4.0 * (2 ** attempt), 5.0)
                if retry_after:
                    try:
                        delay = max(delay, min(120.0, float(retry_after)))
                    except ValueError:
                        pass
                log.warning("Rate limit 429 from %s; backing off for %.1fs (attempt %d/4)", url, delay, attempt + 1)
                if attempt == 3:
                    resp.raise_for_status()
                time.sleep(delay)
                continue

            if resp.status_code >= 500:
                delay = self.retry_delay * (2 ** attempt)
                log.warning("Server error %d from %s; retrying in %.1fs (attempt %d/4)", resp.status_code, url, delay, attempt + 1)
                if attempt == 3:
                    resp.raise_for_status()
                time.sleep(delay)
                continue

            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    def _mode(self, name: str, force_full: bool = False) -> str:
        if force_full:
            return "full"
        last_full = self.store.get_meta(f"crawl_last_full:{name}")
        return "incremental" if last_full and time.time() - last_full < self.full_interval else "full"

    def _pass(self, name: str, force_full: bool = False) -> dict:
        key = f"crawl_pass:{name}"
        mode = self._mode(name, force_full=force_full)
        state = self.store.get_meta(key)
        resumed = bool(state and state.get("mode") == mode and time.time() - state["started"] < self.RESUME_WINDOW)
        if not resumed:
            state = {"mode": mode, "started": time.time(), "position": None, "pages": 0,
                     "seen": 0, "new": 0, "changed": 0, "unchanged": 0}
            if mode == "incremental":  # 지난번 수집 시작 5분 전부터 바뀐 것 (겹쳐서 놓치지 않게)
                since = (self.store.get_meta(f"crawl_last_start:{name}") or time.time() - self.full_interval) - 300
                state["since"] = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if name in ('x402-bazaar', 'a2a-registry'):
                    state['position'] = self.store.get_meta(f'crawl_scan_position:{name}')
        fetch = self._x402_page if name == "x402-bazaar" else (self._mcp_page if name == "mcp-registry" else self._a2a_page)

        consecutive_unchanged = 0
        batch_pages = 0
        completed = False
        while state["pages"] < self.max_pages:
            previous_position = state['position']
            records, next_position = fetch(state)
            if next_position is not None and next_position == previous_position:
                raise ValueError('registry_cursor_did_not_advance')
            counts = self.store.upsert_page(records)
            state["pages"] += 1
            batch_pages += 1
            state["seen"] += len(records)
            for k, v in counts.items():
                state[k] += v
            state["position"] = next_position
            self.store.set_meta(key, state)  # 진행 위치 저장 (재시작 시 이어서)
            if next_position is None:
                completed = True
                break
            if self.should_stop():
                return {"ok": True, "interrupted": True, **self._summary(state, resumed)}

            # Safe incremental pass bounds to prevent upstream rate-limiting/bans
            if mode == "incremental" and name == "x402-bazaar":
                if counts.get("new", 0) == 0 and counts.get("changed", 0) == 0:
                    consecutive_unchanged += 1
                    if consecutive_unchanged >= 2:
                        break
                else:
                    consecutive_unchanged = 0
                if batch_pages >= self.incremental_x402_max_pages:
                    break
            elif mode == "incremental" and name == "mcp-registry":
                if batch_pages >= self.incremental_mcp_max_pages:
                    break
            elif mode == "incremental" and name == "a2a-registry":
                if counts.get("new", 0) == 0 and counts.get("changed", 0) == 0:
                    consecutive_unchanged += 1
                    if consecutive_unchanged >= 2:
                        break
                else:
                    consecutive_unchanged = 0
                since_ts = _ts(state.get("since")) if state.get("since") else None
                if since_ts and records and all(r.get("last_called") is not None and r["last_called"] < since_ts for r in records):
                    break
                if batch_pages >= self.incremental_a2a_max_pages:
                    break

            time.sleep(self.page_delay)

        if mode == 'full' and not completed:
            log.warning('Incomplete full discovery scan for %s; membership unchanged', name)
            return {'ok': False, 'incomplete': True, 'deactivated': 0,
                    'registry_missing': 0, **self._summary(state, resumed)}
        registry_missing = 0
        if mode == "full":
            registry_missing = self.store.mark_registry_unseen(name, state['started'])
            if registry_missing >= 1000:
                log.warning('Discovery source %s omitted %d entries; local management retained', name, registry_missing)
            self.store.set_meta(f"crawl_prev_full_start:{name}", state["started"])
            self.store.set_meta(f"crawl_last_full:{name}", time.time())
            self.store.set_meta(f'crawl_scan_position:{name}', None)
        elif name in ('x402-bazaar', 'a2a-registry'):
            self.store.set_meta(f'crawl_scan_position:{name}', state['position'])
        elif not completed:
            # Keep the original updated_since and cursor until this change set is drained.
            return {'ok': True, 'pending': True, 'deactivated': 0, 'registry_missing': 0,
                    **self._summary(state, resumed)}
        self.store.set_meta(f"crawl_last_start:{name}", state["started"])
        self.store.set_meta(key, None)
        return {"ok": True, "deactivated": 0, 'registry_missing': registry_missing,
                **self._summary(state, resumed)}

    @staticmethod
    def _summary(state: dict, resumed: bool) -> dict:
        return {"mode": state["mode"], "resumed": resumed, "pages": state["pages"], "seen": state["seen"], "new": state["new"],
                "changed": state["changed"], "unchanged": state["unchanged"], "seconds": round(time.time() - state["started"], 1)}

    def _x402_page(self, state: dict) -> tuple[list[dict], int | None]:
        offset, limit = state["position"] or 0, 100
        for attempt in range(2):
            data = self._get(X402_DISCOVERY, {"limit": limit, "offset": offset})
            if not isinstance(data, dict) or not isinstance(data.get('items'), list):
                raise ValueError('invalid_registry_items')
            items = data['items']
            pagination = data.get('pagination')
            if not isinstance(pagination, dict) or type(pagination.get('total')) is not int or pagination['total'] < 0:
                raise ValueError('invalid_registry_pagination')
            total = pagination['total']
            if not ((not items and offset < total) or (items and total == 0)):
                break
            # The registry briefly returned an empty page inside its total (2026-11-01 twice); ask once more.
            if attempt == 0 and not self.should_stop():
                time.sleep(2)
        else:
            raise ValueError('incomplete_registry_page')
        records = [p for p in (parse_x402_item(i) for i in items) if p]
        offset += limit
        return records, (offset if items and offset < total else None)

    def _mcp_page(self, state: dict) -> tuple[list[dict], str | None]:
        params = {"limit": 100, "version": "latest"}  # 서버마다 최신 버전만 (전체 버전 목록은 5배 이상 길다)
        if state["position"]:
            params["cursor"] = state["position"]
        if state.get("since"):
            params["updated_since"] = state["since"]
        data = self._get(MCP_REGISTRY, params)
        if not isinstance(data, dict) or not isinstance(data.get('servers'), list):
            raise ValueError('invalid_registry_items')
        cursor = (data.get('metadata') or {}).get('nextCursor') or None
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError('invalid_registry_cursor')
        records = [p for p in (parse_mcp_item(i) for i in data['servers']) if p]
        return records, cursor

    def _a2a_page(self, state: dict) -> tuple[list[dict], int | None]:
        offset, limit = state["position"] or 0, 100
        params = {"limit": limit, "offset": offset}
        try:
            data = self._get(A2A_REGISTRY, params)
        except Exception as exc:
            try:
                data = self._get(A2A_REGISTRY_FALLBACK, params)
            except Exception:
                raise exc
        if not isinstance(data, dict) or not isinstance(data.get('agents'), list):
            raise ValueError('invalid_registry_items')
        items = data['agents']
        total = data.get('total')
        if type(total) is not int or total < 0:
            raise ValueError('invalid_registry_pagination')
        if (not items and offset < total) or (items and total == 0):
            raise ValueError('incomplete_registry_page')
        records = [p for p in (parse_a2a_item(i) for i in items) if p]
        offset += limit
        return records, (offset if items and offset < total else None)


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
