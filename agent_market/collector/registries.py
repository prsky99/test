"""AI 에이전트(A2A) 수집 출처.

1. ERC-8004 Identity Registry (온체인 에이전트 신원 등록부, 같은 주소로 여러 체인에 배포)
   - 에이전트 = ERC-721 토큰, tokenURI(agentURI) = 등록 파일(JSON: name, description, services[{name, endpoint}], active …)
   - 키 없는 공개 RPC로 tokenURI를 100개씩 묶어(배치 JSON-RPC) 읽는다. 새 ID는 이어서, 기존 ID는 한 바퀴씩 다시 읽어
     agentURI가 바뀐 것만 등록 파일을 다시 받는다(URIUpdated 반영).
   - 등록 파일은 data: URI(바로 해석), https://, ipfs://(공개 게이트웨이)에 있다. https는 호스트별로 나눠 천천히 받는다.
   - services 중 A2A → A2A 에이전트, MCP → MCP 서버(이미 수집한 주소면 건너뜀)로 저장. 같은 card를 여러 토큰이
     등록해도(스팸·중복 등록이 많다) card 주소 하나로 묶는다. active: false면 제외.
2. well-known 탐색: 이미 아는 호스트(MCP·x402·웹사이트)의 /.well-known/agent-card.json을 30일에 한 번 확인.
"""

import base64
import hashlib
import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

import httpx

from ..broker.discovery import DiscoveryError, check_public_url
from ..gateway.classify import classify
from ..gateway.store import Store
from .a2a import CARD_PATHS, normalize_card

log = logging.getLogger("agent_market.collector.registries")

USER_AGENT = "agent-collector/0.1 (+agent discovery; no payment is made)"
IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"  # 모든 메인넷에서 같은 주소 (CREATE2)
TOKEN_URI = "0xc87b56dd"  # tokenURI(uint256)
DEFAULT_CHAINS = {  # 이름: (chain id, 키 없는 공개 RPC)
    "base": (8453, "https://base-rpc.publicnode.com"),
    "ethereum": (1, "https://ethereum-rpc.publicnode.com"),
    "bsc": (56, "https://bsc-rpc.publicnode.com"),
}
IPFS_GATEWAY = "https://ipfs.io/ipfs/"
MAX_REGISTRATION = 256 * 1024
BATCH = 100


def _decode_string(hexdata: str) -> str | None:
    try:
        b = bytes.fromhex(hexdata[2:])
        off = int.from_bytes(b[:32], "big")
        ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf-8", errors="replace")
    except (ValueError, IndexError):
        return None


def parse_data_uri(uri: str):
    head, _, payload = uri.partition(",")
    raw = base64.b64decode(payload + "=" * (-len(payload) % 4)) if ";base64" in head else unquote(payload).encode()
    return json.loads(raw.decode("utf-8", errors="replace"))


def services_of(doc) -> list[dict]:
    """등록 파일의 services(구버전 endpoints)에서 A2A·MCP 엔드포인트만."""
    if not isinstance(doc, dict):
        return []
    raw = doc.get("services") or doc.get("endpoints") or []
    if isinstance(raw, dict):  # {"A2A": "https://…"} 또는 {"A2A": {"endpoint": …}} 형식도 있다
        raw = [v if isinstance(v, dict) and "name" in v else {"name": k, **(v if isinstance(v, dict) else {"endpoint": v})}
               for k, v in raw.items()]
    out = []
    for s in raw[:20] if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or s.get("type") or "").strip().lower()
        ep = str(s.get("endpoint") or s.get("url") or "").strip()
        if not ep.startswith("https://") or any(c in ep for c in " {}<>"):
            continue
        if name in ("a2a", "agent2agent", "a2a-agent", "agentcard", "agent-card"):
            out.append({"kind": "a2a", "endpoint": ep[:500], "version": str(s.get("version") or "")[:20] or None})
        elif name == "mcp":
            out.append({"kind": "mcp", "endpoint": ep[:500], "version": str(s.get("version") or "")[:20] or None})
    return out


def _is_revert(error) -> bool:
    msg = str(error.get("message") if isinstance(error, dict) else error).lower()
    return "revert" in msg or "nonexistent" in msg or "invalid token" in msg or (isinstance(error, dict) and error.get("code") == 3)


