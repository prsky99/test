"""E6 lifecycle signals (docs/VERIFIED_REGISTRY.md 4; growth experiments 2026-11-15).

Once a day the jobs step writes ``gateway-data/registry/lifecycle.json``, served from memory at
``/registry/verified/v0.1/x/biz.agentconcierge/lifecycle``. Three signals, each with its rule written in the file:

  * unresponsive: an official-registry server our health checks retired, or that has failed every check for more
    than 7 days. One failure, a 429 or a day of 5xx is not enough.
  * domain_expiring: a registrable domain behind a verified-registry server whose RDAP ``expiration`` event is
    within 30 days. Registrars may renew automatically, so only the date is stated, never "abandoned".
  * similar_name: an official-registry name one edit (or only look-alike characters) away from a verified-registry
    name, whose repository owner and registrable domain both differ. Servers of one owner or domain are left out.

Public line (design section 4): no security finding goes here, and nothing from RDAP but the expiration date (no
registrant data is read or kept). Sources: our catalog (one registered SELECT in id pages), the verified-registry
snapshot, and RDAP servers found through the IANA bootstrap, reserved per RDAP server on the shared provider budget
('lifecycle_rdap', 50 a day per RDAP server, not raised). Members' and pearls' domains are read first. A read date is
not read again until it is within 60 days (then every 7 days). Until a domain has been read it is counted under
``not_checked_yet``.
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from . import verified_registry as R

FILE = "lifecycle.json"
RDAP_CACHE = "rdap-expiry.json"
PATH = "/registry/verified/v0.1/x/biz.agentconcierge/lifecycle"
DAY = 86400
DEAD_AFTER_S = 7 * DAY
EXPIRY_WINDOW_S = 30 * DAY
NEAR_S = 60 * DAY
RECHECK_NEAR_S = 7 * DAY
KEEP_EXPIRY_S = 90 * DAY
BOOTSTRAP_S = DAY
BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BUDGET = "lifecycle_rdap"
MAX_READS = 300          # RDAP reads in one run; the per-server budget usually stops earlier
SPACING_S = 1.0
RULES = {
    "unresponsive": "Official MCP Registry server that our health checks retired or that failed every check for "
                    "more than 7 days. A single failure, a 429 or one day of 5xx is not counted.",
    "domain_expiring": "Registrable domain behind a verified-registry server whose RDAP expiration date is within "
                       "30 days. Registrars may renew automatically; only the date is stated.",
    "similar_name": "Official MCP Registry name one edit or only look-alike characters away from a verified-registry "
                    "name, with a different repository owner and a different registrable domain.",
}
NOTICE = ("Lifecycle signals from AgentValCon's keyless read-only checks and public RDAP data. Signals are not "
          "verdicts: read the publisher's own records before acting. Not affiliated with the MCP Registry.")
# Look-alike characters folded before comparing names (Latin digits and common Cyrillic/Greek homoglyphs).
_CONFUSABLE = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s", "а": "a", "е": "e",
                             "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
                             "і": "l", "ο": "o", "α": "a", "ρ": "p"})


def _json(value):
    return R._json(value)


def _name(row) -> str | None:
    name = (_json(row.get("details")) or {}).get("registry_name")
    return name if isinstance(name, str) and R.NAME.fullmatch(name) else None


def _hosts(row) -> list[str]:
    details = _json(row.get("details")) or {}
    urls = [r.get("url") for r in details.get("remotes") or [] if isinstance(r, dict)] + [row.get("url")]
    out = []
    for url in urls:
        host = (urlsplit(str(url or "")).hostname or "").lower()
        if host and host not in out:
            out.append(host)
    return out


def _owner(row) -> str | None:
    repo = (_json(row.get("details")) or {}).get("repository")
    url = repo.get("url") if isinstance(repo, dict) else repo
    if not isinstance(url, str):
        return None
    parts = [p for p in urlsplit(url).path.split("/") if p]
    host = (urlsplit(url).hostname or "").lower()
    return f"{host}/{parts[0].lower()}" if parts and host else None


# ---------------------------------------------------------------- unresponsive
def unresponsive(rows, now: float) -> list[dict]:
    out = {}
    for row in rows:
        name = _name(row)
        if not name:
            continue
        status = row.get("health_status")
        try:
            since = float(row.get("failing_since")) if row.get("failing_since") is not None else None
        except (TypeError, ValueError):
            since = None
        if status == "retired":
            kind = "retired"
        elif since is not None and now - since > DEAD_AFTER_S and status in ("down", "failing", "unknown"):
            kind = "failing_over_7_days"
        else:
            continue
        item = {"name": name, "signal": "unresponsive", "state": kind, "hosts": _hosts(row)[:3]}
        if since is not None:
            item["failing_since"] = R._iso(since)
        if name not in out or kind == "failing_over_7_days":
            out[name] = item
    return [out[n] for n in sorted(out)]


# ---------------------------------------------------------------- similar names
def _skeleton(name: str) -> str:
    folded = unicodedata.normalize("NFKC", name).lower().translate(_CONFUSABLE)
    return folded.replace("rn", "m").replace("vv", "w")


def _within_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:] if len(a) < len(b) else a[i + 1:] == b[i + 1:]


def _brands(domains) -> set[str]:
    return {d.split(".")[0] for d in domains if d and "." in d}


def similar_names(rows, listed: set[str]) -> list[dict]:
    """Pairs (candidate, verified name) one edit apart after folding look-alikes, different owner and domain."""
    from .provider_budget import domain
    meta = {}
    for row in rows:
        name = _name(row)
        if name and name not in meta:
            meta[name] = (_owner(row), {domain(h) for h in _hosts(row)})
    index: dict[str, set[str]] = {}
    for name in meta:
        sk = _skeleton(name)
        for key in {sk} | {sk[:i] + sk[i + 1:] for i in range(len(sk))}:
            index.setdefault(key, set()).add(name)
    found = {}
    for target in sorted(listed & set(meta)):
        sk = _skeleton(target)
        near = set()
        for key in {sk} | {sk[:i] + sk[i + 1:] for i in range(len(sk))}:
            near |= index.get(key, set())
        t_owner, t_domains = meta[target]
        for other in sorted(near - {target}):
            o_sk = _skeleton(other)
            if not _within_one(sk, o_sk):
                continue
            o_owner, o_domains = meta[other]
            if t_domains & o_domains or _brands(t_domains) & _brands(o_domains):
                continue          # same registrable domain, or one brand under country domains (dinilu.ch/.de)
            if t_owner and o_owner and t_owner == o_owner:
                continue          # same repository owner
            if other in listed and other < target:
                continue          # two verified names: report the pair once
            kind = "lookalike_characters" if sk == o_sk else "one_edit"
            found[(other, target)] = {"name": other, "signal": "similar_name", "resembles": target, "kind": kind,
                                      "name_is_verified": other in listed}
    return [found[k] for k in sorted(found)]


# ---------------------------------------------------------------- domain expiry (RDAP)
def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def registrable_domains(snapshot: dict | None) -> dict[str, list[str]]:
    """Registrable domain -> verified server names, leaving out hosting tenants (their platform's domain renews)."""
    from .provider_budget import SHARED_SUFFIXES, domain
    out: dict[str, list[str]] = {}
    for item in (snapshot or {}).get("servers") or []:
        if not item.get("_meta", {}).get(R.META_KEY, {}).get("listed"):
            continue
        for remote in item["server"].get("remotes") or []:
            host = (urlsplit(remote.get("url") or "").hostname or "").lower()
            name = domain(host)
            if not name or any(host == s or host.endswith("." + s) for s in SHARED_SUFFIXES):
                continue
            servers = out.setdefault(name, [])
            if item["server"]["name"] not in servers:
                servers.append(item["server"]["name"])
    return out


def priorities(snapshot: dict | None, rows, member_ids, now: float) -> dict[str, int]:
    """Reading order (PM 11-15 12:3x): 0 = a domain behind a necklace member or pearl, 1 = a server listed or changed in
    the last 30 days or a domain with an official server that is failing now, 2 = the rest."""
    from .provider_budget import domain
    members = set(member_ids)
    rank: dict[str, int] = {}
    failing = {domain(h) for r in rows if r.get("failing_since") is not None or r.get("health_status") in
               ("down", "failing") for h in _hosts(r)}
    for item in (snapshot or {}).get("servers") or []:
        meta = item.get("_meta", {}).get(R.META_KEY, {})
        if not meta.get("listed"):
            continue
        recent = now - R._ts(str(meta.get("updated_at"))) <= 30 * DAY
        for remote in item["server"].get("remotes") or []:
            d = domain(remote.get("url") or "")
            level = 0 if item.get("_id") in members else 1 if recent or d in failing else 2
            rank[d] = min(rank.get(d, 2), level)
    return rank


def due(cache: dict, domains, now: float, rank: dict[str, int] | None = None) -> list[str]:
    """Domains to read now, never-read ones first and in RANK order (members and pearls, then recent or failing, then
    the rest). A read expiry date is not read again until it is within 60 days (then every 7 days), which keeps the
    per-server share for unread domains; an answer without a date is read again after 90 days."""
    rank = rank or {}
    order = sorted(domains, key=lambda d: (rank.get(d, 2), d))
    never, near, old = [], [], []
    for d in order:
        entry = cache.get(d)
        if not entry:
            never.append(d)
            continue
        age = now - float(entry.get("checked_at") or 0)
        expires = R._ts(entry["expires"]) if entry.get("expires") else None
        if expires is not None:
            if expires - now <= NEAR_S and age >= RECHECK_NEAR_S:
                near.append(d)
        elif age >= KEEP_EXPIRY_S:
            old.append(d)
    return near + never + old


def _bootstrap(state: dict, now: float, http, reserve) -> dict:
    boot = state.get("bootstrap") or {}
    if boot.get("table") and now - float(boot.get("at") or 0) < BOOTSTRAP_S:
        return boot["table"]
    ok, _ = reserve(BOOTSTRAP_URL)
    if not ok:
        return boot.get("table") or {}
    raw = http.get(BOOTSTRAP_URL).json()
    table = {}
    for service in raw.get("services") or []:
        if isinstance(service, list) and len(service) >= 2:
            base = next((u for u in service[1] if isinstance(u, str) and u.startswith("https://")), None)
            for tld in service[0] if base else []:
                table[str(tld).lower()] = base
    if len(table) < 100:
        return boot.get("table") or {}
    state["bootstrap"] = {"at": now, "table": table}
    return table


def expiration(raw: dict) -> str | None:
    """The expiration event date only (no registrant, registrar or contact data is read)."""
    for event in raw.get("events") or []:
        if isinstance(event, dict) and event.get("eventAction") == "expiration" and isinstance(event.get("eventDate"), str):
            return event["eventDate"][:40]
    return None


def read_expiry(domains, state: dict, now: float, *, http, reserve, note, sleep=time.sleep,
                limit: int = MAX_READS, check_public_url=None, rank: dict[str, int] | None = None) -> dict:
    """Read due domains through the per-RDAP-server budget. Updates STATE['domains']; returns counts.
    CHECK_PUBLIC_URL (default broker.discovery's) refuses an RDAP address that does not resolve to a public host."""
    if check_public_url is None:
        from .broker.discovery import check_public_url
    from .provider_budget import PROVIDER_HTTP
    cache = state.setdefault("domains", {})
    counts = {"read": 0, "refused": 0, "failed": 0}
    try:
        table = _bootstrap(state, now, http, reserve)
    except Exception:  # noqa: BLE001 - no bootstrap today: nothing is read, earlier dates stay
        return {**counts, "bootstrap": "failed"}
    closed: set[str] = set()
    for d in due(cache, domains, now, rank):
        if counts["read"] >= limit:
            break
        labels = d.split(".")
        base = next((table[".".join(labels[i:])] for i in range(1, len(labels)) if ".".join(labels[i:]) in table), None)
        if not base:
            cache[d] = {"checked_at": now, "expires": None, "status": "no_rdap"}
            continue
        server = urlsplit(base).hostname or ""
        if server in closed:
            continue
        url = base.rstrip("/") + "/domain/" + d
        try:
            check_public_url(url)
        except Exception:  # noqa: BLE001
            closed.add(server)
            continue
        ok, _ = reserve(url)
        if not ok:
            closed.add(server)           # this RDAP server's share is used up for today
            counts["refused"] += 1
            continue
        if counts["read"]:
            sleep(SPACING_S)
        counts["read"] += 1
        try:
            response = http.get(url, headers={"accept": "application/rdap+json, application/json"})
        except Exception:  # noqa: BLE001
            counts["failed"] += 1
            continue
        if response.status_code == 429:
            note(url, 429, evidence=PROVIDER_HTTP)
            closed.add(server)
            counts["failed"] += 1
            continue
        if response.status_code == 404:
            cache[d] = {"checked_at": now, "expires": None, "status": "not_found", "server": server}
            continue
        if response.status_code != 200 or len(response.content) > 512 * 1024:
            counts["failed"] += 1
            continue
        try:
            expires = expiration(response.json())
        except ValueError:
            counts["failed"] += 1
            continue
        cache[d] = {"checked_at": now, "expires": expires, "status": "ok", "server": server}
    return counts


def expiring(domains: dict[str, list[str]], cache: dict, now: float) -> list[dict]:
    out = []
    for d, servers in sorted(domains.items()):
        entry = cache.get(d) or {}
        if not entry.get("expires"):
            continue
        at = R._ts(entry["expires"])
        if 0 < at - now <= EXPIRY_WINDOW_S or (at and at <= now):
            out.append({"domain": d, "signal": "domain_expiring", "expires": entry["expires"],
                        "checked_at": R._iso(float(entry["checked_at"])), "source": f"RDAP ({entry.get('server')})",
                        "servers": sorted(servers)[:20]})
    return out


# ---------------------------------------------------------------- the daily step
def build(rows, snapshot: dict | None, cache: dict, now: float) -> dict:
    listed = {i["server"]["name"] for i in (snapshot or {}).get("servers") or []
              if i.get("_meta", {}).get(R.META_KEY, {}).get("listed")}
    domains = registrable_domains(snapshot)
    read = [d for d in domains if (cache.get(d) or {}).get("status") in ("ok", "not_found", "no_rdap")]
    return {"profile": "agentvalcon-lifecycle-v1", "generated": R._iso(now), "notice": NOTICE, "rules": RULES,
            "coverage": {"official_servers": len({_name(r) for r in rows} - {None}), "verified_servers": len(listed),
                         "domains": len(domains), "domains_checked": len(read),
                         "domains_not_checked_yet": len(domains) - len(read)},
            "unresponsive": unresponsive(rows, now),
            "domain_expiring": expiring(domains, cache, now),
            "similar_name": similar_names(rows, listed)}


def run_job(store, now=None, folder: Path | None = None, *, http=None, reserve=None, note=None,
            sleep=time.sleep, check_public_url=None) -> dict:
    """jobs step, once a day outside the measurement windows. One registered SELECT in id pages, RDAP reads through
    the shared budget, then lifecycle.json replaced atomically."""
    from .necklaces.watch import in_quiet_window
    from . import provider_budget
    now = time.time() if now is None else now
    if in_quiet_window(now):
        return {"skipped": "measurement_window"}
    folder = Path(folder or R.data_dir())
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = _load(folder / "verified.json") or None
    rows = R.read_rows(store, R.SELECT_OFFICIAL)
    state = _load(folder / RDAP_CACHE)
    reserve = reserve or (lambda url: provider_budget.reserve(url, BUDGET))
    note = note or (lambda url, status, evidence=None: provider_budget.note(url, BUDGET, status, evidence=evidence))
    own = http is None
    if own:
        import httpx
        http = httpx.Client(timeout=10.0, follow_redirects=False,
                            headers={"user-agent": "AgentValCon-lifecycle/1 (+https://agentconcierge.biz/registry)"})
    try:
        from .member_fingerprints import member_ids
        rank = priorities(snapshot, rows, member_ids(), now)
        counts = read_expiry(registrable_domains(snapshot), state, now, http=http, reserve=reserve, note=note,
                             sleep=sleep, check_public_url=check_public_url, rank=rank)
    finally:
        if own:
            http.close()
    R.replace_atomic(folder / RDAP_CACHE, json.dumps(state, separators=(",", ":")))
    data = build(rows, snapshot, state.get("domains") or {}, now)
    R.replace_atomic(folder / FILE, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return {"rdap": counts, "unresponsive": len(data["unresponsive"]), "domain_expiring": len(data["domain_expiring"]),
            "similar_name": len(data["similar_name"]), **{k: v for k, v in data["coverage"].items()}}


# ---------------------------------------------------------------- answering (frontend, memory only)
class LifecycleIndex:
    def __init__(self, folder: Path | None = None):
        self.path = Path(folder or R.data_dir()) / FILE
        self._lock = threading.Lock()
        self._mtime, self.data, self.etag = None, None, None

    def current(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        with self._lock:
            if mtime != self._mtime:
                import hashlib
                raw = self.path.read_bytes()
                self.data = json.loads(raw)
                self.etag = '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
                self._mtime = mtime
            return self


_DEFAULT: LifecycleIndex | None = None
_DEFAULT_LOCK = threading.Lock()


def default_index() -> LifecycleIndex:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = LifecycleIndex()
        return _DEFAULT

