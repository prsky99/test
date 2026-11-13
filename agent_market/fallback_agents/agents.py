"""Execute one fallback agent call within a slot budget.

Envelope returned by ``execute``::

    {"agent", "tool", "result": <contract output>, "sources": [{name, url, license, notice}],
     "retrieved_at", "cache": {"status": live|fresh_cache|stale_cache|snapshot, "age_seconds"},
     "partial": bool}

``result`` is validated against the slot contract before it is returned; an
answer that does not fit the contract is an error, never a guess. Failures raise
``FallbackUnavailable`` with a fixed code. Every call appends one usage line
(agent, ok, code, ms, cache status; no inputs) for the fallback usage rate.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from .catalog import SPECS, contract
from .limits import SourceBusy, limiters as make_limiters
from .net import SourceError, get
from .nvd_store import CVE_ID, Snapshot, _text, record as nvd_record
from .versions import in_range

CODES = ("invalid_input", "not_found", "rate_limited", "source_unavailable", "invalid_output")
TTL = {"nvd-cve": (21600, 7 * 86400), "cve-org": (21600, 7 * 86400), "github-advisory": (3600, 21600),
       "epss": (21600, 3 * 86400)}
KEV_TTL, KEV_MAX_STALE = 3600, 72 * 3600
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
PACKAGE = re.compile(r"(?:@[a-z0-9][a-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*")
GHSA_ID = re.compile(r"GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}")


class FallbackUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FallbackAgents:
    def __init__(self, *, http=None, snapshot: Snapshot | None = None, data_dir: Path | str | None = None,
                 usage_dir: Path | str | None = None, clock=time.monotonic, wall=time.time, utc_now=None,
                 limiters=None, budget: float = 3.3):
        self.http, self.clock, self.wall = http, clock, wall
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        root = Path(data_dir or os.environ.get("FALLBACK_AGENTS_DATA", "gateway-data/fallback-agents"))
        self.data_dir = root
        self.snapshot = snapshot or Snapshot(root / "nvd-cve.sqlite3")
        self.usage_dir = Path(usage_dir) if usage_dir else root / "usage"
        self.limiters = limiters or make_limiters(clock=clock)
        self.budget = budget
        self.lock = threading.Lock()
        self.cache: OrderedDict = OrderedDict()
        self.kev = None  # (monotonic fetched, wall fetched, {cve: dateAdded}, catalogVersion)

    # ---------------------------------------------------------------- public
    def execute(self, agent_id: str, arguments: dict) -> dict:
        started = self.clock()
        envelope, code = None, None
        try:
            envelope = self._execute(agent_id, arguments, started)
            return envelope
        except FallbackUnavailable as exc:
            code = exc.code
            raise
        except Exception as exc:  # never leak raw errors upward
            code = "source_unavailable"
            raise FallbackUnavailable(code, "The source is unavailable. No replacement data was generated.") from exc
        finally:
            self._usage(agent_id, envelope, code, started)

    # ---------------------------------------------------------------- core
    def _execute(self, agent_id, arguments, started):
        if agent_id not in SPECS:
            raise FallbackUnavailable("invalid_input", "Unknown fallback agent.")
        spec = SPECS[agent_id]
        c = contract(spec["contract"])
        try:
            jsonschema.Draft202012Validator(c["input_schema"]).validate(arguments)
        except jsonschema.ValidationError as exc:
            raise FallbackUnavailable("invalid_input", "Arguments do not match the tool input schema.") from exc
        handler = getattr(self, "_" + agent_id.replace("-", "_"))
        result, cache, partial = handler(arguments, lambda: self.budget - (self.clock() - started))
        try:
            jsonschema.Draft202012Validator(c["output_schema"]).validate(result)
        except jsonschema.ValidationError as exc:
            raise FallbackUnavailable("invalid_output", "The source answer did not fit the contract.") from exc
        if "cve_id" in arguments and result.get("cve_id") != arguments["cve_id"]:
            raise FallbackUnavailable("invalid_output", "The source answered a different CVE.")
        if ("cvss_score" in result) != ("cvss_version" in result):
            raise FallbackUnavailable("invalid_output", "Score and version must come together.")
        return {"agent": agent_id, "tool": spec["tool"], "result": result,
                "sources": [dict(s) for s in spec["sources"]], "retrieved_at": _now_iso(self.utc_now()),
                "cache": cache, "partial": bool(partial)}

    def _cached(self, key, ttl, fetch, remaining):
        """Fresh cache, else live fetch, else stale cache within max_stale, else error."""
        fresh, max_stale = ttl
        with self.lock:
            hit = self.cache.get(key)
        age = self.clock() - hit[0] if hit else None
        if hit and age <= fresh:
            return hit[1], {"status": "fresh_cache", "age_seconds": int(age)}
        try:
            if remaining() < 0.5:
                raise SourceBusy("No time left for a live call.")
            value = fetch(remaining)
        except FallbackUnavailable as exc:
            if exc.code != "not_found" and hit and age <= max_stale:
                return hit[1], {"status": "stale_cache", "age_seconds": int(age)}
            raise
        except SourceBusy as exc:
            if hit and age <= max_stale:
                return hit[1], {"status": "stale_cache", "age_seconds": int(age)}
            raise FallbackUnavailable("rate_limited", "The source asked us to slow down; try again later.") from exc
        except (SourceError, ValueError, KeyError, TypeError) as exc:
            if hit and age <= max_stale:
                return hit[1], {"status": "stale_cache", "age_seconds": int(age)}
            raise FallbackUnavailable("source_unavailable", "The source is unavailable. No replacement data was generated.") from exc
        with self.lock:
            self.cache[key] = (self.clock(), value)
            self.cache.move_to_end(key)
            while len(self.cache) > 2048:
                self.cache.popitem(last=False)
        return value, {"status": "live", "age_seconds": 0}

    def _get_json(self, url, remaining, *, params=None, limit=2 * 1024 * 1024, not_found=(404,)):
        try:
            response = get(url, limiters=self.limiters, http=self.http, params=params,
                           seconds=max(0.1, remaining() - 0.1), limit=limit)
        except SourceError as exc:
            if exc.status in not_found:
                raise FallbackUnavailable("not_found", "The source has no record for this input.") from exc
            raise
        return json.loads(response.content)

    # ---------------------------------------------------------------- agents
    def _nvd_cve(self, args, remaining):
        cve_id = args["cve_id"]
        try:
            body, status, synced_at = self.snapshot.lookup(cve_id)
        except Exception:
            body, status, synced_at = None, "absent", None
        if body is not None:
            if status == "Rejected":
                raise FallbackUnavailable("not_found", "The CVE is rejected in the NVD.")
            age = int(max(0, self.wall() - synced_at)) if synced_at else 0
            return body, {"status": "snapshot", "age_seconds": age}, False

        def live(rem):
            # Snapshot miss (new CVE or no snapshot): one paced NVD API call if time allows.
            if rem() < 2.5:
                raise SourceBusy("Not enough time for the NVD API.")
            raw = self._get_json("https://services.nvd.nist.gov/rest/json/cves/2.0", rem, params={"cveId": cve_id})
            rows = raw.get("vulnerabilities") or []
            if not rows:
                raise FallbackUnavailable("not_found", "The NVD has no record for this CVE.")
            cve = rows[0]["cve"]
            if cve.get("vulnStatus") == "Rejected":
                raise FallbackUnavailable("not_found", "The CVE is rejected in the NVD.")
            return nvd_record(cve)
        value, cache = self._cached(("nvd-cve", cve_id), TTL["nvd-cve"], live, remaining)
        return value, cache, False

    def _cve_org(self, args, remaining):
        cve_id = args["cve_id"]

        def live(rem):
            raw = self._get_json("https://cveawg.mitre.org/api/cve/" + cve_id, rem, not_found=(400, 404))
            meta = raw.get("cveMetadata") or {}
            if meta.get("cveId") != cve_id:
                raise ValueError("record id mismatch")
            if meta.get("state") != "PUBLISHED":
                raise FallbackUnavailable("not_found", "The CVE Record is not published (rejected or reserved).")
            return cve_org_record(raw)
        value, cache = self._cached(("cve-org", cve_id), TTL["cve-org"], live, remaining)
        return value, cache, False

    def _kev_catalog(self, remaining):
        now = self.clock()
        with self.lock:
            kev = self.kev
        if kev is None:
            kev = self._kev_from_disk()
        if kev and now - kev[0] <= KEV_TTL:
            return kev, {"status": "fresh_cache", "age_seconds": int(now - kev[0])}
        try:
            raw = self._get_json(KEV_URL, remaining, limit=8 * 1024 * 1024, not_found=())
            rows = {r["cveID"]: _text(r.get("dateAdded"), 40) for r in raw["vulnerabilities"]
                    if isinstance(r, dict) and isinstance(r.get("cveID"), str) and CVE_ID.fullmatch(r["cveID"])}
            if len(rows) < 100:
                raise ValueError("catalog too small")
            kev = (self.clock(), self.wall(), rows, _text(raw.get("catalogVersion"), 40))
            self._kev_to_disk(kev)
            with self.lock:
                self.kev = kev
            return kev, {"status": "live", "age_seconds": 0}
        except (SourceBusy, SourceError, FallbackUnavailable, ValueError, KeyError, TypeError) as exc:
            if kev and now - kev[0] <= KEV_MAX_STALE:
                with self.lock:
                    self.kev = kev
                return kev, {"status": "stale_cache", "age_seconds": int(now - kev[0])}
            code = "rate_limited" if isinstance(exc, SourceBusy) else "source_unavailable"
            raise FallbackUnavailable(code, "The KEV catalog is unavailable. No replacement data was generated.") from exc

    def _kev_from_disk(self):
        path = self.data_dir / "kev-catalog.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            age = max(0.0, self.wall() - float(saved["fetched_at"]))
            return (self.clock() - age, float(saved["fetched_at"]), dict(saved["rows"]), saved.get("catalog_version", ""))
        except Exception:
            return None

    def _kev_to_disk(self, kev):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.data_dir / "kev-catalog.json.tmp"
            tmp.write_text(json.dumps({"fetched_at": kev[1], "catalog_version": kev[3], "rows": kev[2]}), encoding="utf-8")
            os.replace(tmp, self.data_dir / "kev-catalog.json")
        except OSError:
            pass  # the in-memory copy still serves

    def _cisa_kev(self, args, remaining):
        cve_id = args["cve_id"]
        kev, cache = self._kev_catalog(remaining)
        result = {"cve_id": cve_id, "kev": cve_id in kev[2], "source": "CISA KEV"}
        if result["kev"] and kev[2][cve_id]:
            result["kev_date_added"] = kev[2][cve_id]
        partial = False

        def live(rem):
            raw = self._get_json("https://api.first.org/data/v1/epss", rem, params={"cve": cve_id}, limit=65536)
            rows = [r for r in raw.get("data") or [] if isinstance(r, dict) and r.get("cve") == cve_id]
            return float(rows[0]["epss"]) if rows else None
        try:
            score, _ = self._cached(("epss", cve_id), TTL["epss"], live, remaining)
        except FallbackUnavailable:
            score, partial = None, True
        if score is not None and 0 <= score <= 1:
            result["epss"] = score
            result["source"] = "CISA KEV; FIRST EPSS"
        return result, cache, partial

    def _github_advisory(self, args, remaining):
        package, ecosystem = args["package"], args["ecosystem"]
        version = args.get("version") or ""
        if not PACKAGE.fullmatch(package) or (version and not re.fullmatch(r"[A-Za-z0-9.+_!~-]{1,64}", version)):
            raise FallbackUnavailable("invalid_input", "Use a valid package name and exact version.")
        gh_eco = {"npm": "npm", "PyPI": "pip"}[ecosystem]

        def live(rem):
            # List the whole package and check ranges here: the API's name@version filter
            # misses other name casings and pre-releases (see versions.py).
            raw = self._get_json("https://api.github.com/advisories", rem, not_found=(), params={
                "ecosystem": gh_eco, "affects": package, "type": "reviewed", "per_page": 100})
            if not isinstance(raw, list):
                raise ValueError("unexpected advisory list")
            return raw[:100], len(raw) >= 100
        (rows, more), cache = self._cached(("github-advisory", ecosystem, package.lower()),
                                           TTL["github-advisory"], live, remaining)
        items, unknown = github_items(rows, package, gh_eco, version)
        partial = more or unknown
        return {"items": items, "partial": partial, "source": "GitHub Advisory Database"}, cache, partial

    # ---------------------------------------------------------------- usage
    def _usage(self, agent_id, envelope, code, started):
        line = {"at": _now_iso(self.utc_now()), "agent": agent_id if agent_id in SPECS else "unknown",
                "ok": envelope is not None, "code": code, "ms": int((self.clock() - started) * 1000),
                "cache": (envelope or {}).get("cache", {}).get("status")}
        try:
            self.usage_dir.mkdir(parents=True, exist_ok=True)
            with open(self.usage_dir / f"{line['at'][:10]}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
        except OSError:
            pass


def cve_org_record(raw: dict) -> dict:
    """CVE JSON 5 record -> cve.record.v1. Score: CNA first, then ADP blocks; in a block the newest CVSS version."""
    meta = raw.get("cveMetadata") or {}
    containers = raw.get("containers") or {}
    cna = containers.get("cna") or {}
    out = {"cve_id": meta["cveId"], "source": "CVE Program"}
    for block in [cna] + [b for b in containers.get("adp") or [] if isinstance(b, dict)]:
        found = None
        for key in ("cvssV4_0", "cvssV3_1", "cvssV3_0", "cvssV2_0"):  # newest version across the block
            for metric in block.get("metrics") or []:
                data = metric.get(key) if isinstance(metric, dict) else None
                if isinstance(data, dict) and isinstance(data.get("baseScore"), (int, float)) \
                        and isinstance(data.get("version"), str) and 0 <= data["baseScore"] <= 10:
                    found = data
                    break
            if found:
                break
        if found:
            out["cvss_score"] = float(found["baseScore"])
            out["cvss_version"] = found["version"][:8]
            if _text(found.get("vectorString"), 200):
                out["cvss_vector"] = _text(found.get("vectorString"), 200)
            break
    text = next((d.get("value") for d in cna.get("descriptions") or []
                 if isinstance(d, dict) and str(d.get("lang", "")).lower().startswith("en")), "")
    if _text(text, 4000):
        out["description"] = _text(text, 4000)
    if _text(meta.get("datePublished"), 40):
        out["published"] = _text(meta.get("datePublished"), 40)
    refs = []
    for ref in cna.get("references") or []:
        url = ref.get("url") if isinstance(ref, dict) else None
        if isinstance(url, str) and url.startswith("https://") and len(url) <= 2000 and " " not in url and url not in refs:
            refs.append(url)
        if len(refs) == 20:
            break
    if refs:
        out["references"] = refs
    return out


def github_items(rows: list, package: str, gh_eco: str, version: str = "") -> tuple[list[dict], bool]:
    """Advisories of ``package`` (any name casing); with ``version``, only those whose range holds it.
    The flag is True when some range could not be read (such an advisory is kept, not dropped)."""
    items, seen, unknown = [], set(), False
    for row in rows[:100]:
        if not isinstance(row, dict) or not isinstance(row.get("ghsa_id"), str) or not GHSA_ID.fullmatch(row["ghsa_id"]):
            continue
        if row["ghsa_id"] in seen or row.get("withdrawn_at"):
            continue
        seen.add(row["ghsa_id"])
        aliases = []
        for ident in row.get("identifiers") or []:
            value = ident.get("value") if isinstance(ident, dict) else None
            if isinstance(value, str) and value != row["ghsa_id"] and re.fullmatch(r"[A-Za-z0-9._:-]{3,64}", value) \
                    and value not in aliases:
                aliases.append(value)
        item = {"id": row["ghsa_id"], "aliases": aliases[:20]}
        if _text(row.get("summary"), 2000):
            item["summary"] = _text(row.get("summary"), 2000)
        if _text(row.get("severity"), 32):
            item["severity"] = _text(row.get("severity"), 32)
        ranges = [_text(v.get("vulnerable_version_range"), 200) for v in row.get("vulnerabilities") or []
                  if isinstance(v, dict) and isinstance(v.get("package"), dict)
                  and str(v["package"].get("name", "")).lower() == package.lower()
                  and v["package"].get("ecosystem") == gh_eco]
        ranges = [r for r in ranges if r]
        if not ranges:
            continue
        if version:
            verdicts = [in_range(version, r, gh_eco) for r in ranges]
            if True not in verdicts:
                if None not in verdicts:
                    continue
                unknown = True
        if ranges:
            item["affected"] = "; ".join(dict.fromkeys(ranges))[:500]
        url = row.get("html_url")
        if isinstance(url, str) and url.startswith("https://github.com/advisories/") and len(url) <= 2000:
            item["url"] = url
        items.append(item)
        if len(items) == 50:
            unknown = True
            break
    return items, unknown


_DEFAULT: FallbackAgents | None = None
_DEFAULT_LOCK = threading.Lock()


def run(agent_id: str, arguments: dict) -> dict:
    """Entry point for the necklace runner (``kind: agentcon`` chain links)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = FallbackAgents()
    return _DEFAULT.execute(agent_id, arguments)


def slot_output(envelope: dict) -> dict:
    """The contract-shaped part a slot keeps."""
    return envelope["result"]