class Erc8004Crawler:
    def __init__(self, store: Store, chains: dict | None = None, http: httpx.Client | None = None,
                 allow_private: bool = False, batch_delay: float = 1.0, workers: int = 8, per_host: int = 5,
                 per_host_delay: float = 1.0, rescan_interval: float = 86400):
        self.store = store
        self.chains = chains or DEFAULT_CHAINS
        self._fixed_http = http
        self.allow_private = allow_private
        self.batch_delay = batch_delay
        self.workers = workers
        self.per_host = per_host
        self.per_host_delay = per_host_delay
        self.rescan_interval = rescan_interval

    def _http(self) -> httpx.Client:
        return self._fixed_http or httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=False,
                                                headers={"user-agent": USER_AGENT})

    # ---------------- 온체인 목록 ----------------
    def token_uris(self, http: httpx.Client, rpc: str, ids: list[int]) -> dict[int, str | None]:
        """{id: uri}. 없는 토큰(되돌림)은 결과에서 빠지고, URI가 비어 있으면 ''."""
        batch = [{"jsonrpc": "2.0", "id": i, "method": "eth_call",
                  "params": [{"to": IDENTITY_REGISTRY, "data": TOKEN_URI + hex(i)[2:].rjust(64, "0")}, "latest"]} for i in ids]
        for attempt in range(5):
            try:
                resp = http.post(rpc, json=batch)
                data = resp.json()
                # 없는 토큰은 'execution reverted'. 그 밖의 오류(요청 한도 등)가 섞이면 배치 전체를 다시 요청한다
                if isinstance(data, list) and not any(
                        isinstance(x, dict) and x.get("error") and not _is_revert(x["error"]) for x in data):
                    break
            except (httpx.HTTPError, ValueError):
                data = None
            time.sleep(max(self.batch_delay, 0.01) * 2 ** (attempt + 1))
        else:
            raise RuntimeError(f"RPC batch failed (rate limited or unavailable): {rpc}")
        out = {}
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("result"), str) and len(item["result"]) > 2:
                uri = _decode_string(item["result"])
                if uri is not None:
                    out[int(item["id"])] = uri.strip()
        return out

    def scan(self, chain: str, max_batches: int = 20) -> dict:
        """새 ID를 이어서 읽고, 남는 배치로 기존 ID를 한 바퀴씩 다시 읽는다."""
        chain_id, rpc = self.chains[chain]
        http = self._http()
        stats = defaultdict(int)
        try:
            next_id = self.store.get_meta(f"erc8004_next:{chain}")
            if next_id is None:  # 처음 수집: 다 읽은 직후 곧바로 재확인하지 않도록 재확인 주기를 지금부터 센다
                next_id = 1
                self.store.set_meta(f"erc8004_rescan_done:{chain}", time.time())
            misses = 0
            for _ in range(max_batches):  # 1) 새로 등록된 에이전트
                ids = list(range(next_id, next_id + BATCH))
                found = self.token_uris(http, rpc, ids)
                self._store_uris(chain, chain_id, found, stats)
                if found:
                    next_id = max(found) + 1
                    misses = 0
                else:
                    misses += 1
                    if misses >= 2:  # 두 배치 연속 비면 끝(중간 삭제·소각된 ID는 건너뜀)
                        break
                    next_id += BATCH
                self.store.set_meta(f"erc8004_next:{chain}", next_id - (BATCH if misses else 0))
                stats["batches"] += 1
                time.sleep(self.batch_delay)
            if misses >= 2 or stats["batches"] < max_batches:  # 2) 남는 배치로 기존 ID 다시 읽기 (agentURI 변경 반영)
                last_full = self.store.get_meta(f"erc8004_rescan_done:{chain}") or 0
                cursor = self.store.get_meta(f"erc8004_rescan:{chain}") or 1
                end = self.store.get_meta(f"erc8004_next:{chain}") or 1
                if time.time() - last_full >= self.rescan_interval:
                    for _ in range(max_batches - stats["batches"]):
                        if cursor >= end:
                            cursor = 1
                            self.store.set_meta(f"erc8004_rescan_done:{chain}", time.time())
                            break
                        found = self.token_uris(http, rpc, list(range(cursor, min(cursor + BATCH, end))))
                        self._store_uris(chain, chain_id, found, stats, rescan=True)
                        cursor += BATCH
                        stats["rescan_batches"] += 1
                        time.sleep(self.batch_delay)
                    self.store.set_meta(f"erc8004_rescan:{chain}", cursor)
        finally:
            if http is not self._fixed_http:
                http.close()
        return dict(stats)

    def _store_uris(self, chain: str, chain_id: int, found: dict[int, str], stats: dict, rescan: bool = False) -> None:
        """agentURI 저장. 바뀐 것만 pending으로 → 등록 파일을 (다시) 받는다. data: URI는 바로 해석."""
        now = time.time()
        with self.store.tx() as db:
            for agent_id, uri in found.items():
                digest = hashlib.sha1(uri.encode()).hexdigest()
                row = db.execute("SELECT uri_hash FROM erc8004_tokens WHERE chain=? AND agent_id=?", (chain, agent_id)).fetchone()
                if row and row["uri_hash"] == digest:
                    stats["unchanged"] += 1
                    continue
                stats["changed" if row else "new"] += 1
                host = None
                if uri.startswith("https://"):
                    host = urlparse(uri).hostname
                elif uri.startswith("ipfs://"):
                    host = "ipfs"
                status = "empty" if not uri else "pending"
                # services(지난번 등록 엔드포인트)는 남겨 둔다: 빠진 엔드포인트를 비활성화하는 데 쓴다
                db.execute("""INSERT INTO erc8004_tokens (chain, agent_id, uri_hash, uri, host, status, services,
                              checked_at, next_at, error) VALUES (?,?,?,?,?,?,NULL,?,?,NULL)
                              ON CONFLICT(chain, agent_id) DO UPDATE SET uri_hash=excluded.uri_hash, uri=excluded.uri,
                              host=excluded.host, status=excluded.status, checked_at=excluded.checked_at,
                              next_at=excluded.next_at, error=NULL""",
                           (chain, agent_id, digest, uri[:2000] if not uri.startswith("data:") else None, host, status, now, now))
        for agent_id, uri in found.items():  # data: URI는 네트워크 없이 바로
            if uri.startswith("data:"):
                try:
                    doc = parse_data_uri(uri)
                except (ValueError, UnicodeDecodeError, base64.binascii.Error):
                    self._mark(chain, agent_id, "error", None, "invalid data URI")
                    continue
                self._apply_safe(chain, chain_id, agent_id, doc, stats)
            elif uri and not (uri.startswith("https://") or uri.startswith("ipfs://")):
                self._mark(chain, agent_id, "no_service", None, "unsupported URI scheme")

    def _mark(self, chain: str, agent_id: int, status: str, services: list | None, error: str | None,
              retry_after: float | None = None) -> None:
        with self.store.tx() as db:
            # 다시 받을 필요가 없으면 URI 원문은 지운다 (수십만 건이라 디스크 절약, 변경 감지는 uri_hash로)
            db.execute("""UPDATE erc8004_tokens SET status=?, services=?, error=?, checked_at=?, next_at=?,
                          uri=CASE WHEN ? IN ('resolved','no_service') THEN NULL ELSE uri END WHERE chain=? AND agent_id=?""",
                       (status, json.dumps(services) if services else None, error, time.time(),
                        time.time() + retry_after if retry_after else None, status, chain, agent_id))

    # ---------------- 등록 파일 → 에이전트 ----------------
    def _apply_safe(self, chain: str, chain_id: int, agent_id: int, doc, stats: dict) -> None:
        try:
            self._apply(chain, chain_id, agent_id, doc, stats)
        except Exception as exc:  # 비표준 등록 파일 하나 때문에 배치가 멈추지 않게
            log.warning("erc8004 %s#%s: bad registration: %r", chain, agent_id, exc)
            self._mark(chain, agent_id, "no_service", None, f"invalid registration: {type(exc).__name__}")
            stats["invalid"] += 1

    def _key(self, service: dict) -> str:
        return f"{'erc8004-mcp' if service['kind'] == 'mcp' else 'a2a'}:{service['endpoint']}"

    def _withdraw(self, chain: str, agent_id: int, keep: list[dict], stats: dict) -> None:
        """이 토큰이 전에 등록했던 엔드포인트 중 지금은 빠진 것: 등록 목록에서 지우고, 남은 등록이 없으면 비활성화."""
        row = self.store.query("SELECT services FROM erc8004_tokens WHERE chain=? AND agent_id=?", (chain, agent_id))
        old = json.loads(row[0]["services"]) if row and row[0]["services"] else []
        keep_keys = {self._key(s) for s in keep}
        for s in old:
            key = self._key(s)
            if key in keep_keys:
                continue
            res = self.store.query("SELECT id, details FROM resources WHERE key=?", (key,))
            if not res:
                continue
            details = json.loads(res[0]["details"])
            regs = [r for r in details.get("erc8004") or [] if not (r["chain"] == chain and r["agent_id"] == agent_id)]
            with self.store.tx() as db:
                if regs:
                    db.execute("UPDATE resources SET details=? WHERE id=?", (json.dumps({**details, "erc8004": regs}, sort_keys=True), res[0]["id"]))
                else:
                    db.execute("UPDATE resources SET active=0 WHERE id=?", (res[0]["id"],))
                    stats["withdrawn"] += 1

    def _apply(self, chain: str, chain_id: int, agent_id: int, doc, stats: dict) -> None:
        if not isinstance(doc, dict):
            self._mark(chain, agent_id, "error", None, "registration is not a JSON object")
            return
        services = services_of(doc) if doc.get("active") is not False else []
        self._withdraw(chain, agent_id, services, stats)
        if not services:
            self._mark(chain, agent_id, "no_service", None, "inactive" if doc.get("active") is False else None)
            stats["no_service"] += 1
            return
        name = str(doc.get("name") or f"agent #{agent_id}")[:200]
        description = str(doc.get("description") or "")[:2000]
        reg = {"chain": chain, "agent_id": agent_id, "registry": f"eip155:{chain_id}:{IDENTITY_REGISTRY}",
               "x402": bool(doc.get("x402Support"))}
        for s in services:
            url = s["endpoint"]
            if s["kind"] == "mcp":
                existing = self.store.query("SELECT key FROM resources WHERE url=? LIMIT 1", (url,))
                if existing and not existing[0]["key"].startswith("erc8004-mcp:"):
                    stats["mcp_known"] += 1
                    continue
                key = f"erc8004-mcp:{url}"
            else:
                key = f"a2a:{url}"
            row = self.store.query("SELECT details FROM resources WHERE key=?", (key,))
            regs = json.loads(row[0]["details"]).get("erc8004", []) if row else []
            if not any(r["chain"] == chain and r["agent_id"] == agent_id for r in regs):
                regs = (regs + [reg])[:5]  # 같은 엔드포인트를 여러 토큰이 등록한 경우 앞의 5개만 기록
            elif row:
                stats["already"] += 1
                continue
            self.store.upsert_resource({
                "key": key, "source": "erc8004", "kind": s["kind"], "url": url, "name": name, "description": description,
                "category": classify(f"{name} {description}"), "networks": [], "price_usdc": 0 if not reg["x402"] else None,
                "details": {"erc8004": sorted(regs, key=lambda r: (r["chain"], r["agent_id"])), "protocol_version": s["version"],
                            "image": str(doc.get("image") or "")[:300] or None,
                            **({"remotes": [{"type": "streamable-http", "url": url}]} if s["kind"] == "mcp" else {})},
            })
            stats[f"{s['kind']}_upserted"] += 1
        self._mark(chain, agent_id, "resolved", services, None)

    def _fetch_registration(self, http: httpx.Client, uri: str):
        url = IPFS_GATEWAY + uri[len("ipfs://"):].lstrip("/").removeprefix("ipfs/") if uri.startswith("ipfs://") else uri
        if not self.allow_private and not uri.startswith("ipfs://"):
            check_public_url(url)
        resp = http.get(url, headers={"accept": "application/json", "user-agent": USER_AGENT})
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        if len(resp.content) > MAX_REGISTRATION:
            raise ValueError("registration file too large")
        return resp.json()

    def resolve_pending(self, limit: int = 200) -> dict:
        """https·ipfs 등록 파일을 받는다. 호스트당 per_host개씩, 호스트 사이는 병렬."""
        rows = self.store.query(
            """SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY host ORDER BY next_at) AS rn FROM erc8004_tokens
                 WHERE status IN ('pending','error') AND uri IS NOT NULL AND (next_at IS NULL OR next_at <= ?))
               WHERE rn <= ? ORDER BY next_at LIMIT ?""", (time.time(), self.per_host, limit))
        if not rows:
            return {"resolved": 0}
        by_host = defaultdict(list)
        for r in rows:
            by_host[r["host"]].append(dict(r))
        http = self._http()
        stats, results = defaultdict(int), []

        def work(items):
            for i, r in enumerate(items):
                if i:
                    time.sleep(self.per_host_delay)
                try:
                    results.append((r, self._fetch_registration(http, r["uri"]), None))
                except (httpx.HTTPError, DiscoveryError, ValueError) as exc:
                    results.append((r, None, f"{type(exc).__name__}: {exc}"[:200]))

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(work, by_host.values()))
        finally:
            if http is not self._fixed_http:
                http.close()
        for r, doc, err in results:
            if err:
                tries = (r.get("error") or "").count("|") + 1
                if tries >= 3:
                    self._mark(r["chain"], r["agent_id"], "no_service", None, f"unreachable: {err}")
                else:
                    self._mark(r["chain"], r["agent_id"], "error", None, (r.get("error") or "") + "|" + err,
                               retry_after=3600 * 6 * tries)
                stats["fetch_failed"] += 1
                continue
            chain_id = self.chains[r["chain"]][0]
            self._apply_safe(r["chain"], chain_id, r["agent_id"], doc, stats)
            stats["fetched"] += 1
        return {"resolved": len(results), **stats}


class WellKnownDiscoverer:
    """이미 아는 호스트에서 A2A agent card를 찾는다 (호스트당 30일에 한 번, 요청 1~2개)."""

    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False,
                 max_age: float = 30 * 86400, workers: int = 8):
        self.store = store
        self._fixed_http = http
        self.allow_private = allow_private
        self.max_age = max_age
        self.workers = workers

    def due_hosts(self, limit: int) -> list[str]:
        rows = self.store.query(
            """SELECT h.host FROM (SELECT DISTINCT host FROM resources WHERE active=1 AND host IS NOT NULL) h
               LEFT JOIN wellknown_hosts w ON w.host = h.host
               WHERE w.host IS NULL OR w.checked_at < ? ORDER BY w.checked_at IS NOT NULL, w.checked_at LIMIT ?""",
            (time.time() - self.max_age, limit))
        return [r["host"] for r in rows]

    def probe(self, http: httpx.Client, host: str) -> tuple[str, dict] | None:
        for path in CARD_PATHS:
            url = f"https://{host}{path}"
            try:
                if not self.allow_private:
                    check_public_url(url)
                resp = http.get(url, headers={"accept": "application/json", "user-agent": USER_AGENT})
            except (httpx.HTTPError, DiscoveryError):
                return None
            if resp.status_code == 200 and len(resp.content) <= 512 * 1024:
                try:
                    card = normalize_card(resp.json(), url)
                except ValueError:
                    card = None
                if card:
                    return url, card
        return None

    def _probe_safe(self, http: httpx.Client, host: str):
        try:
            return self.probe(http, host)
        except Exception as exc:  # 비표준 응답 하나가 묶음 전체를 멈추지 않게
            log.warning("well-known probe %s failed: %r", host, exc)
            return None

    def run_due(self, limit: int = 200) -> dict:
        hosts = self.due_hosts(limit)
        if not hosts:
            return {"checked": 0}
        http = self._fixed_http or httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=False)
        found = []
        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                results = list(pool.map(lambda h: (h, self._probe_safe(http, h)), hosts))
        finally:
            if http is not self._fixed_http:
                http.close()
        now = time.time()
        with self.store.tx() as db:
            db.executemany("INSERT OR REPLACE INTO wellknown_hosts VALUES (?,?,?)",
                           [(h, now, res[0] if res else None) for h, res in results])
        for host, res in results:
            if not res:
                continue
            url, card = res
            if self.store.query("SELECT 1 FROM resources WHERE key=? OR url=? LIMIT 1", (f"a2a:{url}", url)):
                continue
            self.store.upsert_resource({
                "key": f"a2a:{url}", "source": "well-known", "kind": "a2a", "url": url, "name": card["name"],
                "description": card["description"], "category": classify(f"{card['name']} {card['description']}"),
                "networks": [], "price_usdc": 0 if not card.get("payment") else None,
                "details": {"agent_card": url, "found_on": host},
            })
            found.append(url)
        return {"checked": len(hosts), "found": len(found)}
