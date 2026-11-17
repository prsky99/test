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
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import jsonschema

from .catalog import SPECS, contract
from .limits import SourceBusy, limiters as make_limiters
from .net import SourceError, get
from .tz_grid import parse_point
from .nvd_store import CVE_ID, Snapshot, _text, record as nvd_record
from .versions import in_range

CODES = ("invalid_input", "not_found", "rate_limited", "source_unavailable", "invalid_output", "stale", "internal_error")
INTERNAL = "internal_error"


def failure_code(exc: BaseException) -> str:
    """What a failure says about whom (PM 11-16 source review): the source asked for a pause (rate_limited), the
    source failed or sent something unusable (source_unavailable: SourceError, and ValueError, which our parsers
    raise on purpose for a bad answer and json raises for a broken one), or our own code broke on a case it does not
    handle (internal_error: KeyError, TypeError, AttributeError, IndexError and anything else). Before, every one of
    these read as source_unavailable, so our parser bugs looked like source outages."""
    if isinstance(exc, SourceBusy):
        return "rate_limited"
    if isinstance(exc, (SourceError, ValueError)):
        return "source_unavailable"
    return INTERNAL


def failure_message(code: str, what: str = "The source") -> str:
    if code == INTERNAL:
        return "Our substitute failed on this request (an internal error, not the source). No answer was given."
    if code == "rate_limited":
        return f"{what} asked us to slow down; try again later."
    return f"{what} is unavailable. No replacement data was generated."
# Data age (PM 11-14, user emphasis): every answer states when its source data was updated and how
# old our copy is. A copy older than MAX_AGE is an error ("stale") so the slot moves to the next member.
MAX_AGE = {"nvd-cve": 6 * 3600, "cve-org": 24 * 3600, "cisa-kev": 24 * 3600, "github-advisory": 6 * 3600,
           "package-registry": 6 * 3600, "depsdev-package": 24 * 3600, "gleif-lei": 24 * 3600,
           "sec-edgar": 24 * 3600, "wikipedia-summary": 24 * 3600, "arxiv-search": 48 * 3600,
           "worldbank-indicator": 24 * 3600, "met-weather": 3 * 3600,
           "public-holidays": 400 * 86400, "holiday-calendar": 400 * 86400, "sec-filings": 24 * 3600,
           "software-incident": 6 * 3600, "scorecard": 24 * 3600, "site-readiness": 24 * 3600,
           "wiki-grounding": 24 * 3600, "ecb-fx": 26 * 3600, "usgs-quakes": 3600,
           "tz-time": 400 * 86400, "airport-lookup": 8 * 86400, "wiktionary-define": 7 * 86400,
           "github-repo": 24 * 3600, "rdap-domain": 7 * 86400, "unit-convert": 10 * 365 * 86400,
           "wikidata-place": 7 * 86400, "wikidata-book": 7 * 86400, "gdelt-news": 6 * 3600, "census-geocode": 30 * 86400, "mcp-registry": 86400, "github-releases": 86400, "package-releases": 86400, "tls-certificate": 86400,
           "sec-company-profile": 24 * 3600, "sun-times": 10 * 365 * 86400, "site-reachability": 60,
           "dns-spf-dmarc": 86400, "package-readme": 86400, "agent-record": 2 * 86400}  # rules age from the library release; update the pin at least yearly
TTL = {"nvd-cve": (6 * 3600, 6 * 3600), "cve-org": (6 * 3600, 24 * 3600), "github-advisory": (3600, 6 * 3600),
       "epss": (6 * 3600, 48 * 3600), "package-registry": (3600, 6 * 3600), "depsdev-package": (6 * 3600, 24 * 3600),
       "gleif-lei": (6 * 3600, 24 * 3600), "sec-edgar": (6 * 3600, 24 * 3600), "sec-tickers": (6 * 3600, 24 * 3600),
       "sec-company-profile": (6 * 3600, 24 * 3600),
       "wikipedia-summary": (6 * 3600, 24 * 3600), "arxiv-search": (24 * 3600, 48 * 3600),
       "worldbank-indicator": (6 * 3600, 24 * 3600), "sec-filings": (3600, 24 * 3600),
       "software-incident": (3600, 6 * 3600), "scorecard": (6 * 3600, 24 * 3600),
       "site-readiness": (6 * 3600, 24 * 3600), "wiki-grounding": (6 * 3600, 24 * 3600), "ecb-fx": (3600, 26 * 3600),
       "usgs-quakes": (300, 3600), "wiktionary-define": (86400, 7 * 86400), "github-repo": (6 * 3600, 24 * 3600),
       "rdap-domain": (6 * 3600, 7 * 86400), "rdap-bootstrap": (86400, 7 * 86400),
       "wikidata-place": (86400, 7 * 86400), "wikidata-book": (86400, 7 * 86400),
       "gdelt-news": (3600, 6 * 3600), "census-geocode": (7 * 86400, 30 * 86400),
       "mcp-registry": (3600, 6 * 3600), "github-releases": (3600, 24 * 3600),
       "package-releases": (6 * 3600, 24 * 3600), "tls-certificate": (6 * 3600, 24 * 3600),
       "dns-spf-dmarc": (3600, 24 * 3600), "package-readme": (6 * 3600, 24 * 3600)}  # (serve from cache without asking, longest a cached copy may serve)
KEV_TTL, KEV_MAX_STALE = 3600, 24 * 3600
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
        # Host pacing shared by every process on this machine (frontend, jobs, execution): R30, PM 11-15.
        self.limiters = limiters or make_limiters(clock=clock, shared_dir=root / "host-limits", wall=wall)
        self.budget = budget
        self.lock = threading.Lock()
        self.cache: OrderedDict = OrderedDict()
        self.kev = None  # (monotonic fetched, wall fetched, {cve: dateAdded}, catalogVersion)
        self.weather: OrderedDict = OrderedDict()  # (lat, lon) -> dict(value, as_of, expires, last_modified, at)
        self.airports = None
        self.tz_grid = None
        import socket as _socket
        self.resolve = lambda host: _socket.getaddrinfo(host, 443, proto=_socket.IPPROTO_TCP)   # tests replace these
        self.connect = lambda addr, timeout: _socket.create_connection(addr, timeout=timeout)
        from .dns_txt import txt as _txt
        self.dns_txt = lambda name, timeout: _txt(name, timeout)   # our own resolver; tests replace it
        self.country_grid = None

    # ---------------------------------------------------------------- public
    def execute(self, agent_id: str, arguments: dict) -> dict:
        started = self.clock()
        envelope, code = None, None
        try:
            envelope = self._execute(agent_id, arguments, started)
            return envelope
        except FallbackUnavailable as exc:
            code = exc.code
            cause = type(exc.__cause__).__name__ if exc.__cause__ is not None else None
            raise
        except Exception as exc:  # never leak raw errors upward; a bug of ours is said to be ours
            code, cause = failure_code(exc), type(exc).__name__
            raise FallbackUnavailable(code, failure_message(code)) from exc
        finally:
            self._usage(agent_id, envelope, code, started, locals().get("cause"))

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
        result, cache, partial, as_of = handler(arguments, lambda: self.budget - (self.clock() - started))
        field_sources = cache.pop("field_sources", None)
        if cache["age_seconds"] > MAX_AGE[agent_id]:
            raise FallbackUnavailable("stale", f"Our copy of the source is {cache['age_seconds']} s old, over the "
                                               f"{MAX_AGE[agent_id]} s limit. No answer was given from it.")
        try:
            jsonschema.Draft202012Validator(c["output_schema"]).validate(result)
        except jsonschema.ValidationError as exc:
            raise FallbackUnavailable("invalid_output", "The source answer did not fit the contract.") from exc
        contract_check(spec["contract"], arguments, result)
        return {"agent": agent_id, "tool": spec["tool"], "result": result,
                "sources": [dict(s) for s in spec["sources"]], "retrieved_at": _now_iso(self.utc_now()),
                "cache": cache, "partial": bool(partial),
                "freshness": {"data_as_of": as_of, "age_seconds": cache["age_seconds"],
                              "max_age_seconds": MAX_AGE[agent_id]},
                **({"field_sources": field_sources} if field_sources else {})}

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
        except Exception as exc:     # a pause, a source failure or a bug of ours (failure_code)
            if hit and age <= max_stale:
                return hit[1], {"status": "stale_cache", "age_seconds": int(age)}
            code = failure_code(exc)
            raise FallbackUnavailable(code, failure_message(code)) from exc
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
            age = int(max(0, self.wall() - synced_at)) if synced_at else MAX_AGE["nvd-cve"] + 1
            as_of = {"NVD": self.snapshot.meta("source_updated_at") or None}
            return body, {"status": "snapshot", "age_seconds": age}, False, as_of

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
            return nvd_record(cve), _text(cve.get("lastModified"), 40) or None
        (value, as_of), cache = self._cached(("nvd-cve", cve_id), TTL["nvd-cve"], live, remaining)
        return value, cache, False, {"NVD": as_of}

    def _cve_org(self, args, remaining):
        cve_id = args["cve_id"]

        def live(rem):
            raw = self._get_json("https://cveawg.mitre.org/api/cve/" + cve_id, rem, not_found=(400, 404))
            meta = raw.get("cveMetadata") or {}
            if meta.get("cveId") != cve_id:
                raise ValueError("record id mismatch")
            if meta.get("state") != "PUBLISHED":
                raise FallbackUnavailable("not_found", "The CVE Record is not published (rejected or reserved).")
            return cve_org_record(raw), _text(meta.get("dateUpdated"), 40) or None
        (value, as_of), cache = self._cached(("cve-org", cve_id), TTL["cve-org"], live, remaining)
        return value, cache, False, {"CVE Program": as_of}

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
            kev = (self.clock(), self.wall(), rows, _text(raw.get("catalogVersion"), 40),
                   _text(raw.get("dateReleased"), 40))
            self._kev_to_disk(kev)
            with self.lock:
                self.kev = kev
            return kev, {"status": "live", "age_seconds": 0}
        except Exception as exc:
            if kev and now - kev[0] <= KEV_MAX_STALE:
                with self.lock:
                    self.kev = kev
                return kev, {"status": "stale_cache", "age_seconds": int(now - kev[0])}
            code = exc.code if isinstance(exc, FallbackUnavailable) else failure_code(exc)
            raise FallbackUnavailable(code, failure_message(code, "The KEV catalog")) from exc

    def _kev_from_disk(self):
        path = self.data_dir / "kev-catalog.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            age = max(0.0, self.wall() - float(saved["fetched_at"]))
            return (self.clock() - age, float(saved["fetched_at"]), dict(saved["rows"]), saved.get("catalog_version", ""),
                    saved.get("date_released", ""))
        except Exception:
            return None

    def _kev_to_disk(self, kev):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.data_dir / "kev-catalog.json.tmp"
            tmp.write_text(json.dumps({"fetched_at": kev[1], "catalog_version": kev[3], "date_released": kev[4],
                                       "rows": kev[2]}), encoding="utf-8")
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
            return (float(rows[0]["epss"]), _text(rows[0].get("date"), 40) or None) if rows else (None, None)
        as_of = {"CISA KEV": kev[4] or None}
        try:
            (score, epss_date), _ = self._cached(("epss", cve_id), TTL["epss"], live, remaining)
        except FallbackUnavailable:
            score, partial = None, True
        if score is not None and 0 <= score <= 1:
            result["epss"] = score
            result["source"] = "CISA KEV; FIRST EPSS"
            as_of["FIRST EPSS"] = epss_date
        return result, cache, partial, as_of

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
            # The database has no single release stamp; the listing is current as of retrieval.
            return raw[:100], len(raw) >= 100, _now_iso(self.utc_now())
        (rows, more, as_of), cache = self._cached(("github-advisory", ecosystem, package.lower()),
                                                  TTL["github-advisory"], live, remaining)
        items, unknown = github_items(rows, package, gh_eco, version)
        partial = more or unknown
        result = {"items": items, "partial": partial, "source": "GitHub Advisory Database"}
        return result, cache, partial, {"GitHub Advisory Database": as_of}

    def _package_args(self, args):
        package, ecosystem = args["package"], args["ecosystem"]
        if not PACKAGE.fullmatch(package):
            raise FallbackUnavailable("invalid_input", "Use a valid package name.")
        return package, ecosystem

    def _package_registry(self, args, remaining):
        package, ecosystem = self._package_args(args)

        def live(rem):
            if ecosystem == "npm":
                raw = self._get_json("https://registry.npmjs.org/" + quote(package, safe="@") + "/latest", rem,
                                     limit=1024 * 1024)
                if raw.get("name") != package or not isinstance(raw.get("version"), str):
                    raise ValueError("package mismatch")
                repo = raw.get("repository")
                out = {"latest_version": _text(raw["version"], 64), "deprecated": bool(raw.get("deprecated")),
                       "source": "npm public registry"}
                url = repository_url(repo.get("url") if isinstance(repo, dict) else repo)
            else:
                raw = self._get_json("https://pypi.org/pypi/" + quote(package, safe="") + "/json", rem,
                                     limit=12 * 1024 * 1024)
                info = raw.get("info") or {}
                if pep503(info.get("name", "")) != pep503(package) or not isinstance(info.get("version"), str):
                    raise ValueError("package mismatch")
                files = [f for f in raw.get("urls") or [] if isinstance(f, dict)]
                out = {"latest_version": _text(info["version"], 64), "source": "PyPI JSON API"}
                times = sorted(_text(f.get("upload_time_iso_8601"), 40) for f in files if f.get("upload_time_iso_8601"))
                if times:
                    out["released_at"] = times[0]
                inactive = any("Development Status :: 7 - Inactive" in str(c) for c in info.get("classifiers") or [])
                if inactive or info.get("yanked") or (files and all(f.get("yanked") for f in files)):
                    out["deprecated"] = True
                links = info.get("project_urls") or {}
                ordered = [links.get(k) for k in ("Source", "Source Code", "Repository", "Code", "GitHub", "source")]
                ordered += list(links.values()) + [info.get("home_page")]
                url = next((u for u in (repository_url(x, hosted_only=True) for x in ordered) if u), None)
            if url:
                out["repository"] = url
            return out, _now_iso(self.utc_now())
        (out, as_of), cache = self._cached(("package-registry", ecosystem, package.lower()),
                                           TTL["package-registry"], live, remaining)
        return out, cache, False, {out["source"]: as_of}

    def _depsdev_package(self, args, remaining):
        """deps.dev for its own generated data only (default-version choice, source-repository association; CC BY 4.0)
        and the Scorecard API for the score (CDLA-Permissive-2.0); PM 11-14. Registry facts (release time,
        deprecation) are left to package-registry, which reads the registries directly."""
        package, ecosystem = self._package_args(args)
        system = {"npm": "npm", "PyPI": "pypi"}[ecosystem]
        base = "https://api.deps.dev/v3/systems/" + system + "/packages/" + quote(package, safe="")

        def live(rem):
            raw = self._get_json(base, rem, limit=4 * 1024 * 1024)
            default = next((v for v in raw.get("versions") or [] if isinstance(v, dict) and v.get("isDefault")), None)
            if not default:
                raise FallbackUnavailable("not_found", "deps.dev has no default version for this package.")
            version = default["versionKey"]["version"]
            out = {"latest_version": _text(version, 64)}
            fields = {"latest_version": "deps.dev default version (CC BY 4.0)"}
            as_of = {"deps.dev": _now_iso(self.utc_now())}
            partial = False
            try:
                doc = self._get_json(base + "/versions/" + quote(version, safe=""), rem, limit=2 * 1024 * 1024)
                project = next((p["projectKey"]["id"] for p in doc.get("relatedProjects") or []
                                if isinstance(p, dict) and p.get("relationType") == "SOURCE_REPO"
                                and isinstance((p.get("projectKey") or {}).get("id"), str)), None)
                if project and re.fullmatch(r"(github\.com|gitlab\.com|bitbucket\.org)/[\w.-]+/[\w.-]+", project):
                    out["repository"] = "https://" + project
                    fields["repository"] = "deps.dev source-repository association (CC BY 4.0)"
                    card = self._get_json("https://api.scorecard.dev/projects/" + project, rem, limit=1024 * 1024)
                    if isinstance(card.get("score"), (int, float)) and 0 <= card["score"] <= 10:
                        out["scorecard"] = float(card["score"])
                        fields["scorecard"] = "OpenSSF Scorecard API (CDLA-Permissive-2.0)"
                        as_of["OpenSSF Scorecard"] = _text(card.get("date"), 40) or None
            except (SourceBusy, SourceError, FallbackUnavailable, ValueError, KeyError, TypeError):
                partial = True  # the version stands; repository or score could not be read in time
            out["source"] = "; ".join(f"{k}: {v}" for k, v in fields.items())
            return out, as_of, partial, fields
        (out, as_of, partial, fields), cache = self._cached(("depsdev-package", ecosystem, package.lower()),
                                                            TTL["depsdev-package"], live, remaining)
        return out, dict(cache, field_sources=fields), partial, as_of

    def _company_args(self, args):
        name = " ".join(args["name"].split())
        country = (args.get("country") or "").upper()
        if not company_key(name) or (country and not re.fullmatch(r"[A-Z]{2}", country)):
            raise FallbackUnavailable("invalid_input", "Use a company legal name and an optional ISO country code.")
        return name, country

    def _gleif_lei(self, args, remaining):
        name, country = self._company_args(args)

        def search(term, rem):
            params = {"filter[entity.names]": term, "page[size]": 100}
            if country:
                params["filter[entity.legalAddress.country]"] = country
            raw = self._get_json("https://api.gleif.org/api/v1/lei-records", rem, params=params, limit=2 * 1024 * 1024)
            return [r.get("attributes") or {} for r in raw.get("data") or [] if isinstance(r, dict)]

        def names(r):  # legal name plus registered other names (e.g. a transliterated English name)
            entity = r.get("entity") or {}
            yield (entity.get("legalName") or {}).get("name", "")
            for other in entity.get("otherNames") or []:
                if isinstance(other, dict):
                    yield other.get("name", "")

        def live(rem):
            # GLEIF matches names loosely. Search legal and other names by the core name first (legal suffix
            # removed, so "NVIDIA Corp" finds "NVIDIA CORPORATION"), then by the full name when a common core
            # name crowds the exact one out of the first page; keep only exact name keys either way.
            wanted = name_keys(name)
            # A short or common name ("HSBC", "Philips") usually means the group's parent, which name rules
            # cannot tell from a same-name subsidiary. Wikidata's LEI link (P1278) on the item that name finds
            # first decides, and only for a GLEIF record whose name holds every word of the input (and the same
            # country): Wikidata picks among GLEIF records, it never supplies the record. A name without a legal
            # form asks Wikidata while GLEIF is searched, so a parent outside the first result page can still be
            # read directly inside the time limit.
            linked = self._wikidata_leis_async(name, rem) if core_name(name) == name else None
            rows = search(core_name(name), rem)
            keys = lambda r: [name_keys(n) for n in names(r)]
            issued = lambda r: (r.get("registration") or {}).get("status") == "ISSUED"
            exact = [r for r in rows if any(k[0] == wanted[0] for k in keys(r))]
            rec = tiered_match(exact, wanted, keys, issued) if exact else None
            read_record = [False]  # GLEIF calls per request: one search plus at most one more (gate budget 11-15)
            if rec is None:
                leis = linked() if linked else (self._wikidata_leis(name, rem) if rem() > 1.6 else [])
                rec = self._pick_linked_lei(leis, country, wanted, rows, names, rem, read_record)
            if rec is None:
                rec = tiered_match(rows, wanted, keys, issued)
            if rec is None and core_name(name) != name and rem() > 1.2 and not read_record[0]:
                rows = search(name, rem)
                rec = tiered_match(rows, wanted, lambda r: [name_keys(n) for n in names(r)],
                                   lambda r: (r.get("registration") or {}).get("status") == "ISSUED")
            if rec is None:
                raise FallbackUnavailable("not_found", "GLEIF has no LEI record with this legal name.")
            entity, reg = rec.get("entity") or {}, rec.get("registration") or {}
            ids = {"LEI": rec["lei"]}
            if _text(entity.get("registeredAs"), 64):
                ids["company number"] = _text(entity.get("registeredAs"), 64)
                if _text((entity.get("registeredAt") or {}).get("id"), 16):
                    ids["registration authority (GLEIF RA code)"] = _text(entity["registeredAt"]["id"], 16)
            legal = _text(entity["legalName"]["name"], 3000)
            if not legal.isascii():
                english = next((_text(n, 900) for n in names(rec) if n and n.isascii()), "")
                if english:
                    legal = f"{legal} ({english})"
            out = {"legal_name": legal, "identifiers": ids,
                   "status": _text(f"{entity.get('status', '')} (LEI {reg.get('status', '')})", 40),
                   "url": "https://search.gleif.org/#/record/" + rec["lei"], "source": "GLEIF"}
            city = _text((entity.get("legalAddress") or {}).get("city"), 200)
            if city:
                out["address_city"] = city
            if not re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", rec["lei"]):
                raise ValueError("bad LEI")
            return out, _text(reg.get("lastUpdateDate"), 40) or None
        (out, as_of), cache = self._cached(("gleif-lei", company_key(name), country), TTL["gleif-lei"], live, remaining)
        return out, cache, False, {"GLEIF": as_of}

    def _wikidata_leis(self, name, rem) -> list[str]:
        """LEIs that Wikidata links (P1278) to the items its search ranks for NAME, best first; [] on any failure
        (the tie-break is optional: the name rules still answer or report the tie)."""
        query = ('SELECT ?lei ?ord WHERE { SERVICE wikibase:mwapi { bd:serviceParam wikibase:endpoint '
                 '"www.wikidata.org"; wikibase:api "EntitySearch"; mwapi:search "%s"; mwapi:language "en". '
                 '?item wikibase:apiOutputItem mwapi:item. ?ord wikibase:apiOrdinal true. } '
                 '?item wdt:P1278 ?lei. } ORDER BY ?ord LIMIT 10') % name.replace("\\", " ").replace('"', " ")
        try:
            response = get("https://query.wikidata.org/sparql", limiters=self.limiters, http=self.http,
                           params={"query": query, "format": "json"}, seconds=max(0.1, min(1.5, rem() - 1.0)),
                           limit=128 * 1024, accept="application/sparql-results+json")
            bindings = json.loads(response.content).get("results", {}).get("bindings") or []
        except Exception:
            return []
        leis = []
        for row in bindings:
            lei = str((row.get("lei") or {}).get("value", "")).upper()
            if re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", lei) and lei not in leis:
                leis.append(lei)
        return leis

    def _wikidata_leis_async(self, name, rem):
        """Start _wikidata_leis on its own thread (same context, so the shared test ledger still counts it);
        returns a function that waits for the answer."""
        import contextvars
        import threading
        box: list = [[]]
        ctx = contextvars.copy_context()
        worker = threading.Thread(target=lambda: box.__setitem__(0, ctx.run(self._wikidata_leis, name, rem)),
                                  daemon=True)
        worker.start()

        def result():
            worker.join(max(0.0, min(1.6, rem() - 0.5)))
            return box[0] if not worker.is_alive() else []
        return result

    def _pick_linked_lei(self, leis, country, wanted, rows, names, rem, read_record=None):
        need = set(wanted[1].split())  # every word but the legal form: "HSBC Holdings" never means HSBC Bank plc
        by_lei = {r.get("lei"): r for r in rows}
        read_record = read_record if read_record is not None else [False]
        for lei in leis[:3]:
            rec = by_lei.get(lei)
            if rec is None and not read_record[0] and rem() > 1.3:
                read_record[0] = True  # at most one direct record read
                try:
                    raw = self._get_json(f"https://api.gleif.org/api/v1/lei-records/{lei}", rem)
                    rec = (raw.get("data") or {}).get("attributes") or None
                except FallbackUnavailable:
                    rec = None
            if not rec:
                continue
            entity = rec.get("entity") or {}
            if country and (entity.get("legalAddress") or {}).get("country") != country:
                continue
            if any(need <= set(name_keys(n)[0].split()) for n in names(rec)):
                return rec
        return None

    def _sec_index(self, remaining):
        """EDGAR ticker list (daily cache): name key -> CIKs, ticker -> CIK."""
        def tickers(rem):
            raw = self._get_json("https://www.sec.gov/files/company_tickers.json", rem, limit=4 * 1024 * 1024,
                                 not_found=())
            index, by_ticker = ({}, {}, {}), {}
            for row in raw.values():
                if isinstance(row, dict) and isinstance(row.get("cik_str"), int) and isinstance(row.get("title"), str):
                    # EDGAR titles may carry a state tag ("QUALCOMM INC/DE"); it is not part of the name.
                    title = re.sub(r"\s*/[A-Z]{2,3}/?$", "", row["title"].strip())
                    for tier, key in enumerate(name_keys(title)):
                        index[tier].setdefault(key, set()).add(row["cik_str"])
                    if isinstance(row.get("ticker"), str):
                        by_ticker[row["ticker"].upper()] = row["cik_str"]
            if len(index[0]) < 1000:
                raise ValueError("ticker list too small")
            return (index, by_ticker), _now_iso(self.utc_now())
        ((index, by_ticker), _), list_cache = self._cached(("sec-tickers",), TTL["sec-tickers"], tickers, remaining)
        return index, by_ticker, list_cache

    def _sec_edgar(self, args, remaining):
        name, country = self._company_args(args)
        index, _, list_cache = self._sec_index(remaining)
        cik = sec_lookup(index, name)

        def live(rem):
            raw = self._get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", rem, limit=8 * 1024 * 1024)
            if int(raw.get("cik", -1)) != cik:
                raise ValueError("CIK mismatch")
            ids = {"SEC CIK": str(cik)}
            tick = [_text(t, 12) for t in raw.get("tickers") or [] if isinstance(t, str)]
            if tick:
                ids["ticker"] = ", ".join(tick[:5])
            exch = [_text(e, 20) for e in raw.get("exchanges") or [] if isinstance(e, str) and e]
            if exch:
                ids["exchange"] = ", ".join(exch[:5])
            if isinstance(raw.get("lei"), str) and re.fullmatch(r"[A-Z0-9]{20}", raw["lei"]):
                ids["LEI"] = raw["lei"]
            out = {"legal_name": _text(raw.get("name"), 4000), "identifiers": ids,
                   "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}",
                   "source": "SEC EDGAR"}
            if _text(raw.get("category"), 40):
                out["status"] = _text(raw.get("category"), 40)
            city = _text(((raw.get("addresses") or {}).get("business") or {}).get("city"), 200)
            if city:
                out["address_city"] = city
            if not out["legal_name"]:
                raise ValueError("no name")
            return out, _now_iso(self.utc_now())
        (out, as_of), cache = self._cached(("sec-edgar", cik), TTL["sec-edgar"], live, remaining)
        if list_cache["age_seconds"] > cache["age_seconds"]:
            cache = list_cache
        return out, cache, False, {"SEC EDGAR": as_of}

    def _sec_company_profile(self, args, remaining):
        """company.profile.v1 from SEC EDGAR submissions (workflow 11-16, company-due-diligence v2 background; PM 11-16:
        its own contract, judged apart from encyclopedia.summary.v1):
        a one- or two-sentence company profile built from the filer's own registration (SIC industry, state of
        incorporation, business address, tickers), said to be from SEC filings and not an encyclopedia article.
        The company is "CIK 320193" (or the bare number), an exact SEC filer name (with or without its legal form)
        or a listed ticker; a name shared by several filers is not guessed."""
        title = " ".join(str(args.get("company") or "").split())
        if not title or any(c in title for c in "|#<>[]{}"):
            raise FallbackUnavailable("invalid_input", "Use a CIK, an SEC filer name or a ticker.")
        cik, list_cache = None, None
        m = re.fullmatch(r"(?:CIK[\s:#-]*)?0*([0-9]{1,10})", title, re.I)
        if m:
            cik = int(m[1])
        else:
            index, by_ticker, list_cache = self._sec_index(remaining)
            for tier in (0, 1):
                ciks = index[tier].get(name_keys(title)[tier]) or set()
                if len(ciks) > 1:
                    raise FallbackUnavailable("not_found", "Several SEC filers share this name; use the CIK.")
                if ciks:
                    cik = next(iter(ciks))
                    break
            if cik is None and re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", title) and title.upper() in by_ticker:
                cik = by_ticker[title.upper()]
            if cik is None:
                raise FallbackUnavailable("not_found", "No SEC filer has this CIK, exact name or ticker.")

        def live(rem):
            raw = self._get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", rem, limit=8 * 1024 * 1024)
            if int(raw.get("cik", -1)) != cik:
                raise ValueError("CIK mismatch")
            name = _text(raw.get("name"), 300)
            if not name:
                raise ValueError("no name")
            facts = []
            sic, sic_text = _text(raw.get("sic"), 8), _text(raw.get("sicDescription"), 200)
            if sic_text:
                facts.append(f"its SEC industry classification is {sic_text}" + (f" (SIC {sic})" if sic else ""))
            state = _text(raw.get("stateOfIncorporationDescription") or raw.get("stateOfIncorporation"), 80)
            if state:
                facts.append(f"it is incorporated in {state}")
            business = (raw.get("addresses") or {}).get("business") or {}
            city = _text(business.get("city"), 120)
            where = _text(business.get("stateOrCountryDescription") or business.get("stateOrCountry"), 80)
            if city:
                facts.append("its business address is in " + ", ".join(x for x in (city.title(), where) if x))
            tickers = [_text(t, 12) for t in raw.get("tickers") or [] if isinstance(t, str)][:5]
            exchanges = [_text(e, 20) for e in raw.get("exchanges") or [] if isinstance(e, str) and e][:5]
            if tickers:
                facts.append("it files under the ticker" + ("s " if len(tickers) > 1 else " ") + ", ".join(tickers)
                             + (f" ({', '.join(exchanges)})" if exchanges else ""))
            summary = f"{name} (SEC CIK {cik})"
            summary += (": " + "; ".join(facts) + ".") if facts else " is an SEC EDGAR filer."
            summary += " Company profile from SEC EDGAR filings (not an encyclopedia article)."
            out = {"title": name, "summary": summary[:4000], "cik": str(cik),
                   "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}",
                   "source": "SEC EDGAR filings (company profile, not an encyclopedia article)"}
            if sic_text:
                out["industry"] = sic_text
            if tickers:
                out["tickers"] = tickers
            return out, _now_iso(self.utc_now())
        (out, as_of), cache = self._cached(("sec-company-profile", cik), TTL["sec-company-profile"], live, remaining)
        if list_cache is not None and list_cache["age_seconds"] > cache["age_seconds"]:
            cache = list_cache
        return out, cache, False, {"SEC EDGAR": as_of}

    def _wikipedia_summary(self, args, remaining):
        title = " ".join(args["title"].split())
        if not title or any(c in title for c in "|#<>[]{}"):
            raise FallbackUnavailable("invalid_input", "Use a plain article title.")

        def live(rem):
            raw = self._get_json("https://en.wikipedia.org/w/api.php", rem, limit=512 * 1024, params={
                "action": "query", "prop": "extracts|info|pageprops", "exintro": 1, "explaintext": 1,
                "redirects": 1, "inprop": "url", "ppprop": "disambiguation", "titles": title,
                "format": "json", "formatversion": 2, "maxlag": 5})
            pages = (raw.get("query") or {}).get("pages") or []
            page = pages[0] if len(pages) == 1 else None
            missing = page is None or page.get("missing") or page.get("invalid")
            ambiguous = not missing and "disambiguation" in (page.get("pageprops") or {})
            if missing or ambiguous:
                # 11-16 company v2 (workflow): "Bjs Restaurants", "Dexcom" and "Entravision Communications" missed
                # their articles because titles are case- and punctuation-exact after the first letter. One title
                # search (read-only, same host) then takes only an article whose title is the asked one up to case and
                # punctuation; anything else stays not_found, so a title lookup never answers about something else.
                page = self._wiki_search_title(title, rem)
                if page is None:
                    raise FallbackUnavailable("not_found", "This title is a disambiguation page; use a more specific title."
                                              if ambiguous else "Wikipedia has no article with this title.")
            summary = lead(page.get("extract") or "", 1500)
            url = page.get("fullurl") or ""
            if not summary or not url.startswith("https://en.wikipedia.org/wiki/"):
                raise ValueError("no extract")
            out = {"title": _text(page.get("title"), 4000), "summary": summary, "url": url,
                   "source": "Wikipedia (CC BY-SA 4.0, Wikipedia contributors)"}
            return out, _text(page.get("touched"), 40) or None
        (out, as_of), cache = self._cached(("wikipedia-summary", title.casefold()), TTL["wikipedia-summary"],
                                           live, remaining)
        return out, cache, False, {"Wikipedia": as_of}

    def _wiki_search_title(self, title, rem):
        raw = self._get_json("https://en.wikipedia.org/w/api.php", rem, limit=512 * 1024, params={
            # title (prefix) search: it matches "Bjs Restaurants" to "BJ's Restaurants", which full-text search
            # does not (checked 11-16), and returns the leads in the same request
            "action": "query", "generator": "prefixsearch", "gpssearch": title, "gpslimit": 5, "gpsnamespace": 0,
            "prop": "extracts|info|pageprops", "exintro": 1, "explaintext": 1, "exlimit": 5, "inprop": "url",
            "ppprop": "disambiguation", "redirects": 1, "format": "json", "formatversion": 2, "maxlag": 5})
        pages = sorted((p for p in (raw.get("query") or {}).get("pages") or [] if isinstance(p, dict)),
                       key=lambda p: p.get("index", 99))
        asked = title_words(title)
        usable = [p for p in pages if "disambiguation" not in (p.get("pageprops") or {}) and p.get("extract")]
        # only the same title up to case and punctuation ("DEXCOM" -> "Dexcom", never "Dexcom CGM"); a title with
        # more words ("Nope (band)", "X Records") is another subject (PM 11-16), so it stays not_found
        for page in usable:
            if title_words(str(page.get("title") or "")) == asked:
                return page
        return None

    def _arxiv_search(self, args, remaining):
        query = " ".join(args["query"].split())
        limit = args.get("limit", 5)
        words = re.findall(r"[A-Za-z0-9]+", query.lower())
        terms = [w for w in words if w not in STOPWORDS] or words
        if not terms or len(terms) > 12:
            raise FallbackUnavailable("invalid_input", "Use 1 to 12 plain keywords.")

        # 11-16 gate (holdout-r3 28/30): "teacher AND burnout" anywhere ranked papers that only mention both words.
        # One request (arXiv asks for 3 s between calls, longer than a call's budget) that also takes titles carrying
        # the phrase itself; those go first below.
        phrase = " ".join(words) if 2 <= len(words) <= 4 and len(terms) >= 2 else None
        # 11-16 role task papers-attention (2/3), PM decision a: a query of more than four words is searched in titles
        # only (its first five words as a phrase, or every keyword in the title). Measured 11-16: ORed with the
        # all-fields search, arXiv's relevance put "Attention Is All You Need" outside the 50 results; on its own the
        # title search returned it first. arXiv allows one call every 3 s, so one answer cannot ask twice. The price:
        # a long descriptive query whose words are not in titles finds fewer papers or none (deploy/FALLBACK_AGENTS.md).
        # Two to four words (the topic slot's input) keep the earlier search: the title phrase OR all fields.
        lead = " ".join(words[:5]) if len(words) > 4 else None
        phrases = [p for p in (phrase, lead) if p]
        if lead:
            search = f'ti:"{lead}" OR (' + " AND ".join("ti:" + t for t in terms) + ")"
        else:
            search = " AND ".join("all:" + t for t in terms)
            if phrase:
                search = f'ti:"{phrase}" OR ({search})'

        def live(rem):
            response = get("https://export.arxiv.org/api/query", limiters=self.limiters, http=self.http,
                           seconds=max(0.1, rem() - 0.1), limit=2 * 1024 * 1024, accept="application/atom+xml",
                           params={"search_query": search, "start": 0, "max_results": 50})
            return arxiv_entries(response.content), _now_iso(self.utc_now())
        (entries, as_of), cache = self._cached(("arxiv-search", " ".join(terms)), TTL["arxiv-search"], live, remaining)
        # The API's own order does not favor title matches: rank by query words in the title, then by fewer
        # extra title words, then by the API order.
        def stem(w):
            return w[:-1] if len(w) > 3 and w.endswith("s") else w

        def has_phrase(title_words, phrase_words):
            """PHRASE_WORDS side by side in the title (plural s aside; two words in either order)."""
            want = [stem(w) for w in phrase_words]
            stems, n = [stem(w) for w in title_words], len(want)
            spans = {tuple(stems[i:i + n]) for i in range(len(stems) - n + 1)}
            return tuple(want) in spans or (n == 2 and tuple(reversed(want)) in spans)

        def rank(pair):
            title_words = re.findall(r"[a-z0-9]+", pair[1]["title"].lower())
            hit = sum(w in set(title_words) for w in set(words))
            return (not any(has_phrase(title_words, p.split()) for p in phrases), -hit,
                    len([w for w in title_words if w not in set(words)]), pair[0])
        ranked = sorted(enumerate(entries), key=rank)
        items, seen = [], set()
        for _, item in ranked:
            key = item["title"].casefold()
            if key not in seen:
                seen.add(key)
                items.append(item)
        return {"items": items[:limit], "source": "arXiv"}, cache, False, {"arXiv": as_of}

    def _worldbank_indicator(self, args, remaining):
        country = args["country"].upper()
        if not re.fullmatch(r"[A-Z]{2,3}", country):
            raise FallbackUnavailable("invalid_input", "Use an ISO 3166 alpha-2 or alpha-3 country code.")
        wanted = " ".join(args["indicator"].lower().replace("_", " ").split())
        code, label, unit = WB_ALIASES.get(wanted, (None, None, None))
        if code is None and re.fullmatch(r"[A-Za-z]{2,3}(\.[A-Za-z0-9]{1,8}){1,5}", args["indicator"].strip()):
            code = args["indicator"].strip().upper()
            unit = next((u for c, _, u in WB_ALIASES.values() if c == code), None)
        if code is None:
            raise FallbackUnavailable("invalid_input", "Unknown indicator. Use a common name such as population or "
                                                       "gdp, or a World Bank indicator code.")
        year = args.get("year")
        if year is not None and not 1960 <= year <= self.utc_now().year:
            raise FallbackUnavailable("invalid_input", "Use a year from 1960 to the current year.")

        def live(rem):
            if code == "CAPITAL":
                raw = self._get_json(f"https://api.worldbank.org/v2/country/{country}", rem, params={"format": "json"},
                                     limit=65536)
                row = (raw[1] or [None])[0] if isinstance(raw, list) and len(raw) > 1 and raw[1] else None
                if not row or not _text(row.get("capitalCity"), 200):
                    raise FallbackUnavailable("not_found", "No capital city is listed for this country code.")
                out = {"country": f"{_text(row.get('name'), 120)} ({row.get('id')})", "indicator": "Capital city",
                       "value": _text(row["capitalCity"], 200), "source": "World Bank (CC BY 4.0)"}
                return out, None
            # The API usually answers in 0.03-0.3 s but now and then one cached URL stalls for 15 s or more
            # while another form of the same question answers at once (11-14 measurements). So: ask the plain
            # path with a 1.4 s cap, and only on a timeout ask once more in the other form. Read-only GETs,
            # at most two per call, never after a 429.
            url = f"https://api.worldbank.org/v2/country/{country}/indicator/{quote(code, safe='.')}"
            recent = year is None or year > self.utc_now().year - 49
            first = {"format": "json", **({} if recent else {"date": str(year)})}
            second = {"format": "json", **({"date": str(year)} if year else {"mrnev": 1})}
            try:
                raw = self._get_json(url, lambda: min(1.5, rem()), params=first, limit=262144)
            except SourceError as exc:
                if exc.status is not None or rem() < 1.0 or second == first:
                    raise
                raw = self._get_json(url, rem, params=second, limit=262144)
            if not isinstance(raw, list) or len(raw) < 2 or not isinstance(raw[1], list):
                # The API answers an unknown country or indicator with a message object, not data.
                raise FallbackUnavailable("not_found", "The World Bank has no data for this country and indicator.")
            rows = [r for r in raw[1] if isinstance(r, dict) and isinstance(r.get("value"), (int, float))
                    and (r.get("indicator") or {}).get("id") == code and str(r.get("date", "")).isdigit()
                    and (year is None or int(r["date"]) == year)]
            rows.sort(key=lambda r: -int(r["date"]))
            if not rows:
                raise FallbackUnavailable("not_found", "No published value for this country, indicator and year.")
            r = rows[0]
            out = {"country": f"{_text((r.get('country') or {}).get('value'), 120)} ({_text(r.get('countryiso3code'), 3)})",
                   "indicator": f"{_text((r.get('indicator') or {}).get('value'), 160)} ({code})",
                   "year": int(r["date"]), "value": r["value"], "source": "World Bank WDI (CC BY 4.0)"}
            if unit:
                out["unit"] = unit
            return out, _text(raw[0].get("lastupdated"), 40) or None
        (out, as_of), cache = self._cached(("worldbank-indicator", country, code, year), TTL["worldbank-indicator"],
                                           live, remaining)
        return out, cache, False, {"World Bank": as_of or _now_iso(self.utc_now())}

    def _met_weather(self, args, remaining):
        lat, lon = args["latitude"], args["longitude"]
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise FallbackUnavailable("invalid_input", "Use a latitude from -90 to 90 and a longitude from -180 to 180.")
        key = (round(lat, 2), round(lon, 2))  # MET asks for at most 4 decimals; 0.01 degree is about 1 km
        now = self.clock()
        with self.lock:
            hit = self.weather.get(key)
        if hit and now < hit["expires"]:
            return hit["value"], {"status": "fresh_cache", "age_seconds": int(now - hit["at"])}, False, hit["as_of"]
        try:
            if remaining() < 0.5:
                raise SourceBusy("No time left for a live call.")
            response = get("https://api.met.no/weatherapi/locationforecast/2.0/compact", limiters=self.limiters,
                           http=self.http, params={"lat": f"{key[0]:.2f}", "lon": f"{key[1]:.2f}"},
                           seconds=max(0.1, remaining() - 0.1), limit=1024 * 1024, ok=(200, 304),
                           headers={"If-Modified-Since": hit["last_modified"]} if hit and hit["last_modified"] else None)
            expires = expires_in(response.headers.get("expires"), self.wall())
            if response.status_code == 304 and hit:
                value, as_of = hit["value"], hit["as_of"]
            else:
                value, as_of = met_forecast(json.loads(response.content), self.utc_now())
            entry = {"value": value, "as_of": as_of, "expires": self.clock() + expires,
                     "last_modified": response.headers.get("last-modified") or "", "at": self.clock()}
        except Exception as exc:
            if hit and now - hit["at"] <= MAX_AGE["met-weather"]:
                return hit["value"], {"status": "stale_cache", "age_seconds": int(now - hit["at"])}, False, hit["as_of"]
            code = failure_code(exc)
            raise FallbackUnavailable(code, failure_message(code, "MET Norway")) from exc
        with self.lock:
            self.weather[key] = entry
            self.weather.move_to_end(key)
            while len(self.weather) > 1024:
                self.weather.popitem(last=False)
        return value, {"status": "live", "age_seconds": 0}, False, as_of

    def _holiday_rows(self, place, year):
        """[(date, English title)] of one country's national public holidays, the place label, and freshness."""
        try:
            import holidays as lib
            from holidays import registry
        except ImportError as exc:
            raise FallbackUnavailable("source_unavailable", "Holiday rules are not installed on this server.") from exc
        place = " ".join((place or "").split())
        if not place:
            raise FallbackUnavailable("not_found", "National public holidays only: give a country.")
        code = holiday_country(place, registry.COUNTRIES)
        if not code:
            raise FallbackUnavailable("not_found", "National public holidays only: the place is not a supported country.")
        year = year or self.utc_now().year
        if not 1950 <= year <= self.utc_now().year + 5:
            raise FallbackUnavailable("invalid_input", "Use a year from 1950 to five years ahead.")
        base = lib.country_holidays(code, years=year)
        english = "en_US" in (getattr(base, "supported_languages", ()) or ())
        table = lib.country_holidays(code, years=year, language="en_US") if english else base
        rows = []
        for day, names in sorted(table.items()):
            for name in str(names).split("; "):
                name = _text(name, 300)
                # English names may keep accented proper names (Atatürk); only a non-English table is labeled.
                rows.append((day, name if english or name.isascii() else f"Public holiday (local name: {name})"))
        label = _text(f"{country_name(code, registry.COUNTRIES)} ({getattr(base, 'country', code)})", 200)
        version = getattr(lib, "__version__", "")
        released = HOLIDAYS_RELEASES.get(version)
        age = int(max(0, self.wall() - released)) if released else MAX_AGE["public-holidays"] + 1
        as_of = {f"holidays {version}": datetime.fromtimestamp(released, timezone.utc).strftime("%Y-%m-%d")
                 if released else None}
        return rows, label, version, year, {"status": "snapshot", "age_seconds": age}, as_of

    def _public_holidays(self, args, remaining):
        rows, label, version, _, cache, as_of = self._holiday_rows(args.get("place"), args.get("year"))
        month, limit = args.get("month"), args.get("limit", 20)
        words = [w for w in re.findall(r"[a-z0-9]+", (args.get("query") or "").lower())
                 if w not in STOPWORDS | {"holiday", "holidays", "public", "national", "day", "days"}]
        items = [{"title": f"{title} (national public holiday)", "date": day.isoformat(), "place": label}
                 for day, title in rows if (not month or day.month == month)
                 and (not words or any(w in title.lower() for w in words))]
        if not items:
            raise FallbackUnavailable("not_found", "No national public holiday matches; festivals, concerts and "
                                                   "other events are not covered.")
        out = {"items": items[:limit], "source": f"holidays {version} (MIT): national public holidays only"}
        return out, cache, len(items) > limit, as_of

    def _country_at(self, lat, lon) -> str:
        """The country grid's single answer for a point (PM 11-15 13:58), or FallbackUnavailable when the grid is not
        built, the point is at sea, near a border or in a disputed area (never one country there)."""
        from .country_grid import CountryGrid
        if self.country_grid is None:
            self.country_grid = CountryGrid(self.data_dir / "country-grid.bin")
        try:
            found = self.country_grid.lookup(lat, lon)
        except (OSError, ValueError) as exc:
            raise FallbackUnavailable("source_unavailable", "The country grid is not built on this server yet.") from exc
        if found["country"]:
            return found["country"]
        if found["disputed"]:
            raise FallbackUnavailable("not_found", "The point is in a disputed area (" + ", ".join(found["candidates"])
                                      + "); give the country code.")
        if found["candidates"]:
            raise FallbackUnavailable("not_found", "The point is within about 2 km of a border (" +
                                      ", ".join(found["candidates"]) + "); give the country code.")
        raise FallbackUnavailable("not_found", "The point is not in any country (at sea).")

    def _holiday_calendar(self, args, remaining):
        place = next((args.get(k) for k in ("country_code", "countryCode", "country") if args.get(k)), "")
        point = parse_point(str(place)) if isinstance(place, str) else None
        if point:   # an address hub gives coordinates only: the country comes from the country grid
            place = point[2] or self._country_at(point[0], point[1])
        year = args.get("year")
        if year is not None and not isinstance(year, int):
            raise FallbackUnavailable("invalid_input", "Use a year as a number.")
        rows, label, version, year, cache, as_of = self._holiday_rows(place, year)
        lines = "; ".join(f"{day.isoformat()} {title}" for day, title in rows)
        answer = (f"National public holidays in {label}, {year} (national public holidays only; regional holidays, "
                  f"festivals and events are not included): {lines}.")[:8000]
        out = {"answer": answer, "url": "https://github.com/vacanza/holidays",
               "source": f"holidays {version} (MIT): national public holidays only"}
        if point and self.country_grid is not None and not point[2]:
            header = self.country_grid.header
            as_of = {**(as_of if isinstance(as_of, dict) else {"holidays": as_of}),
                     "country grid built": header.get("built")}
            cache = {**cache, "age_seconds": max(int(cache.get("age_seconds") or 0), self._grid_age(header))}
        return out, cache, False, as_of

    def _sec_filings(self, args, remaining):
        """PM 11-15 12:55: identifiers first (CIK, then ticker), a name only when it matches one SEC filer exactly;
        a company with no SEC registration gets a normal answer that says so, not an error."""
        cik, matched = None, None
        raw_cik = str(args.get("cik") or "").strip()
        if raw_cik:
            if not re.fullmatch(r"(?:CIK)?0*[0-9]{1,10}", raw_cik, re.I):
                raise FallbackUnavailable("invalid_input", "Use a numeric SEC CIK.")
            cik, matched = int(re.sub(r"\D", "", raw_cik)), "CIK"
        if cik is None:
            index, by_ticker, list_cache = self._sec_index(remaining)
            ticker = str(args.get("ticker") or "").strip().upper()
            if ticker and re.fullmatch(r"[A-Z0-9.\-]{1,10}", ticker) and ticker in by_ticker:
                cik, matched = by_ticker[ticker], f"ticker {ticker}"
            for key in ("company", "query"):
                name = str(args.get(key) or "").strip()
                # the exact name, then the same name without its legal form ("Union Electric" = "UNION ELECTRIC CO",
                # ops gate 11-15); never the loose tier that also drops Holding or Group: no near-name guesses
                for tier, how in ((0, "exact company name"), (1, "company name without its legal form")):
                    if cik is not None or not name:
                        break
                    ciks = index[tier].get(name_keys(name)[tier]) or set()
                    if len(ciks) > 1:
                        raise FallbackUnavailable("not_found", "Several SEC companies share this name; use the ticker or CIK.")
                    if ciks:
                        cik, matched = next(iter(ciks)), how
            if cik is None:
                asked = ", ".join(f"{k} {str(args.get(k)).strip()[:120]}" for k in ("ticker", "company", "query")
                                  if str(args.get(k) or "").strip()) or "no identifier"
                out = {"answer": (f"No SEC EDGAR registration matches ({asked}): the company has no SEC filings "
                                  f"under a listed ticker, CIK or this exact name. Companies outside the U.S. "
                                  f"securities markets usually have none.")[:8000],
                       "url": "https://www.sec.gov/edgar/search/", "source": "SEC EDGAR (company ticker list)"}
                return out, list_cache, False, {"SEC EDGAR company ticker list": None}

        def live(rem):
            raw = self._get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", rem, limit=8 * 1024 * 1024)
            if int(raw.get("cik", -1)) != cik:
                raise ValueError("CIK mismatch")
            recent = (raw.get("filings") or {}).get("recent") or {}
            forms, dates = recent.get("form") or [], recent.get("filingDate") or []
            accessions, docs = recent.get("accessionNumber") or [], recent.get("primaryDocument") or []
            rows = []
            for i in range(min(len(forms), len(dates), len(accessions), 200)):
                rows.append((_text(dates[i], 10), _text(forms[i], 20), _text(accessions[i], 25),
                             _text(docs[i] if i < len(docs) else "", 120)))
            if not rows:
                raise FallbackUnavailable("not_found", "EDGAR lists no recent filings for this filer.")
            main = [r for r in rows if r[1] in ("10-K", "10-Q", "8-K", "20-F", "6-K", "40-F", "10-K/A", "10-Q/A")][:8]
            name = _text(raw.get("name"), 200)
            lines = "; ".join(f"{d} {f}" for d, f, _, _ in rows[:10])
            key = "; ".join(f"{d} {f} (accession {a})" for d, f, a, _ in main) or "none in the latest list"
            answer = (f"Matched SEC filer: {name} (SEC CIK {cik}). Recent EDGAR filings: {lines}. "
                      f"Periodic and current reports (10-K, 10-Q, 8-K and foreign equivalents): {key}.")
            facts = None
            facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
            try:   # PM 11-15 12:46: the summary facts of the latest annual report, from XBRL company facts
                facts = annual_facts(self._get_json(facts_url, rem, limit=40 * 1024 * 1024), facts_url)
            except (FallbackUnavailable, SourceError, ValueError):
                facts = None   # a filer without XBRL facts (404) or a slow facts file still gets its filing list
            if facts:
                answer += " " + facts
            out = {"answer": answer[:8000], "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}",
                   "source": "SEC EDGAR (submissions" + (" and XBRL company facts)" if facts else ")")}
            return out, rows[0][0] or None
        (out, as_of), cache = self._cached(("sec-filings", cik), TTL["sec-filings"], live, remaining)
        # how this request found the filer is not part of the cached answer (one filer, many ways to ask)
        out = {**out, "answer": out["answer"].replace(f"(SEC CIK {cik}).", f"(SEC CIK {cik}), by {matched}.", 1)[:8000]}
        return out, cache, False, {"SEC EDGAR (latest filing date)": as_of}

    def _software_incident(self, args, remaining):
        query = " ".join(args["query"].split())
        cve = query.upper() if CVE_ID.fullmatch(query.upper()) else None
        package_name = bool(PACKAGE.fullmatch(query))
        if not cve and not (package_name or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._+-]{1,99}", query)):
            raise FallbackUnavailable("invalid_input", "Use a CVE id, a package name or a program name.")

        def live(rem):
            if not cve and not package_name:
                return [], _now_iso(self.utc_now())  # a program name with spaces is not a package: NVD only
            params = {"cve_id": cve} if cve else {"affects": query}
            raw = self._get_json("https://api.github.com/advisories", rem, not_found=(), params={
                **params, "type": "reviewed", "per_page": 20, "sort": "published", "direction": "desc"})
            if not isinstance(raw, list):
                raise ValueError("unexpected advisory list")
            return raw[:20], _now_iso(self.utc_now())
        (rows, as_of), cache = self._cached(("software-incident", query.lower()), TTL["software-incident"], live, remaining)
        items, packages = [], {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("ghsa_id"), str) or row.get("withdrawn_at"):
                continue
            if cve:   # structured fields for the fix seat (workflow 11-15): every affected package and its first fix
                for v in row.get("vulnerabilities") or []:
                    pkg = v.get("package") if isinstance(v, dict) else None
                    if isinstance(pkg, dict) and isinstance(pkg.get("name"), str):
                        # one entry per patched branch (log4j-core 2.15.0 and 2.12.2 alike); a package with no
                        # patched version keeps one bare entry, dropped below once a patched branch is known
                        patched = v.get("first_patched_version")
                        patched = _text(patched, 64) if isinstance(patched, str) else None
                        key = (str(pkg.get("ecosystem") or ""), pkg["name"], patched)
                        entry = {"ecosystem": _text(key[0], 40), "name": _text(key[1], 214)}
                        if patched:
                            entry["first_patched_version"] = patched
                        packages.setdefault(key, entry)
            title = _text(f"{row['ghsa_id']}: {row.get('summary') or ''}", 400)
            fixes = [f"{v['package'].get('name')}@{v['first_patched_version']}" for v in row.get("vulnerabilities") or []
                     if isinstance(v, dict) and isinstance(v.get("package"), dict) and isinstance(v.get("first_patched_version"), str)
                     and (cve or str(v["package"].get("name", "")).lower() == query.lower())]
            item = {"title": title}
            if fixes:
                # A fixed version is data to read, never an instruction to run (contract rule).
                item["fixed_version"] = _text(fixes[0].rsplit("@", 1)[1], 64)
                item["title"] = _text(f"{title} (patched in {', '.join(dict.fromkeys(fixes))[:90]})", 500)
            if isinstance(row.get("html_url"), str) and row["html_url"].startswith("https://github.com/advisories/"):
                item["url"] = row["html_url"]
            if _text(row.get("published_at"), 40):
                item["published"] = _text(row.get("published_at"), 40)
            items.append(item)
        source = "GitHub Advisory Database (CC BY 4.0)"
        if cve and not items:
            # Not an open-source package advisory: give the NVD record's references instead.
            try:
                body, status, _ = self.snapshot.lookup(cve)
            except Exception:
                body, status = None, None
            if body and status != "Rejected":
                patch = next((r for r in body.get("references") or []), None)
                item = {"title": _text(f"{cve}: {body.get('description', '')}", 500)}
                if patch:
                    item["url"] = patch
                if body.get("published"):
                    item["published"] = body["published"]
                items, source = [item], "NVD (references; no reviewed package advisory)"
        if not cve:
            # Program names (PM 11-14): NVD CPE products give the CVEs and the first fixed versions. They come
            # before package advisories, so "openssl" answers about OpenSSL before a same-named library package.
            try:
                found = self.snapshot.products(query, limit=10)
            except Exception:
                found = []
            program = []
            for row in found:
                rec = row["record"]
                item = {"title": _text(f"{row['cve_id']} ({row['vendor']}:{row['product']}): {rec.get('description', '')}", 500)}
                if row["fixed"]:
                    item["fixed_version"] = _text(row["fixed"].split(", ")[0], 64)
                if rec.get("references"):
                    item["url"] = rec["references"][0]
                if rec.get("published"):
                    item["published"] = rec["published"]
                program.append(item)
            if program:
                nvd = "NVD (CPE product match; fixed version = the CPE versionEndExcluding bound)"
                source = nvd + ("; then GitHub Advisory Database (CC BY 4.0) package advisories" if items else "")
                items = program + items
        if not items:
            raise FallbackUnavailable("not_found", "No reviewed advisory or NVD product record for this name; use a CVE id, "
                                                   "an exact package name or the program's product name.")
        out = {"items": items[:20], "source": source}
        if cve:
            out["cve_id"] = cve
            patched_names = {k[:2] for k in packages if k[2]}
            out["packages"] = [e for k, e in packages.items() if k[2] or k[:2] not in patched_names][:20]
        return out, cache, False, {"GitHub Advisory Database": as_of}

    def _scorecard(self, args, remaining):
        repo = next((str(args[k]) for k in ("repo", "repository") if args.get(k)), "")
        m = re.fullmatch(r"(?:https?://)?(github\.com|gitlab\.com)/([\w.-]+)/([\w.-]+?)(?:\.git)?/?", repo.strip())
        if not m and args.get("package"):
            ecosystem = {"npm": "npm", "pypi": "PyPI"}.get(str(args.get("ecosystem") or "npm").lower())
            if ecosystem:
                found = self.execute("package-registry", {"package": str(args["package"]), "ecosystem": ecosystem})
                m = re.fullmatch(r"https://(github\.com|gitlab\.com)/([\w.-]+)/([\w.-]+)",
                                 found["result"].get("repository") or "")
        if not m:
            raise FallbackUnavailable("invalid_input", "Use a github.com/owner/repo, or an npm or PyPI package with a "
                                                       "listed source repository.")
        project = f"{m[1]}/{m[2]}/{m[3]}"

        def live(rem):
            raw = self._get_json("https://api.scorecard.dev/projects/" + project, rem, limit=1024 * 1024)
            score = raw.get("score")
            if not isinstance(score, (int, float)) or not 0 <= score <= 10:
                raise ValueError("no score")
            checks = sorted((c for c in raw.get("checks") or [] if isinstance(c, dict) and isinstance(c.get("score"), int)
                             and c["score"] >= 0), key=lambda c: c["score"])
            low = ", ".join(f"{_text(c.get('name'), 40)} {c['score']}" for c in checks[:5])
            answer = (f"OpenSSF Scorecard for {project}: aggregate score {score}/10 (scored {raw.get('date')}). "
                      f"Lowest checks: {low or 'none listed'}.")
            out = {"answer": answer[:8000], "url": f"https://scorecard.dev/viewer/?uri={project}",
                   "source": "OpenSSF Scorecard (CDLA-Permissive-2.0)"}
            return out, _text(raw.get("date"), 40) or None
        (out, as_of), cache = self._cached(("scorecard", project.lower()), TTL["scorecard"], live, remaining)
        return out, cache, False, {"OpenSSF Scorecard": as_of}

    def _site_get(self, url, rem, domain):
        """GET one public file; follow at most two redirects within the same site (the domain or its subdomains,
        e.g. wikipedia.org -> www.wikipedia.org -> en.wikipedia.org). Every hop is checked as a public address."""
        from urllib.parse import urljoin
        root = domain[4:] if domain.startswith("www.") else domain

        def same_site(host):
            host = (host or "").lower()
            return host == root or host.endswith("." + root)
        for _ in range(3):
            try:
                response = get(url, limiters=self.limiters, http=self.http, seconds=max(0.1, min(2.0, rem() - 0.1)),
                               limit=256 * 1024, accept="text/plain, application/xml, text/xml, */*",
                               ok=tuple(range(200, 600)), any_site=True)
            except (SourceBusy, SourceError) as exc:
                return None, "could not read: " + str(exc)[:80]
            if response.status_code in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get("location") or "")
                if urlsplit(target).scheme != "https" or not same_site(urlsplit(target).hostname):
                    return None, "redirects off the site"
                url = target
                continue
            if response.status_code != 200:
                return None, f"HTTP {response.status_code}"
            return response.text, None
        return None, "too many redirects"

    def _site_readiness(self, args, remaining):
        from urllib.robotparser import RobotFileParser
        from .catalog import USER_AGENT
        from .net import site_host
        domain = args["domain"].strip().lower().rstrip(".")
        domain = re.sub(r"^https?://", "", domain).split("/")[0]
        if not site_host(domain):
            raise FallbackUnavailable("invalid_input", "Use a public domain name such as example.com.")

        def live(rem):
            base = f"https://{domain}"
            signals = {}
            robots, why = self._site_get(base + "/robots.txt", rem, domain)
            signals["robots_txt"] = {"present": robots is not None, **({"note": why} if why else {})}
            parser = RobotFileParser()
            parser.parse((robots or "").splitlines())
            if robots is not None:
                bots = {}
                for bot in AI_CRAWLERS:
                    named = re.search(r"(?im)^\s*user-agent:\s*" + re.escape(bot) + r"\s*$", robots) is not None
                    bots[bot] = ("allowed" if parser.can_fetch(bot, base + "/") else "blocked") + \
                        ("" if named else " (by the * rule)")
                signals["ai_crawlers"] = bots
                maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
                signals["robots_txt"]["sitemaps_declared"] = len(maps)
            for name, path in (("llms_txt", "/llms.txt"), ("sitemap_xml", "/sitemap.xml")):
                if robots is not None and not parser.can_fetch(USER_AGENT, base + path):
                    signals[name] = {"present": None, "note": "not read: robots.txt disallows it for our user agent"}
                    continue
                if rem() < 0.6:
                    signals[name] = {"present": None, "note": "not read: time budget"}
                    continue
                body, why = self._site_get(base + path, rem, domain)
                # absent only when the site says so (404/410); a refused budget, a time-out or a 5xx is unknown
                gone = bool(why) and re.match(r"HTTP 4(04|10)\b", why) is not None
                entry = {"present": True if body is not None else (False if gone else None),
                         **({"note": why if gone else "not read: " + why} if why else {})}
                if body is not None and name == "llms_txt":
                    title = next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.startswith("#")), "")
                    entry.update(bytes=len(body.encode("utf-8")), title=_text(title, 120),
                                 links=len(re.findall(r"\]\(https?://", body)))
                if body is not None and name == "sitemap_xml":
                    entry.update(kind="index" if "<sitemapindex" in body[:2000] else
                                 "urlset" if "<urlset" in body[:2000] else "unrecognized",
                                 entries_in_first_256kb=body.count("<loc>"))
                    entry["present"] = entry["kind"] != "unrecognized"
                signals[name] = entry
            if all(str((signals.get(k) or {}).get("note", "")).startswith("could not read")
                   for k in ("robots_txt", "llms_txt", "sitemap_xml")):
                raise SourceError("The website did not answer.")
            bots = signals.get("ai_crawlers") or {}
            open_share = (sum(v.startswith("allowed") for v in bots.values()) / len(bots)) if bots else 1.0
            score = round(20 * bool(signals["robots_txt"]["present"]) + 30 * open_share
                          + 30 * bool((signals.get("llms_txt") or {}).get("present"))
                          + 20 * bool((signals.get("sitemap_xml") or {}).get("present")), 1)
            out = {"domain": domain, "signals": signals, "score": score,
                   "source": f"{domain} public files (robots.txt, llms.txt, sitemap.xml)"}
            return out, _now_iso(self.utc_now())
        (out, as_of), cache = self._cached(("site-readiness", domain), TTL["site-readiness"], live, remaining)
        return out, cache, False, {domain: as_of}

    def _wiki_grounding(self, args, remaining):
        question = " ".join(args["question"].split())
        words = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if w not in STOPWORDS | QUESTION_WORDS]
        if not words:
            raise FallbackUnavailable("invalid_input", "Ask a factual question with some content words.")

        subject = subject_title(question)

        def live(rem):
            # 11-16 gate (holdout-r3 28/30): search ranked side articles ("Intrusion detection system" for "Anomaly
            # detection") above the subject's own article. The article titled exactly as the subject (after
            # redirects, never a disambiguation page) is read first and quoted first.
            exact = None
            if subject:
                found = self._get_json("https://en.wikipedia.org/w/api.php", rem, limit=256 * 1024, params={
                    "action": "query", "titles": subject, "prop": "extracts|info|pageprops", "exintro": 1,
                    "explaintext": 1, "inprop": "url", "ppprop": "disambiguation", "redirects": 1,
                    "format": "json", "formatversion": 2, "maxlag": 5})
                exact = next((p for p in (found.get("query") or {}).get("pages") or []
                              if isinstance(p, dict) and not p.get("missing") and p.get("extract")
                              and "disambiguation" not in (p.get("pageprops") or {})
                              and str(p.get("fullurl", "")).startswith("https://en.wikipedia.org/wiki/")), None)
            raw = self._get_json("https://en.wikipedia.org/w/api.php", rem, limit=512 * 1024, params={
                "action": "query", "generator": "search", "gsrsearch": search_terms(question), "gsrlimit": 3,
                "prop": "extracts|info", "exintro": 1, "explaintext": 1, "inprop": "url", "redirects": 1,
                "format": "json", "formatversion": 2, "maxlag": 5})
            pages = sorted((p for p in (raw.get("query") or {}).get("pages") or []
                            if isinstance(p, dict) and p.get("extract") and str(p.get("fullurl", "")).startswith(
                                "https://en.wikipedia.org/wiki/")), key=lambda p: p.get("index", 99))
            if exact is not None:
                pages = [dict(exact, exact=True)] + [p for p in pages if p.get("pageid") != exact.get("pageid")][:2]
            if not pages:
                raise FallbackUnavailable("not_found", "Wikipedia has no article matching this question.")
            return pages, max((_text(p.get("touched"), 40) for p in pages), default=None)
        (pages, as_of), cache = self._cached(("wiki-grounding", " ".join(words)), TTL["wiki-grounding"], live, remaining)
        cues = [re.compile(pattern, re.I) for trigger, pattern in ANSWER_CUES if re.search(trigger, question, re.I)]
        scored = []
        for rank, page in enumerate(pages):
            title = str(page.get("title", ""))
            title_words = set(re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", "", title).lower())) - STOPWORDS
            # The article about the asked subject itself beats a derived one ("... (2005 film)").
            topic = (1.5 if title_words and title_words <= set(words) else 0) - (1.0 if "(" in title else 0)
            for n, sentence in enumerate(re.split(r"(?<=[.!?])\s+", " ".join(page["extract"].split()))[:20]):
                hits = len(set(words) & set(re.findall(r"[a-z0-9]+", sentence.lower())))
                # A sentence that carries the kind of fact asked for (a maker, a year, a measure) counts double.
                bonus = 2 * sum(bool(c.search(sentence)) for c in cues)
                if hits:
                    scored.append((-(hits + bonus + topic - 0.5 * rank), rank, n, sentence, page))
        if not scored:
            raise FallbackUnavailable("not_found", "No Wikipedia lead sentence matches this question.")
        scored.sort(key=lambda x: x[:3])
        best = scored[:3]
        own = [x for x in scored if x[4].get("exact")]
        if own and not any(x[4].get("exact") for x in best):
            best = [min(own, key=lambda x: x[2])] + best[:2]       # the subject's own article is always quoted
        elif own:
            best = sorted(best, key=lambda x: not x[4].get("exact"))   # and quoted first
        quotes = " ".join(f"{s[3]} [{s[4]['title']}]" for s in best)
        sources = list(dict.fromkeys(s[4]["fullurl"] for s in best))
        answer = (f"From Wikipedia (quoted, not generated): {quotes}")[:4000]
        return {"answer": answer, "sources": sources, "source": "Wikipedia (CC BY-SA 4.0, Wikipedia contributors)"}, \
            cache, False, {"Wikipedia": as_of}

    def _ecb_fx(self, args, remaining):
        base, quote_ccy = args["from"], args["to"]

        def live(rem):
            response = get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", limiters=self.limiters,
                           http=self.http, seconds=max(0.1, rem() - 0.1), limit=65536, accept="application/xml, text/xml")
            return ecb_rates(response.content), _now_iso(self.utc_now())
        ((day, rates), _), cache = self._cached(("ecb-fx",), TTL["ecb-fx"], live, remaining)
        rates = dict(rates, EUR=1.0)
        missing = [c for c in (base, quote_ccy) if c not in rates]
        if missing:
            raise FallbackUnavailable("not_found", "The ECB publishes no reference rate for " + ", ".join(missing) + ".")
        published = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        if (self.utc_now() - published).days > 5:  # longer than any TARGET holiday gap: the copy is stale
            raise FallbackUnavailable("stale", f"The newest ECB reference rates are from {day}.")
        rate = rates[quote_ccy] / rates[base]
        out = {"from": base, "to": quote_ccy, "rate": float(f"{rate:.6g}"), "date": day,
               "source": "ECB euro foreign exchange reference rates" + ("" if "EUR" in (base, quote_ccy) else
                                                                        " (crossed through EUR by AgentValCon)")
                         + "; for information only, not for transactions"}   # ECB conditions (11-16 terms check)
        return out, cache, False, {"ECB": day}

    def _usgs_quakes(self, args, remaining):
        """earthquake.feed.v1 from the USGS real-time GeoJSON feeds (USGS asks automated applications to use them).
        With lat/lon (or near "lat,lon") and radius_km the feed is filtered by distance on our side, so a point
        query costs no extra request (PM 11-15 13:53, workflow 0aac4347)."""
        import math
        floor = next((args[k] for k in ("min_magnitude", "minmagnitude", "magnitude") if args.get(k) is not None), 4.5)
        if not isinstance(floor, (int, float)) or not 0 <= floor <= 10:
            raise FallbackUnavailable("invalid_input", "Use a minimum magnitude from 0 to 10.")
        floor = max(4.5, float(floor))  # the feeds start at 4.5; a lower minimum is answered from 4.5
        lat, lon = args.get("lat"), args.get("lon")
        if args.get("near") and lat is None and lon is None:
            point = parse_point(args["near"])
            if not point:
                raise FallbackUnavailable("invalid_input", "near is \"lat,lon\".")
            lat, lon = point[0], point[1]
        if (lat is None) != (lon is None):
            raise FallbackUnavailable("invalid_input", "Give both lat and lon.")
        if lat is not None and not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                                    and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise FallbackUnavailable("invalid_input", "lat is -90..90 and lon -180..180.")
        radius = float(args.get("radius_km") or 1000)
        if not 1 <= radius <= 2000:
            raise FallbackUnavailable("invalid_input", "radius_km is 1 to 2000.")
        days = args.get("days") or {"hour": 1 / 24, "day": 1, "week": 7, "month": 30}.get(args.get("period") or "", None)
        if days is not None and not (isinstance(days, (int, float)) and 0 < days <= 30):
            raise FallbackUnavailable("invalid_input", "days is 1 to 30.")
        limit = int(args.get("limit") or 15)

        def feed(period):
            def live(rem):
                raw = self._get_json(f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_{period}.geojson",
                                     rem, limit=4 * 1024 * 1024)
                rows = []
                for f in raw.get("features") or []:
                    p = (f or {}).get("properties") or {}
                    xyz = ((f or {}).get("geometry") or {}).get("coordinates") or []
                    if isinstance(p.get("mag"), (int, float)) and isinstance(p.get("time"), int):
                        where = (float(xyz[1]), float(xyz[0])) if len(xyz) >= 2 and all(
                            isinstance(v, (int, float)) for v in xyz[:2]) else None
                        rows.append((float(p["mag"]), p["time"], _text(p.get("place"), 160), bool(p.get("tsunami")),
                                     _text(p.get("url"), 300), where))
                generated = (raw.get("metadata") or {}).get("generated")
                when = datetime.fromtimestamp(generated / 1000, timezone.utc) if isinstance(generated, int) else self.utc_now()
                return rows, _now_iso(when)
            return self._cached(("usgs-quakes", period), TTL["usgs-quakes"], live, remaining)

        def km(a, b):
            p1, p2 = math.radians(a[0]), math.radians(b[0])
            h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
            return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))
        now_ms = self.utc_now().timestamp() * 1000

        def pick(rows, span_days):
            out = []
            for r in rows:
                if r[0] < floor or (span_days is not None and now_ms - r[1] > span_days * 86400000):
                    continue
                if lat is not None:
                    if r[5] is None:
                        continue
                    d = km((lat, lon), r[5])
                    if d > radius:
                        continue
                    r = r[:6] + (d,)
                out.append(r)
            return out
        if days is not None:
            (rows, as_of), cache = feed("week" if days <= 7 else "month")
            period = f"past {days * 24:g} hours" if days < 1 else f"past {days:g} day{'s' if days != 1 else ''}"
            hits = pick(rows, days)
        else:
            (rows, as_of), cache = feed("week")
            period, hits = "past 7 days", pick(rows, None)
            if not hits and remaining() > 1.0:
                (rows, as_of), cache = feed("month")
                period, hits = "past 30 days", pick(rows, None)
        hits.sort(key=lambda r: -r[1])
        area = f" within {radius:g} km of {lat:.4f},{lon:.4f}" if lat is not None else ""
        if not hits:
            answer = f"No earthquake of magnitude {floor:g} or more{area} in the USGS feed for the {period}."
        else:
            lines = "; ".join(
                f"M{r[0]:.1f} {datetime.fromtimestamp(r[1] / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC, {r[2]}"
                + (f", {r[6]:.0f} km away" if len(r) > 6 else "")
                + (f", lat {r[5][0]:.3f} lon {r[5][1]:.3f}" if r[5] else "")
                + (" (tsunami flag)" if r[3] else "") for r in hits[:limit])
            answer = (f"{len(hits)} earthquake{'s' if len(hits) != 1 else ''} of magnitude {floor:g} or more{area} "
                      f"in the {period} (USGS, newest first): {lines}.")
        out = {"answer": answer[:8000], "url": "https://earthquake.usgs.gov/earthquakes/map/",
               "source": "USGS Earthquake Hazards Program (U.S. Public Domain)"}
        return out, cache, False, {"USGS feed generated": as_of}

    def _grid_age(self, header: dict) -> int:
        """Seconds since a prebuilt grid was made (its header's "built"), 0 when it does not say."""
        try:
            built = datetime.strptime(str(header.get("built")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return 0
        return max(0, int(self.wall() - built.timestamp()))

    def _zone_at(self, lat, lon, country=None):
        """The time-zone grid's answer for a point (PM 11-15 13:52): {"zone", "candidates", "boundary", ...}."""
        from .tz_grid import TzGrid
        if self.tz_grid is None:
            self.tz_grid = TzGrid(self.data_dir / "tz-grid.bin")
        try:
            return self.tz_grid.lookup(lat, lon, country)
        except (OSError, ValueError) as exc:
            raise FallbackUnavailable("source_unavailable", "The time-zone grid is not built on this server yet.") from exc

    def _tz_time(self, args, remaining):
        import zoneinfo
        wanted = next((str(args[k]).strip() for k in ("timezone", "tz", "city", "location") if args.get(k)), "")
        point = parse_point(wanted)
        if point:
            return self._tz_time_at(*point)
        zone = tz_zone(wanted)
        if not zone:
            raise FallbackUnavailable("not_found", "Use an IANA time zone (Region/City) or a city that names a zone.")
        now = self.utc_now().astimezone(zoneinfo.ZoneInfo(zone))
        offset = now.strftime("%z")
        version = tz_version()
        answer = (f"Local time in {zone}: {now.strftime('%Y-%m-%d %H:%M:%S')} {now.tzname()} "
                  f"(UTC{offset[:3]}:{offset[3:]}). Daylight saving time is {'in effect' if now.dst() else 'not in effect'}.")
        out = {"answer": answer, "url": "https://www.iana.org/time-zones",
               "source": f"IANA Time Zone Database {version or '(version unknown)'} (public domain)"}
        return out, {"status": "snapshot", "age_seconds": 0}, False, {"IANA tz database": version}

    def _tz_time_at(self, lat, lon, country):
        import zoneinfo
        found = self._zone_at(lat, lon, country)
        version = tz_version()

        def clock(zone):
            now = self.utc_now().astimezone(zoneinfo.ZoneInfo(zone))
            offset = now.strftime("%z")
            return (f"{now.strftime('%Y-%m-%d %H:%M:%S')} {now.tzname()} (UTC{offset[:3]}:{offset[3:]}), daylight "
                    f"saving time {'in effect' if now.dst() else 'not in effect'}")
        where = f"{lat:.4f},{lon:.4f}"
        usable = [z for z in found["candidates"] if tz_zone(z) == z]
        if found["zone"] and tz_zone(found["zone"]) == found["zone"]:
            note = (" The point is near a time zone boundary; the country code " + country + " chose the zone."
                    if found["narrowed_by_country"] else "")
            answer = f"Time zone at {where}: {found['zone']}. Local time in {found['zone']}: {clock(found['zone'])}.{note}"
        elif usable:
            answer = (f"The point {where} is near a time zone boundary (within about 2 km); candidate zones: "
                      + "; ".join(f"{z}: {clock(z)}" for z in usable[:4]) + ". Give a country code or an exact zone "
                      "to choose one.")
        else:
            raise FallbackUnavailable("not_found", "No IANA time zone is known for this point.")
        out = {"answer": answer[:8000], "url": "https://github.com/evansiroky/timezone-boundary-builder",
               "source": f"IANA Time Zone Database {version or '(version unknown)'} (public domain); time zone "
                         f"boundaries: timezone-boundary-builder, ODbL 1.0, OpenStreetMap contributors"}
        header = self.tz_grid.header if self.tz_grid else {}
        # the grid's build date is the data date: an old grid shows its age and turns stale past MAX_AGE (PM 14:57)
        return out, {"status": "snapshot", "age_seconds": self._grid_age(header)}, False, {
            "IANA tz database": version, "time zone boundaries": header.get("boundary_data"),
            "time zone grid built": header.get("built")}

    def _airport_lookup(self, args, remaining):
        from .airports import AirportIndex
        if self.airports is None:
            self.airports = AirportIndex(self.data_dir / "airports.json")
        data = self.airports.data()
        if not data:
            raise FallbackUnavailable("source_unavailable", "The airport index is not built on this server yet.")
        index = data["airports"]
        wanted = next((str(args[k]).strip() for k in ("code", "iata", "iata_code", "query") if args.get(k)), "")
        if not wanted or len(wanted) > 80:
            raise FallbackUnavailable("invalid_input", "Use an IATA or ICAO code or part of an airport name.")
        rows = [index[wanted.upper()]] if wanted.upper() in index else []
        if not rows and len(wanted) >= 4:
            needle = wanted.lower()
            seen, rows = set(), []
            for rec in index.values():
                if needle in rec["name"].lower() and rec["ident"] not in seen:
                    seen.add(rec["ident"])
                    rows.append(rec)
                    if len(rows) == 5:
                        break
        if not rows:
            raise FallbackUnavailable("not_found", "No airport with this code or name in the OurAirports index.")
        parts = []
        for r in rows:
            codes = ", ".join(c for c in (f"IATA {r['iata_code']}" if r["iata_code"] else "",
                                         f"ICAO {r['icao_code']}" if r["icao_code"] else "") if c)
            # the location hub reads "country code XX" and "time zone Region/City" from these fixed phrases
            zone_text = self._airport_zone(r)
            parts.append(f"{r['name']} ({codes}): {r['municipality'] or 'city not listed'}, country code "
                         f"{r['iso_country']} ({r['iso_region']}), {r['type'].replace('_', ' ')}, lat {r['latitude_deg']} lon "
                         f"{r['longitude_deg']}, elevation {r['elevation_ft'] or '?'} ft, scheduled service "
                         f"{r['scheduled_service'] or 'unknown'}{zone_text}")
        out = {"answer": "; ".join(parts)[:8000], "url": "https://ourairports.com/airports/" + rows[0]["ident"] + "/",
               "source": "OurAirports (public domain)"}
        age = int(max(0, self.wall() - float(data.get("fetched_at") or 0)))
        as_of = {"OurAirports": data.get("source_last_modified") or None}
        if self.tz_grid is not None and any(", time zone " in p for p in parts):
            as_of["time zone grid built"] = self.tz_grid.header.get("built")
        return out, {"status": "snapshot", "age_seconds": age}, False, as_of

    def _airport_zone(self, rec) -> str:
        """", time zone Region/City" from the grid with the airport's country; near a boundary without one zone,
        ", time zone near a boundary: A or B"; nothing when the grid is not built (the lookup still answers)."""
        try:
            found = self._zone_at(float(rec["latitude_deg"]), float(rec["longitude_deg"]), rec.get("iso_country") or None)
        except (FallbackUnavailable, KeyError, TypeError, ValueError):
            return ""
        if found["zone"]:
            return f", time zone {found['zone']}"
        return ", time zone near a boundary: " + " or ".join(found["candidates"][:4])

    def _sun_times(self, args, remaining):
        """sun.times.v1 (workflow 11-16, weather-outdoor-brief): computed by fallback_agents.sun, no outside call.
        Coordinates come as latitude/longitude or a "lat,lon" location; a place name is not geocoded here."""
        from .sun import sun_times
        lat, lon = args.get("latitude"), args.get("longitude")
        if (lat is None or lon is None) and args.get("location"):
            m = re.fullmatch(r"\s*([-+]?\d{1,2}(?:\.\d+)?)\s*,\s*([-+]?\d{1,3}(?:\.\d+)?)\s*", str(args["location"]))
            if m:
                lat, lon = float(m.group(1)), float(m.group(2))
        if lat is None or lon is None:
            raise FallbackUnavailable("invalid_input", "Give latitude and longitude (a place name is not looked up here).")
        import zoneinfo
        try:
            lat, lon = float(lat), float(lon)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("coordinate out of range")
        except (TypeError, ValueError) as exc:
            raise FallbackUnavailable("invalid_input", "Use valid coordinates.") from exc
        # workflow 11-16: times in the place's own time zone (the offline grid tz-time uses); the date is that zone's
        # calendar date. Where the grid gives no single zone (a border cell) or is not built, times stay in UTC.
        zone = None
        try:
            zone = self._zone_at(lat, lon).get("zone") or None
        except FallbackUnavailable:
            zone = None
        tz = zoneinfo.ZoneInfo(zone) if zone else timezone.utc
        try:
            day = date.fromisoformat(args["date"]) if args.get("date") else self.utc_now().astimezone(tz).date()
            out = sun_times(lat, lon, day)
        except ValueError as exc:
            raise FallbackUnavailable("invalid_input", "Use a valid date (YYYY-MM-DD) and coordinates.") from exc

        def local(t):
            at = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(tz)
            return at.isoformat() if zone else t

        def said(t):
            at = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(tz)
            return at.strftime("%H:%M") + (f" {at.tzname()}" if zone else " UTC")
        state = out["state"]
        polar = "none" if state == "normal" else state
        where = f"{lat:.4f},{lon:.4f}" + (f" ({zone})" if zone else "")
        if state == "normal":
            answer = (f"On {day.isoformat()} at {where}: sunrise {said(out['sunrise'])}, sunset {said(out['sunset'])}, "
                      f"day length {out['day_length_minutes']} minutes.")
        else:
            answer = (f"On {day.isoformat()} at {where} the sun "
                      f"{'stays up all day (no sunset)' if state == 'always_up' else 'stays down all day (no sunrise)'}.")
        if not zone:
            answer += " Times in UTC (time zone not certain)."
        result = {"answer": answer, "url": "https://gml.noaa.gov/grad/solcalc/calcdetails.html",
                  "source": "Computed with the NOAA solar equations (public domain); time zone from the IANA database",
                  "date": day.isoformat(), "timezone": zone or "UTC", "day_length_minutes": out["day_length_minutes"],
                  "polar": polar}
        if state == "normal":
            result.update(sunrise=local(out["sunrise"]), sunset=local(out["sunset"]))
        as_of = {"NOAA solar equations": None}
        if zone and self.tz_grid is not None:
            as_of["time zone grid built"] = self.tz_grid.header.get("built")
        return result, {"status": "computed", "age_seconds": 0}, False, as_of

    def _site_reachability(self, args, remaining):
        """site.reachability.v1 (workflow 11-16, website-trust-brief v2): one GET through fallback_agents.reach."""
        from .net import site_host
        from .reach import reach
        raw = next((str(args[k]) for k in ("url", "domain") if args.get(k)), "")
        domain = re.sub(r"^https?://", "", raw.strip().lower()).split("/")[0].split(":")[0].rstrip(".")
        if not site_host(domain):
            raise FallbackUnavailable("invalid_input", "Use a public domain name such as example.com.")
        url = raw.strip() if raw.strip().startswith("https://") else f"https://{domain}/"
        out = reach(url, limiters=self.limiters, http=self.http, seconds=max(0.5, remaining() - 0.2), clock=self.clock)
        checked = _now_iso(self.utc_now())
        if out["reachable"]:
            answer = f"{domain} answered HTTP {out['status']} at {checked}"
        elif out["status"]:
            answer = f"{domain} answered HTTP {out['status']} at {checked} (not reachable as a working page)"
        else:
            answer = f"{domain} is unreachable at {checked}: {out['note'] or 'no answer'}"
        if out["redirects"]:
            answer += f", after {out['redirects']} redirect(s) to {out['final_url']}"
        result = {"answer": answer + ".", "url": url, "source": "One HTTPS GET from AgentValCon's server",
                  "domain": domain, "reachable": out["reachable"], "https": out["https"],
                  "redirects": min(out["redirects"], 10), "elapsed_ms": out["elapsed_ms"], "checked_at": checked}
        if out["status"]:
            result["status"] = out["status"]
        if out["final_url"].startswith("https://"):
            result["final_url"] = out["final_url"]
        return result, {"status": "live", "age_seconds": 0}, False, {"the website": checked}

    def _tls_certificate(self, args, remaining):
        """tls.certificate.v1 (workflow 11-15 website-trust-brief v2). crt.sh did not answer in 30 s, so the site's own
        certificate is read in a TLS handshake: every resolved address must be public, the connection goes to that
        checked address (no second lookup), port 443, SNI the domain, nothing sent after the handshake."""
        import ipaddress
        import socket
        import ssl
        from .net import site_host
        raw = next((str(args[k]) for k in ("domain", "host", "hostname", "url") if args.get(k)), "")
        domain = re.sub(r"^https?://", "", raw.strip().lower()).split("/")[0].split(":")[0].rstrip(".")
        if not site_host(domain):
            raise FallbackUnavailable("invalid_input", "Use a public domain name such as example.com.")

        def live(rem):
            try:
                infos = self.resolve(domain)
            except OSError as exc:
                raise FallbackUnavailable("not_found", "The domain does not resolve.") from exc
            addrs = sorted({i[4][0] for i in infos})
            if not addrs or not all(ipaddress.ip_address(a).is_global for a in addrs):
                raise FallbackUnavailable("invalid_input", "The domain does not point only to public addresses.")
            from .net import _BUDGET_SYSTEM
            system = _BUDGET_SYSTEM.get()
            if system:   # test runs we start count the handshake in the shared per-domain ledger, like net.get
                from ..provider_budget import reserve
                allowed, why = reserve(f"https://{domain}/", system)
                if not allowed:
                    raise SourceBusy(f"Shared test budget refused the call ({why}).")
            context = ssl.create_default_context()
            facts = {"domain": domain}
            try:
                with self.connect((addrs[0], 443), max(0.5, min(3.0, rem() - 0.2))) as sock:
                    with context.wrap_socket(sock, server_hostname=domain) as tls:
                        cert = tls.getpeercert()
                facts["valid"] = True
            except ssl.SSLCertVerificationError as exc:
                facts.update(valid=False, reason=_text(getattr(exc, "verify_message", "") or str(exc), 160))
                cert = None
            except (OSError, ssl.SSLError) as exc:
                raise SourceError("The website did not complete a TLS handshake.") from exc
            if cert:
                issuer = dict(x[0] for x in cert.get("issuer") or [] if x)
                facts["issuer"] = _text(issuer.get("organizationName") or issuer.get("commonName"), 300)
                end = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), timezone.utc)
                facts["not_after"] = end.strftime("%Y-%m-%d")
            return facts, _now_iso(self.utc_now())
        (facts, as_of), cache = self._cached(("tls-certificate", domain), TTL["tls-certificate"], live, remaining)
        out = {"domain": facts["domain"], "valid": facts["valid"], "url": f"https://{domain}/",
               "source": "TLS handshake with the website (port 443)"}
        if facts["valid"]:
            days = (datetime.strptime(facts["not_after"], "%Y-%m-%d").replace(tzinfo=timezone.utc) - self.utc_now()).days
            out.update(issuer=facts["issuer"], not_after=facts["not_after"], days_left=days)
            out["answer"] = (f"{domain}: the TLS certificate validates; issuer {facts['issuer']}; expires {facts['not_after']} "
                             f"({days} days left).")
        else:
            out["answer"] = f"{domain}: the TLS certificate does not validate ({facts.get('reason') or 'unknown reason'})."
        return out, cache, False, {"TLS handshake": as_of}

    def _agent_record(self, args, remaining):
        """agent.record.v1 (mcp-server-trust-check our_record seat, agent team 11-17): what AgentValCon's own
        published records say about an agent or MCP server, found by its URL or name (our_records.py: the task-page
        catalog, the verified registry and the verify snapshot). Nothing is called and the database is not read; a
        server outside those records is answered as not found in our published records."""
        from datetime import datetime as _dt, timezone as _tz
        from ..concierge.agent_check import CheckError
        from .our_records import RECORDS
        url = str(args.get("url") or "").strip() or None
        name = str(args.get("name") or "").strip() or None
        if not url and not name:
            raise FallbackUnavailable("invalid_input", "Give the agent's https URL or its name.")
        try:
            rid, matched = RECORDS.find(url, name)
        except CheckError as exc:
            raise FallbackUnavailable("invalid_input", str(exc)) from exc
        source = "AgentValCon collection and test records (published snapshots)"
        if rid is None:
            what = url or name
            return ({"found": False, "source": source,
                     "answer": f"{what} is not in AgentValCon's published records (listed agents, verified MCP servers "
                               "and tested agents). Nothing was called to answer this."},
                    {"status": "fresh_cache", "age_seconds": 0}, False, {source: _now_iso(self.utc_now())})
        entry = RECORDS.entry(rid)
        cat, reg, ver = entry.get("catalog") or {}, entry.get("registry") or {}, entry.get("verify") or {}
        meta = ((reg.get("_meta") or {}).get("biz.agentconcierge/verification") or {})
        out = {"found": True, "agent_id": rid, "source": source, "url": f"https://agentconcierge.biz/agent/{rid}"}
        name_out = cat.get("name") or (reg.get("server") or {}).get("name") or ver.get("name")
        if isinstance(name_out, str):
            out["name"] = _text(name_out, 200)
        kind = cat.get("kind") or ver.get("kind") or ("mcp" if reg else None)
        if kind in ("mcp", "a2a", "x402"):
            out["kind"] = kind
        grade = cat.get("eval_grade") or meta.get("grade") or ver.get("grade")
        if isinstance(grade, str) and grade in "ABCDEF" and len(grade) == 1:
            out["grade"] = grade
        status = cat.get("health_status")
        out["status"] = status if status in ("healthy", "degraded", "down", "inactive") else "unknown"
        if isinstance(cat.get("last_check_at"), (int, float)):
            out["last_checked_at"] = _dt.fromtimestamp(cat["last_check_at"], _tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(meta.get("last_success_at"), str):
            out["last_checked_at"] = meta["last_success_at"][:40]
        tested = [r for r in ver.get("roles") or [] if isinstance(r, dict) and isinstance(r.get("score"), (int, float))
                  and r.get("tested_at")]
        if tested:
            best = max(tested, key=lambda r: (r["score"], str(r["tested_at"])))
            out["role_test"] = {"role": _text(best.get("role"), 80), "score": round(float(best["score"]), 1),
                                "tested_at": _text(best["tested_at"], 40)}
        parts = [f"{out.get('name', rid)} (AgentValCon agent {rid}, matched by {matched})"]
        if out.get("grade"):
            parts.append(f"quality grade {out['grade']}")
        parts.append(f"reachability {out['status']}" + (f", last checked {out['last_checked_at']}" if out.get("last_checked_at") else ""))
        if meta.get("listed"):
            parts.append("listed in our verified MCP registry" + (f" (tool {meta['checked_tool']} called)" if meta.get("checked_tool") else ""))
        if out.get("role_test"):
            rt = out["role_test"]
            parts.append(f"best role test {rt['role']} {rt['score']}/100 on {rt['tested_at']}")
        out["answer"] = "; ".join(parts) + ". From our published records; nothing was called."
        return out, {"status": "fresh_cache", "age_seconds": 0}, False, {source: _now_iso(self.utc_now())}

    def _package_readme(self, args, remaining):
        """docs.readme.v1 (package-risk-audit v2 usage seat, agent team 11-17): how to use an npm package now, from the
        README the npm registry holds for it (the latest release's README): the install command, the first code
        example that is not a shell line, the documentation link and the section headings. npm only, like
        package-releases, until PyPI's terms are read. The README text itself is not returned beyond the example."""
        package, ecosystem = str(args.get("package") or ""), args.get("ecosystem")
        version = str(args.get("version") or "")
        if not PACKAGE.fullmatch(package) or len(package) > 214 or (version and not re.fullmatch(r"[A-Za-z0-9.+_!~-]{1,64}", version)):
            raise FallbackUnavailable("invalid_input", "Use a valid package name and exact version.")
        if ecosystem != "npm":
            raise FallbackUnavailable("source_unavailable", "PyPI READMEs are not offered yet; use npm.")
        from urllib.parse import quote as _quote

        def live(rem):
            raw = self._get_json("https://registry.npmjs.org/" + _quote(package, safe="@"), rem, limit=24 * 1024 * 1024)
            latest = ((raw.get("dist-tags") or {}).get("latest")) or ""
            info = (raw.get("versions") or {}).get(latest) or {}
            readme = raw.get("readme") if isinstance(raw.get("readme"), str) else ""
            home = info.get("homepage") or raw.get("homepage")
            return {"latest": _text(latest, 64), "readme": readme[:200000], "versions": sorted(raw.get("versions") or {})[-500:],
                    "homepage": home if isinstance(home, str) and home.startswith("https://") else "",
                    "repository": repository_url(raw.get("repository") or info.get("repository"))}, _now_iso(self.utc_now())
        (data, as_of), cache = self._cached(("package-readme", package.lower()), TTL["package-readme"], live, remaining)
        if version and version not in data["versions"] and version != data["latest"]:
            raise FallbackUnavailable("not_found", "The npm registry has no such version of this package.")
        readme = data["readme"]
        if not readme.strip() or readme.strip().upper() == "ERROR: NO README DATA FOUND!":
            raise FallbackUnavailable("not_found", "The npm registry holds no README for this package.")
        example = readme_example(readme)
        sections = [_text(h, 200) for h in re.findall(r"(?m)^#{2,3}\s+(.+?)\s*#*$", readme)][:10]
        install = f"npm install {package}" + (f"@{version}" if version else "")
        out = {"package": package, "version": version or data["latest"], "install": install,
               "readme_url": "https://www.npmjs.com/package/" + package,
               "url": "https://www.npmjs.com/package/" + package,
               "source": "npm public registry (README of the latest release)"}
        if data["homepage"]:
            out["docs_url"] = data["homepage"]
        if example:
            out["example"] = example
        if sections:
            out["sections"] = sections
        note = "" if not version or version == data["latest"] else f" The README is the one of the latest release {data['latest']}, not of {version}."
        out["answer"] = (f"{package}: install with `{install}`."
                         + (f" First example from its README:\n{example}" if example else " Its README has no code example.")
                         + (f"\nDocumentation: {data['homepage']}" if data["homepage"] else "") + note)
        return out, cache, False, {"npm public registry": as_of}

    def _dns_spf_dmarc(self, args, remaining):
        """dns.mail_auth.v1 (website-trust-brief v2 mail_auth seat, agent team 11-17): the domain's SPF record (TXT at
        the name that starts with v=spf1) and DMARC record (TXT at _dmarc.<domain> that starts with v=DMARC1), asked
        of this machine's own resolver. Public DNS facts; the records are quoted as published."""
        from .dns_txt import DnsError
        from .net import site_host
        raw = next((str(args[k]) for k in ("domain", "host", "hostname", "url") if args.get(k)), "")
        domain = re.sub(r"^https?://", "", raw.strip().lower()).split("/")[0].split(":")[0].rstrip(".")
        if not site_host(domain):
            raise FallbackUnavailable("invalid_input", "Use a public domain name such as example.com.")

        def live(rem):
            found = {}
            for key, name, prefix in (("spf", domain, "v=spf1"), ("dmarc", "_dmarc." + domain, "v=dmarc1")):
                try:
                    records = self.dns_txt(name, max(0.5, min(3.0, rem() - 0.2)))
                except DnsError as exc:
                    raise SourceError("The DNS resolver did not answer.") from exc
                found[key] = [r for r in records if r.strip().lower().startswith(prefix)][:3]
            return found, _now_iso(self.utc_now())
        (found, as_of), cache = self._cached(("dns-spf-dmarc", domain), TTL["dns-spf-dmarc"], live, remaining)
        spf, dmarc = found["spf"], found["dmarc"]
        parts = [f"{domain}:"]
        if len(spf) == 1:
            parts.append(f"SPF {_text(spf[0], 1500)}.")
        elif spf:
            parts.append(f"{len(spf)} SPF records (invalid: only one is allowed): " + " | ".join(_text(s, 700) for s in spf) + ".")
        else:
            parts.append("no SPF record published.")
        if dmarc:
            policy = re.search(r"(?:^|;)\s*p\s*=\s*([a-z]+)", dmarc[0].lower())
            parts.append(f"DMARC {_text(dmarc[0], 1500)}" + (f" (policy {policy.group(1)})." if policy else "."))
        else:
            parts.append("no DMARC record published at _dmarc." + domain + ".")
        parts.append("DKIM is not checked (its selector names are not public).")
        out = {"answer": " ".join(parts), "source": "Public DNS TXT records, read through our own resolver"}
        return out, cache, False, {"public DNS": as_of}

    def _mcp_registry(self, args, remaining):
        """mcp.registry.lookup.v1 (PM 11-15 16:12): an exact registry name reads its latest version; a phrase searches.
        Not found is a normal answer (listed false): the registry is in preview and entries can be reset."""
        from urllib.parse import quote as _quote
        base = "https://registry.modelcontextprotocol.io/v0.1/servers"
        name = str(args.get("name") or "").strip()
        query = " ".join(str(args.get("query") or "").split())
        if name and not REGISTRY_NAME.fullmatch(name):
            raise FallbackUnavailable("invalid_input", "Use a registry name such as io.github.owner/server.")
        if not name and not 2 <= len(query) <= 200:
            raise FallbackUnavailable("invalid_input", "Give a registry name or a search phrase.")

        def live(rem):
            if name:
                try:
                    raw = self._get_json(f"{base}/{_quote(name, safe='')}/versions/latest", rem, limit=512 * 1024)
                except FallbackUnavailable:
                    return None, _now_iso(self.utc_now())          # 404: not in the registry
                return raw, _now_iso(self.utc_now())
            raw = self._get_json(base, rem, params={"search": query, "limit": 10}, limit=1024 * 1024)
            rows = [r for r in raw.get("servers") or [] if isinstance(r, dict) and isinstance(r.get("server"), dict)]
            exact = [r for r in rows if r["server"].get("name", "").lower() == query.lower()]
            pick = exact[0] if exact else (rows[0] if len(rows) == 1 else None)
            return pick, _now_iso(self.utc_now())
        (raw, as_of), cache = self._cached(("mcp-registry", name.lower() or "q:" + query.lower()), TTL["mcp-registry"],
                                           live, remaining)
        if not raw:
            return ({"listed": False, "url": "https://registry.modelcontextprotocol.io/",
                     "source": "Official MCP Registry (preview; CC0): no entry with this " + ("name" if name else "search phrase")},
                    cache, False, {"Official MCP Registry": as_of})
        server = raw.get("server") or {}
        meta = (raw.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
        out = {"listed": True, "name": _text(server.get("name"), 200), "version": _text(server.get("version"), 255),
               "url": f"{base}/{_quote(str(server.get('name')), safe='')}/versions/latest",
               "source": "Official MCP Registry (preview; CC0)"}
        if meta.get("status"):
            out["status"] = _text(meta["status"], 40)
        if meta.get("publishedAt"):
            out["published_at"] = _text(meta["publishedAt"], 40)
        repo = server.get("repository")
        repo_url = repo.get("url") if isinstance(repo, dict) else repo
        if isinstance(repo_url, str) and repo_url.startswith("https://"):
            out["repository"] = repo_url[:2000]
        if isinstance(server.get("websiteUrl"), str) and server["websiteUrl"].startswith("https://"):
            out["website"] = server["websiteUrl"][:2000]
        remotes = [r.get("url") for r in server.get("remotes") or [] if isinstance(r, dict)
                   and isinstance(r.get("url"), str) and r["url"].startswith("https://")]
        if remotes:
            out["remotes"] = remotes[:10]
        return out, cache, False, {"Official MCP Registry": as_of}

    def _census_geocode(self, args, remaining):
        """geocode.address.v1 for U.S. addresses (PM 11-15 14:25): the address string is the only thing sent. An
        address that is plainly not in the United States is not sent; it and a no-match answer not_found, so a
        necklace moves on to its next member."""
        address = " ".join(str(args.get("address") or args.get("query") or "").split())
        if not 5 <= len(address) <= 300:
            raise FallbackUnavailable("invalid_input", "Give a street address of 5 to 300 characters.")
        if not address.isascii() or NON_US.search(address):
            raise FallbackUnavailable("not_found", "This substitute covers U.S. addresses only.")

        def live(rem):
            raw = self._get_json("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress", rem,
                                 params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
                                 limit=512 * 1024)
            matches = ((raw.get("result") or {}).get("addressMatches") or [])
            rows = []
            for m in matches[:3]:
                xy = (m or {}).get("coordinates") or {}
                if isinstance(xy.get("x"), (int, float)) and isinstance(xy.get("y"), (int, float)):
                    rows.append((_text(m.get("matchedAddress"), 300), float(xy["y"]), float(xy["x"])))
            return rows, _now_iso(self.utc_now())
        (rows, as_of), cache = self._cached(("census-geocode", address.lower()), TTL["census-geocode"], live, remaining)
        # the Census matcher is fuzzy: keep only a match with the same house number and street type ("2301 N Highland
        # Ave" must not become "2301 HIGHLAND DR", 8 km away; workflow us-street check 11-15)
        rows = [r for r in rows if same_street(address, r[0])]
        if not rows:
            raise FallbackUnavailable("not_found", "No U.S. Census Geocoder match; this substitute covers U.S. addresses only.")
        name, lat, lon = rows[0]
        more = f" ({len(rows) - 1} other candidate{'s' if len(rows) > 2 else ''} matched)" if len(rows) > 1 else ""
        out = {"answer": f"{name}: lat {lat:.6f} lon {lon:.6f}, country code US{more}.",
               "url": "https://geocoding.geo.census.gov/geocoder/",
               "source": "U.S. Census Bureau Geocoder (public domain), benchmark Public_AR_Current"}
        return out, cache, False, {"Census Geocoder": as_of}

    def _gdelt_news(self, args, remaining):
        """news.search.v1 from the GDELT DOC 2.0 API (PM 11-15 13:52): article titles, outlet, date and link for a
        topic in the last 7 days; never the article text. GDELT allows unrestricted use with a citation and link."""
        query = " ".join(str(args.get("query") or "").split())
        if not 2 <= len(query) <= 300 or any(c in query for c in "<>{}\\"):
            raise FallbackUnavailable("invalid_input", "Use a topic of 2 to 300 characters.")
        try:
            limit = max(1, min(20, int(args.get("limit") or 10)))
        except (TypeError, ValueError):
            raise FallbackUnavailable("invalid_input", "limit is a number from 1 to 20.") from None
        # GDELT treats bare words as AND; a phrase with spaces is quoted only when the caller quoted it
        terms = query if len(query.split()) == 1 or '"' in query else " ".join(w for w in query.split() if len(w) > 2) or query

        def live(rem):
            response = get("https://api.gdeltproject.org/api/v2/doc/doc", limiters=self.limiters, http=self.http,
                           params={"query": terms, "mode": "artlist", "format": "json", "maxrecords": 20,
                                   "timespan": "7d", "sort": "datedesc"},
                           seconds=max(0.1, rem() - 0.1), limit=2 * 1024 * 1024)
            text = response.content.decode("utf-8", "replace").strip()
            if not text.startswith("{"):
                # GDELT answers plain text for a query it rejects (too short, bad operator) or when it is busy
                if re.search(r"(?i)limit requests|too many", text):
                    raise SourceBusy("GDELT asked us to slow down.")
                raise FallbackUnavailable("invalid_input", "GDELT did not accept this topic; use plain words.")
            raw = json.loads(text)
            rows = []
            for art in raw.get("articles") or []:
                if not isinstance(art, dict):
                    continue
                url, title = str(art.get("url") or ""), _text(art.get("title"), 300)
                if not url.startswith("https://") or not title:
                    continue
                seen = str(art.get("seendate") or "")
                published = (f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}T{seen[9:11]}:{seen[11:13]}:{seen[13:15]}Z"
                             if re.fullmatch(r"\d{8}T\d{6}Z", seen) else "")
                rows.append({"title": title, "url": url[:2000], "published": published,
                             "outlet": _text(art.get("domain"), 100), "language": _text(art.get("language"), 40)})
            return rows, _now_iso(self.utc_now())
        (rows, as_of), cache = self._cached(("gdelt-news", terms.lower()), TTL["gdelt-news"], live, remaining)
        if not rows:
            raise FallbackUnavailable("not_found", "GDELT has no articles on this topic in the last 7 days.")
        items = []
        for r in rows[:limit]:
            title = r["title"] + (f" ({r['outlet']})" if r["outlet"] else "")
            item = {"title": title[:4000], "url": r["url"]}
            if r["published"]:
                item["published"] = r["published"]
            items.append(item)
        out = {"items": items,
               "source": "The GDELT Project (https://www.gdeltproject.org/), DOC 2.0 API, articles seen in the last "
                         "7 days; titles and links only, the articles belong to their publishers"}
        return out, cache, False, {"GDELT DOC API": as_of}

    def _wiktionary_define(self, args, remaining):
        word = next((" ".join(str(args[k]).split()) for k in ("word", "term", "query") if args.get(k)), "")
        if not word or len(word) > 80 or any(c in word for c in "|#<>[]{}/"):
            raise FallbackUnavailable("invalid_input", "Use one word or short phrase.")

        def live(rem):
            raw = self._get_json("https://en.wiktionary.org/api/rest_v1/page/definition/" + quote(word.replace(" ", "_"), safe=""),
                                 rem, limit=512 * 1024)
            groups = []
            for entry in (raw.get("en") or [])[:4]:
                defs = [_text(re.sub(r"<[^>]+>", "", d.get("definition") or ""), 300) for d in entry.get("definitions") or []
                        if isinstance(d, dict)]
                defs = [d for d in defs if d][:3]
                if defs:
                    groups.append((_text(entry.get("partOfSpeech"), 30), defs))
            if not groups:
                raise FallbackUnavailable("not_found", "Wiktionary has no English definition for this word.")
            return groups, _now_iso(self.utc_now())
        (groups, as_of), cache = self._cached(("wiktionary-define", word.lower()), TTL["wiktionary-define"], live, remaining)
        lines = " ".join(f"{pos}: " + " ".join(f"({i}) {d}" for i, d in enumerate(defs, 1)) for pos, defs in groups)
        out = {"answer": f"{word} — {lines}"[:8000], "url": "https://en.wiktionary.org/wiki/" + quote(word.replace(" ", "_")),
               "source": "Wiktionary (CC BY-SA 4.0, Wiktionary contributors)"}
        return out, cache, False, {"Wiktionary": as_of}

    def _github_repo(self, args, remaining):
        repo = next((str(args[k]).strip() for k in ("repo", "repository") if args.get(k)), "")
        if not repo and args.get("owner") and args.get("name"):
            repo = f"{args['owner']}/{args['name']}"
        repo = re.sub(r"^(?:https?://)?github\.com/", "", repo).strip("/").removesuffix(".git")
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}", repo):
            raise FallbackUnavailable("invalid_input", "Use a GitHub repository as owner/name.")

        def live(rem):
            response = get("https://api.github.com/repos/" + repo, limiters=self.limiters, http=self.http,
                           seconds=max(0.1, rem() - 0.1), limit=1024 * 1024, ok=(200, 301, 404))
            if response.status_code == 301:  # a moved repository: one hop to its numeric address, same host
                target = response.headers.get("location") or ""
                if not re.fullmatch(r"https://api\.github\.com/repositories/\d{1,12}", target):
                    raise ValueError("unexpected redirect")
                response = get(target, limiters=self.limiters, http=self.http, seconds=max(0.1, rem() - 0.1),
                               limit=1024 * 1024, ok=(200, 404))
            if response.status_code == 404:
                raise FallbackUnavailable("not_found", "No public GitHub repository with this name.")
            raw = json.loads(response.content)
            lic = (raw.get("license") or {}).get("spdx_id") or "none stated"
            facts = (f"{raw.get('full_name')}: {_text(raw.get('description'), 300).rstrip('.') or 'no description'}. License {lic}; "
                     f"{raw.get('stargazers_count')} stars; {raw.get('forks_count')} forks; {raw.get('open_issues_count')} open "
                     f"issues and pull requests; default branch {raw.get('default_branch')}; "
                     f"{'archived' if raw.get('archived') else 'not archived'}; last push {raw.get('pushed_at')}.")
            if raw.get("full_name", "").lower() != repo.lower():
                facts += f" (Requested {repo}; GitHub redirects it here.)"
            return {"answer": facts[:8000], "url": _text(raw.get("html_url"), 300) or "https://github.com/" + repo,
                    "source": "GitHub REST API"}, _text(raw.get("pushed_at"), 40) or None
        (out, as_of), cache = self._cached(("github-repo", repo.lower()), TTL["github-repo"], live, remaining)
        return out, cache, False, {"GitHub (last push)": as_of}

    def _package_releases(self, args, remaining):
        """package.releases.v1 (PM 11-15 16:12): one npm registry document; PyPI waits for its terms (11-16)."""
        package, ecosystem = str(args.get("package") or ""), args.get("ecosystem")
        if not PACKAGE.fullmatch(package) or len(package) > 214:
            raise FallbackUnavailable("invalid_input", "Use a valid package name.")
        if ecosystem != "npm":
            raise FallbackUnavailable("source_unavailable", "PyPI release history is not offered yet; use npm.")
        from urllib.parse import quote as _quote

        def live(rem):
            raw = self._get_json("https://registry.npmjs.org/" + _quote(package, safe="@"), rem, limit=24 * 1024 * 1024)
            times = raw.get("time") or {}
            versions = raw.get("versions") or {}
            latest = ((raw.get("dist-tags") or {}).get("latest")) or ""
            stable = sorted(((t[:10], v) for v, t in times.items() if v in versions and isinstance(t, str)
                             and not re.search(r"-(?:alpha|beta|rc|next|canary|dev|pre)", v)), reverse=True)
            info = versions.get(latest) or {}
            return {"latest": _text(latest, 64), "latest_at": _text(times.get(latest), 20)[:10],
                    "maintainers": len([m for m in raw.get("maintainers") or [] if isinstance(m, dict)]),
                    "deprecated": _text(info.get("deprecated"), 200) if info.get("deprecated") else "",
                    "recent": stable[:6], "count": len(versions),
                    "repository": repository_url(raw.get("repository") or info.get("repository"))}, _now_iso(self.utc_now())
        (data, as_of), cache = self._cached(("package-releases", package.lower()), TTL["package-releases"], live, remaining)
        if not data["latest"]:
            raise FallbackUnavailable("not_found", "The npm registry lists no released version for this package.")
        gaps = []
        for (a, _), (b, _) in zip(data["recent"], data["recent"][1:]):
            try:
                gaps.append((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days)
            except ValueError:
                pass
        parts = [f"{package} (npm): latest {data['latest']} released {data['latest_at'] or 'date not listed'}",
                 f"{data['maintainers']} maintainer{'s' if data['maintainers'] != 1 else ''}",
                 f"deprecated: {data['deprecated']}" if data["deprecated"] else "not deprecated",
                 f"{data['count']} versions in all"]
        if data["recent"]:
            parts.append("recent stable releases: " + ", ".join(f"{v} {d}" for d, v in data["recent"][:5])
                         + (f" (gaps {', '.join(str(g) for g in gaps[:4])} days)" if gaps else ""))
        if data["repository"]:
            parts.append(f"repository {data['repository']}")
        out = {"answer": ("; ".join(parts) + ".")[:8000], "url": "https://www.npmjs.com/package/" + package,
               "source": "npm public registry",
               # structured fields for the next step (workflow 11-15): repository_github feeds github-releases' repo
               "latest_version": data["latest"], "maintainers": data["maintainers"], "deprecated": bool(data["deprecated"]),
               "release_gap_days": [g for g in gaps if g >= 0][:4]}
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["latest_at"] or ""):
            out["latest_date"] = data["latest_at"]
        if data["repository"]:
            out["repository"] = data["repository"]
            gh = re.fullmatch(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?",
                              data["repository"])
            if gh:
                out["repository_github"] = gh.group(1)
        return out, cache, False, {"npm registry": as_of}

    def _github_releases(self, args, remaining):
        """github.releases.v1 (PM 11-15 16:12). Allowed by GitHub's terms while necklace runs are free (section H puts
        resale-like or high-throughput access under a subscription: judged again if runs are ever charged). Two calls a
        repository inside the shared unauthenticated allowance; when it is used up the answer is rate_limited, never
        a made-up release."""
        repo = next((str(args[k]).strip() for k in ("repo", "repository") if args.get(k)), "")
        repo = re.sub(r"^(?:https?://)?github\.com/", "", repo).strip("/").removesuffix(".git")
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}", repo):
            raise FallbackUnavailable("invalid_input", "Use a GitHub repository as owner/name.")

        def live(rem):
            def list_of(path, params):
                response = get(f"https://api.github.com/repos/{repo}/{path}", limiters=self.limiters, http=self.http,
                               params=params, seconds=max(0.1, rem() - 0.1), limit=1024 * 1024, ok=(200, 404))
                if response.status_code == 404:
                    raise FallbackUnavailable("not_found", "No public GitHub repository with this name.")
                raw = json.loads(response.content)
                return raw if isinstance(raw, list) else []
            releases = [r for r in list_of("releases", {"per_page": 5}) if isinstance(r, dict) and not r.get("draft")]
            issues = [i for i in list_of("issues", {"state": "open", "sort": "created", "direction": "desc",
                                                     "per_page": 10}) if isinstance(i, dict) and "pull_request" not in i]
            return {"releases": [(_text(r.get("tag_name"), 80), _text(r.get("published_at"), 20)[:10],
                                  bool(r.get("prerelease"))) for r in releases[:5]],
                    "issues": [(i.get("number"), _text(i.get("title"), 160), _text(i.get("created_at"), 20)[:10])
                               for i in issues[:5]]}, _now_iso(self.utc_now())
        (data, as_of), cache = self._cached(("github-releases", repo.lower()), TTL["github-releases"], live, remaining)
        rels = [r for r in data["releases"] if r[1]]
        gaps = []
        if rels:
            text = "; ".join(f"{tag} {day}" + (" (pre-release)" if pre else "") for tag, day, pre in rels)
            for (_, a, _), (_, b, _) in zip(rels, rels[1:]):
                try:
                    gaps.append((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days)
                except ValueError:
                    pass
            gap = f" Gaps between them: {', '.join(str(g) for g in gaps)} days." if gaps else ""
            head = f"{repo}: recent releases (newest first): {text}.{gap}"
        else:
            head = f"{repo}: no GitHub releases published (tags may still exist)."
        if data["issues"]:
            head += " Newest open issues: " + "; ".join(f"#{n} {title} ({day})" for n, title, day in data["issues"]) + "."
        else:
            head += " No open issues."
        out = {"answer": head[:8000], "url": f"https://github.com/{repo}/releases", "source": "GitHub REST API (no token)",
               "repo": repo,   # structured fields beside the sentence, so a later step can take them (workflow 11-15)
               "open_issues": [{"number": n, "title": t, **({"date": d} if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d or "") else {})}
                               for n, t, d in data["issues"] if isinstance(n, int)]}
        if rels:
            out["latest_tag"] = rels[0][0]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", rels[0][1]):
                out["latest_date"] = rels[0][1]
            out["release_gap_days"] = [g for g in gaps if g >= 0][:4]
        return out, cache, False, {"GitHub REST API": as_of}

    def _rdap_domain(self, args, remaining):
        from .net import site_host
        domain = str(args.get("domain") or "").strip().lower().rstrip(".")
        domain = re.sub(r"^https?://", "", domain).split("/")[0]
        if not site_host(domain):
            raise FallbackUnavailable("invalid_input", "Use a public domain name such as example.com.")

        def bootstrap(rem):
            raw = self._get_json("https://data.iana.org/rdap/dns.json", rem, limit=1024 * 1024)
            table = {}
            for tlds, urls in (s[:2] for s in raw.get("services") or [] if isinstance(s, list) and len(s) >= 2):
                base = next((u for u in urls if isinstance(u, str) and u.startswith("https://")), None)
                for tld in tlds if base else []:
                    table[str(tld).lower()] = base
            if len(table) < 100:
                raise ValueError("bootstrap too small")
            return table, _text(raw.get("publication"), 40)
        (table, _), _ = self._cached(("rdap-bootstrap",), TTL["rdap-bootstrap"], bootstrap, remaining)
        labels = domain.split(".")
        base = next((table[".".join(labels[i:])] for i in range(1, len(labels)) if ".".join(labels[i:]) in table), None)
        if not base:
            raise FallbackUnavailable("not_found", "This top-level domain has no RDAP server in the IANA bootstrap.")

        def live(rem):
            response = get(base.rstrip("/") + "/domain/" + domain, limiters=self.limiters, http=self.http,
                           seconds=max(0.1, rem() - 0.1), limit=512 * 1024, accept="application/rdap+json, application/json",
                           ok=(200, 404), any_site=True)
            if response.status_code == 404:
                raise FallbackUnavailable("not_found", "The registry has no registration for this domain.")
            raw = json.loads(response.content)
            events = {e.get("eventAction"): _text(e.get("eventDate"), 40) for e in raw.get("events") or [] if isinstance(e, dict)}
            registrar = next((v[3] for e in raw.get("entities") or [] if "registrar" in (e.get("roles") or [])
                              for v in ((e.get("vcardArray") or [None, []])[1] or []) if isinstance(v, list) and v[:1] == ["fn"]), None)
            ns = [_text(n.get("ldhName"), 100).lower() for n in raw.get("nameservers") or [] if isinstance(n, dict)][:6]
            parts = [f"{domain}: registered {events.get('registration', '?')[:10]}",
                     f"expires {events.get('expiration', '?')[:10]}", f"last changed {events.get('last changed', '?')[:10]}",
                     f"registrar {_text(registrar, 120) or 'not listed'}",
                     "status " + (", ".join(_text(x, 40) for x in raw.get("status") or []) or "not listed"),
                     "name servers " + (", ".join(ns) or "not listed")]
            return {"answer": "; ".join(parts) + ".", "url": "https://lookup.icann.org/en/lookup?name=" + domain,
                    "source": f"RDAP ({urlsplit(base).hostname})"}, events.get("last update of RDAP database")
        (out, as_of), cache = self._cached(("rdap-domain", domain), TTL["rdap-domain"], live, remaining)
        return out, cache, False, {"RDAP registry": as_of}

    def _unit_convert(self, args, remaining):
        value = next((args[k] for k in ("value", "amount") if isinstance(args.get(k), (int, float))), None)
        src = next((str(args[k]) for k in ("from", "from_unit") if args.get(k)), "")
        dst = next((str(args[k]) for k in ("to", "to_unit") if args.get(k)), "")
        if value is None or not src or not dst:
            raise FallbackUnavailable("invalid_input", "Give a value and the units to convert from and to.")
        try:
            result, a_unit, b_unit = convert_units(float(value), src, dst)
        except ValueError as exc:
            raise FallbackUnavailable("invalid_input", str(exc)) from exc
        shown = f"{result:.10g}"
        out = {"answer": f"{value:g} {a_unit} = {shown} {b_unit}", "url": "https://www.nist.gov/pml/special-publication-811",
               "source": "Exact SI definitions (NIST SP 811)"}
        return out, {"status": "snapshot", "age_seconds": 0}, False, {"NIST SP 811": "2008 edition"}

    def _wikidata_item(self, text, needed, props, rem):
        """Search Wikidata, then one SPARQL query for the candidates: the first hit (search order) that carries
        NEEDED, with the values and English labels of PROPS. Two requests; whole items are never downloaded."""
        found = self._get_json("https://www.wikidata.org/w/api.php", rem, limit=256 * 1024, params={
            "action": "wbsearchentities", "search": text, "language": "en", "type": "item", "limit": 7,
            "format": "json", "maxlag": 5})
        ids = [h["id"] for h in found.get("search") or [] if isinstance(h, dict)
               and re.fullmatch(r"Q\d{1,12}", str(h.get("id")))]
        if not ids:
            raise FallbackUnavailable("not_found", "Wikidata has no item with this name.")
        optional = " ".join(f"OPTIONAL {{ ?item wdt:{p} ?{p} }}" for p in props)
        select = " ".join(f"?{p} ?{p}Label" for p in props)
        query = (f"SELECT ?item ?itemLabel ?itemDescription {select} WHERE {{ VALUES ?item {{ "
                 + " ".join("wd:" + i for i in ids) + f" }} {optional} "
                 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } } LIMIT 300')
        response = get("https://query.wikidata.org/sparql", limiters=self.limiters, http=self.http,
                       params={"query": query, "format": "json"}, seconds=max(0.1, rem() - 0.1), limit=512 * 1024,
                       accept="application/sparql-results+json")
        rows = json.loads(response.content).get("results", {}).get("bindings") or []
        items: dict[str, dict] = {}
        for row in rows:
            qid = str((row.get("item") or {}).get("value", "")).rsplit("/", 1)[-1]
            entry = items.setdefault(qid, {"id": qid, "label": (row.get("itemLabel") or {}).get("value", qid),
                                           "description": (row.get("itemDescription") or {}).get("value", "")})
            for p in props:
                value = (row.get(p) or {}).get("value")
                if value is not None:
                    label = (row.get(p + "Label") or {}).get("value", value)
                    entry.setdefault(p, [])
                    if label not in entry[p]:
                        entry[p].append(label)
        item = next((items[i] for i in ids if i in items and items[i].get(needed)), None)
        if not item:
            raise FallbackUnavailable("not_found", f"No Wikidata item with this name has the needed facts ({needed}).")
        return item

    def _wikidata_place(self, args, remaining):
        query = " ".join(str(args.get("query") or "").split())
        if len(query) < 2 or len(query) > 120:
            raise FallbackUnavailable("invalid_input", "Give the name of a place or landmark.")

        def live(rem):
            item = self._wikidata_item(query, "P625", ("P625", "P131", "P17"), rem)
            answer = f"{item['label']} — {item['description']} (Wikidata {item['id']})"
            m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", item["P625"][0])
            if m:
                answer += f": coordinates latitude {float(m[2]):.5f}, longitude {float(m[1]):.5f}"
            where = ", ".join(dict.fromkeys(item.get("P131", [])[:2] + item.get("P17", [])[:1]))
            if where:
                answer += f"; located in {where}"
            return {"answer": _text(answer + ".", 8000), "url": "https://www.wikidata.org/wiki/" + item["id"],
                    "source": "Wikidata (CC0)"}, _now_iso(self.utc_now())
        (out, as_of), cache = self._cached(("wikidata-place", query.lower()), TTL["wikidata-place"], live, remaining)
        return out, cache, False, {"Wikidata": as_of}

    def _wikidata_book(self, args, remaining):
        title = " ".join(str(args.get("title") or args.get("query") or "").split())
        if len(title) < 2 or len(title) > 200:
            raise FallbackUnavailable("invalid_input", "Give a book title.")

        def live(rem):
            item = self._wikidata_item(title, "P50", ("P50", "P577", "P136", "P407"), rem)
            parts = [f"{item['label']} — {item['description']} (Wikidata {item['id']})", "author " + ", ".join(item["P50"][:5])]
            dates = sorted(d[:10] for d in item.get("P577", []) if re.match(r"\d{4}-", d))
            if dates:  # a year-precision date comes back as YYYY-01-01
                parts.append("first published " + (dates[0][:4] if dates[0].endswith("-01-01") else dates[0]))
            if item.get("P136"):
                parts.append("genre " + ", ".join(item["P136"][:4]))
            if item.get("P407"):
                parts.append("language " + ", ".join(item["P407"][:3]))
            return {"answer": _text("; ".join(parts) + ".", 8000), "url": "https://www.wikidata.org/wiki/" + item["id"],
                    "source": "Wikidata (CC0)"}, _now_iso(self.utc_now())
        (out, as_of), cache = self._cached(("wikidata-book", title.lower()), TTL["wikidata-book"], live, remaining)
        return out, cache, False, {"Wikidata": as_of}

    # ---------------------------------------------------------------- usage
    def _usage(self, agent_id, envelope, code, started, cause=None):
        line = {"at": _now_iso(self.utc_now()), "agent": agent_id if agent_id in SPECS else "unknown",
                "ok": envelope is not None, "code": code, "ms": int((self.clock() - started) * 1000),
                "cache": (envelope or {}).get("cache", {}).get("status")}
        if cause:
            line["exception"] = str(cause)[:60]       # the exception type only, never its text
        try:
            self.usage_dir.mkdir(parents=True, exist_ok=True)
            with open(self.usage_dir / f"{line['at'][:10]}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
        except OSError:
            pass


# Checks of a contract's own answer rules, by contract (PM 11-16 source review: the CVE checks used to sit in the
# common path of every agent). Each raises invalid_output when the answer breaks its contract's rule.
def _check_cve_record(arguments, result):
    if "cve_id" in arguments and result.get("cve_id") != arguments["cve_id"]:
        raise FallbackUnavailable("invalid_output", "The source answered a different CVE.")
    if ("cvss_score" in result) != ("cvss_version" in result):
        raise FallbackUnavailable("invalid_output", "Score and version must come together.")


def _check_same_cve(arguments, result):
    if "cve_id" in arguments and result.get("cve_id") != arguments["cve_id"]:
        raise FallbackUnavailable("invalid_output", "The source answered a different CVE.")


CONTRACT_CHECKS = {"cve.record.v1": _check_cve_record, "cve.exploited.v1": _check_same_cve}


def contract_check(contract_id: str, arguments: dict, result: dict) -> None:
    check = CONTRACT_CHECKS.get(contract_id)
    if check:
        check(arguments, result)


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
            who = _text((block.get("providerMetadata") or {}).get("shortName"), 40) or "unnamed"
            out["source"] = f"CVE Program (score from {'CNA' if block is cna else 'ADP'} {who})"
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


REPO_HOST = re.compile(r"(?:git\+)?(?:https?|git|ssh)?:?/*(?:git@)?(github\.com|gitlab\.com|bitbucket\.org)[:/]"
                       r"([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$")


def repository_url(value, hosted_only: bool = False):
    """Normalize a repository field to https://host/owner/repo; other https URLs pass unless hosted_only."""
    if isinstance(value, dict):
        value = value.get("url")
    if not isinstance(value, str) or len(value) > 2000 or " " in value.strip():
        return None
    value = value.strip()
    short = re.fullmatch(r"(?:github:)?([\w.-]+)/([\w.-]+)", value)
    if short and not value.startswith(("http", "git+", "git:", "git@")):
        return f"https://github.com/{short[1]}/{short[2]}"
    m = REPO_HOST.match(value)
    if m:
        return f"https://{m[1]}/{m[2]}/{m[3]}"
    if not hosted_only and value.startswith("https://"):
        return value
    return None


def readme_examples(readme: str) -> list[str]:
    """Fenced code blocks of a README that are code, not a shell or install line (docs.readme.v1), in order."""
    out = []
    for lang, body in re.findall(r"(?ms)^[ \t]*```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n(.*?)^[ \t]*```", readme or ""):
        lang, body = lang.lower(), body.strip("\n")
        if not body.strip() or lang in ("sh", "bash", "shell", "console", "zsh", "powershell", "cmd", "text", "txt"):
            continue
        if re.fullmatch(r"(?s)\s*(?:\$\s*)?(?:npm|yarn|pnpm|bun|npx)\s[^\n]*\s*", body):
            continue
        out.append(body[:2000])   # newlines kept: it is code
    return out


def readme_example(readme: str) -> str:
    """The first of readme_examples, or ''."""
    found = readme_examples(readme)
    return found[0] if found else ""


_SUFFIX = {"incorporated": "inc", "corporation": "corp", "company": "co", "limited": "ltd", "the": "",
           "aktiengesellschaft": "ag"}
_LEGAL_FORMS = {"inc", "corp", "co", "ltd", "llc", "plc", "ag", "gmbh", "sa", "nv", "bv", "se", "spa", "kk", "lp",
                "llp", "pte", "incorporated", "corporation", "company", "limited", "aktiengesellschaft",
                "as", "asa", "ab", "oy", "oyj", "aps", "kgaa", "sarl", "srl", "sas", "bhd", "berhad", "pty", "ltda"}
# Multi-word legal forms, matched on the joined words before the trailing forms are dropped.
_LEGAL_PHRASES = ((r"\bpublic ltd co\b", "plc"), (r"\bco kgaa\b", "kgaa"), (r"\bpty ltd\b", "pty ltd"))
# Trailing words a group adds to its brand. "international" is not one: "Philips International B.V." is a
# subsidiary, not Philips.
_GENERIC = {"holding", "holdings", "group", "the"}


def name_keys(name: str) -> tuple[str, str, str]:
    """(exact, core, loose) keys of a company name. Exact: case, accents, punctuation and suffix spellings do
    not matter (Nestlé S.A. = NESTLE SA, Inc. = Incorporated). Core: trailing legal forms dropped (Allianz SE ->
    allianz). Loose: also leading "the" and trailing holding/group words (ASML Holding N.V. -> asml)."""
    import unicodedata
    text = unicodedata.normalize("NFKD", (name or "").replace("&amp;", "&"))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"(?<=\b[a-z])\.(?=[a-z]\b)", "", text)          # S.A. / N.V. / P.L.C. -> sa / nv / plc
    text = re.sub(r"(?<=\b[a-z])/(?=[a-z]\b)", "", text)           # A/S -> as
    words = [w for w in (_SUFFIX.get(w, w) for w in re.sub(r"[^0-9a-z&]+", " ", text).split()) if w]
    joined = " ".join(words)
    for pattern, form in _LEGAL_PHRASES:
        joined = re.sub(pattern, form, joined)
    words = joined.split()
    exact = " ".join(words)
    core = list(words)
    while len(core) > 1 and (core[-1] in _LEGAL_FORMS or core[-1] == "&"):
        core.pop()
    loose = [w for w in core if w != "the"] or core
    while len(loose) > 1 and (loose[-1] in _GENERIC | _LEGAL_FORMS or loose[-1] == "&"):
        loose.pop()
    return exact, " ".join(core), " ".join(loose)


def company_key(name: str) -> str:
    """Exact legal-name key (see name_keys)."""
    return name_keys(name)[0]


def tiered_match(rows, wanted, keys_of, preferred):
    """The single row matching WANTED at the strictest tier that matches at all (exact, core, loose).
    Preferred rows (e.g. an issued LEI) win a tie; a tie that remains is an error, never a guess."""
    for tier in range(3):
        hits = [r for r in rows if any(k[tier] == wanted[tier] for k in keys_of(r))]
        if not hits:
            continue
        best = [r for r in hits if preferred(r)] or hits
        if len(best) > 1:
            raise FallbackUnavailable("not_found", "Several records share this name; add the country or the full legal name.")
        return best[0]
    return None


REGISTRY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*/[A-Za-z0-9._-]{1,150}")

STREET_TYPES = {"avenue": "ave", "ave": "ave", "av": "ave", "street": "st", "st": "st", "drive": "dr", "dr": "dr",
                "boulevard": "blvd", "blvd": "blvd", "road": "rd", "rd": "rd", "parkway": "pkwy", "pkwy": "pkwy",
                "place": "pl", "pl": "pl", "plaza": "plz", "plz": "plz", "lane": "ln", "ln": "ln", "court": "ct",
                "ct": "ct", "way": "way", "highway": "hwy", "hwy": "hwy", "circle": "cir", "cir": "cir",
                "terrace": "ter", "ter": "ter", "square": "sq", "sq": "sq", "trail": "trl", "trl": "trl"}


ZIP = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def title_words(title: str) -> list[str]:
    """Words of a title for comparison: case, apostrophes and punctuation aside ("BJ's Restaurants" = "Bjs Restaurants")."""
    return re.findall(r"[a-z0-9]+", title.casefold().replace("'", "").replace("\u2019", ""))


def same_street(asked: str, matched: str) -> bool:
    """The house number and, when both name one, the street type of the first address part agree; and when both
    give a ZIP code, the ZIP codes agree (11-16: "24 Beacon St, Boston, MA 02133" matched 24 BEACON ST 02136, 12 km
    away; on the 36 checked answers this drops the 2 wrong ones and keeps all 34 right ones)."""
    def parts(text):
        words = re.findall(r"[a-z0-9]+", text.split(",")[0].lower())
        number = words[0] if words and words[0].isdigit() else None
        kinds = [STREET_TYPES[w] for w in words[1:] if w in STREET_TYPES]
        zips = ZIP.findall(text.split(",", 1)[1]) if "," in text else []
        return number, kinds[-1] if kinds else None, zips[-1] if zips else None
    n1, t1, z1 = parts(asked)
    n2, t2, z2 = parts(matched)
    return ((n1 is None or n1 == n2) and (t1 is None or t2 is None or t1 == t2)
            and (z1 is None or z2 is None or z1 == z2))


# An address that names another country is not sent to the U.S. Census Geocoder (it covers U.S. addresses only).
NON_US = re.compile(r"(?i),\s*(japan|china|korea|south korea|india|germany|france|spain|italy|united kingdom|uk|england|"
                    r"canada|mexico|brazil|australia|russia|netherlands|switzerland|sweden|norway|poland|turkey|"
                    r"indonesia|thailand|vietnam|philippines|singapore|taiwan|argentina|chile|colombia|peru|egypt|"
                    r"nigeria|south africa|kenya|israel|saudi arabia|united arab emirates|uae)\s*\.?$")

# Concepts read from XBRL company facts for the latest annual report, first match wins (US GAAP, then IFRS).
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
FACT_CONCEPTS = (
    ("revenue", (("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                 ("us-gaap", "SalesRevenueNet"), ("ifrs-full", "Revenue"))),
    ("net income", (("us-gaap", "NetIncomeLoss"), ("us-gaap", "ProfitLoss"), ("ifrs-full", "ProfitLoss"))),
    ("total assets", (("us-gaap", "Assets"), ("ifrs-full", "Assets"))),
)


def _money(value: float, unit: str) -> str:
    size = abs(value)
    for limit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if size >= limit:
            return f"{unit} {value / limit:,.1f} {word}"
    return f"{unit} {value:,.0f}"


def annual_facts(raw: dict, url: str = "") -> str | None:
    """One sentence with revenue, net income and total assets as reported in the latest annual report (10-K, 20-F
    or 40-F) in EDGAR's XBRL company facts. Each value names its standard (US GAAP or IFRS), concept and currency;
    the fiscal year end, form, filing date and the facts URL are stated; a value not reported stays empty (PM 12:55)."""
    facts = raw.get("facts") if isinstance(raw, dict) else None
    if not isinstance(facts, dict):
        return None
    found, latest = {}, None
    for label, concepts in FACT_CONCEPTS:
        best = None   # the newest year across the concepts (a filer may stop using one), earlier concept on a tie
        for rank, (taxonomy, concept) in enumerate(concepts):
            units = ((facts.get(taxonomy) or {}).get(concept) or {}).get("units") or {}
            rows = [(u, r) for u, items in units.items() if isinstance(items, list) for r in items
                    if isinstance(r, dict) and r.get("form") in ANNUAL_FORMS and r.get("fp") == "FY"
                    and isinstance(r.get("val"), (int, float)) and isinstance(r.get("end"), str)
                    and isinstance(r.get("filed"), str)
                    and (label == "total assets" or str(r.get("start") or "") < r["end"])]
            if not rows:
                continue
            unit, row = max(rows, key=lambda x: (x[1]["end"], x[1]["filed"]))
            if best is None or (row["end"], row["filed"], -rank) > (best[0]["end"], best[0]["filed"], -best[4]):
                best = (row, unit, taxonomy, concept, rank)
        if best:
            found[label] = best[:4]
            if latest is None or (best[0]["end"], best[0]["filed"]) > (latest["end"], latest["filed"]):
                latest = best[0]
    if not found or latest is None:
        return None
    parts = []
    for label, _ in FACT_CONCEPTS:
        hit = found.get(label)
        if hit and hit[0]["end"] == latest["end"]:
            row, unit, taxonomy, concept = hit
            standard = "US GAAP" if taxonomy == "us-gaap" else "IFRS"
            parts.append(f"{label} {_money(float(row['val']), _text(unit, 10))} ({standard} {concept})")
        else:
            parts.append(f"{label} not reported for that year")
    where = f" ({url})" if url else ""
    return (f"Latest annual report facts from EDGAR XBRL company facts{where}: {_text(latest.get('form'), 10)} for "
            f"the fiscal year ended {latest['end'][:10]}, filed {latest['filed'][:10]}; {'; '.join(parts)}.")


def sec_lookup(index, name: str) -> int:
    for tier, key in enumerate(name_keys(name)):
        ciks = index[tier].get(key) or set()
        if len(ciks) == 1:
            return next(iter(ciks))
        if len(ciks) > 1:
            raise FallbackUnavailable("not_found", "Several SEC companies share this name; use the ticker or CIK.")
    raise FallbackUnavailable("not_found", "No SEC company with a ticker has this name.")


def core_name(name: str) -> str:
    """The name without trailing legal-form words ("Amazon.com, Inc." -> "Amazon.com"), for a wider
    GLEIF search (never used for matching)."""
    words = [w.strip(",;") for w in name.split()]
    while len(words) > 1 and re.sub(r"\W", "", words[-1]).lower() in _LEGAL_FORMS:
        words.pop()
    return " ".join(w for w in words if w)


WB_ALIASES = {  # common name -> (World Bank code, label, unit); the contract fixes population and gdp
    "population": ("SP.POP.TOTL", "Population, total", "people"),
    "gdp": ("NY.GDP.MKTP.CD", "GDP", "current US dollars"),
    "gdp per capita": ("NY.GDP.PCAP.CD", "GDP per capita", "current US dollars"),
    "gdp growth": ("NY.GDP.MKTP.KD.ZG", "GDP growth", "annual %"),
    "inflation": ("FP.CPI.TOTL.ZG", "Inflation, consumer prices", "annual %"),
    "unemployment": ("SL.UEM.TOTL.ZS", "Unemployment", "% of labor force (modeled ILO estimate)"),
    "life expectancy": ("SP.DYN.LE00.IN", "Life expectancy at birth", "years"),
    "population growth": ("SP.POP.GROW", "Population growth", "annual %"),
    "area": ("AG.SRF.TOTL.K2", "Surface area", "square kilometers"),
    "internet users": ("IT.NET.USER.ZS", "Individuals using the Internet", "% of population"),
    "capital": ("CAPITAL", "Capital city", None), "capital city": ("CAPITAL", "Capital city", None),
}
WB_ALIASES.update({"gross domestic product": WB_ALIASES["gdp"], "total population": WB_ALIASES["population"],
                   "unemployment rate": WB_ALIASES["unemployment"], "inflation rate": WB_ALIASES["inflation"]})

def expires_in(header, wall_now) -> float:
    """Seconds until the source's Expires time, between 60 s and 1 h (missing or past: 10 minutes)."""
    from email.utils import parsedate_to_datetime
    try:
        left = parsedate_to_datetime(header).timestamp() - wall_now
    except (TypeError, ValueError):
        return 600.0
    return min(3600.0, max(60.0, left)) if left > 0 else 600.0


_SYMBOL_WORDS = ("partly", "cloudy", "clear", "sky", "fair", "light", "heavy", "rain", "sleet", "snow",
                 "showers", "and", "thunder", "fog")


def symbol_text(code: str) -> str:
    """MET symbol code -> words ("lightrainshowers_day" -> "light rain showers")."""
    base, words = (code or "").split("_")[0], []
    while base:
        word = next((w for w in _SYMBOL_WORDS if base.startswith(w)), None)
        if not word:
            return _text(code, 40)
        words.append(word)
        base = base[len(word):]
    return " ".join(words)


def met_forecast(raw: dict, now: datetime):
    """Locationforecast compact -> weather.forecast.v1 output, using the hour nearest to now."""
    props = raw["properties"]
    series = [t for t in props["timeseries"] if isinstance(t, dict)]
    def gap(t):
        return abs((datetime.fromisoformat(t["time"].replace("Z", "+00:00")) - now).total_seconds())
    point = min(series[:6], key=gap)
    details = point["data"]["instant"]["details"]
    temp = details["air_temperature"]
    if not isinstance(temp, (int, float)):
        raise ValueError("no temperature")
    parts = []
    nxt1, nxt6 = point["data"].get("next_1_hours") or {}, point["data"].get("next_6_hours") or {}
    if nxt1.get("summary", {}).get("symbol_code"):
        parts.append("next hour: " + symbol_text(nxt1["summary"]["symbol_code"]))
    if nxt6.get("summary", {}).get("symbol_code"):
        rain = (nxt6.get("details") or {}).get("precipitation_amount")
        parts.append("next 6 hours: " + symbol_text(nxt6["summary"]["symbol_code"])
                     + (f", {rain} mm precipitation" if isinstance(rain, (int, float)) else ""))
    if isinstance(details.get("wind_speed"), (int, float)):
        parts.append(f"wind {details['wind_speed']} m/s")
    if isinstance(details.get("relative_humidity"), (int, float)):
        parts.append(f"humidity {details['relative_humidity']}%")
    out = {"temperature_c": float(temp), "forecast": ("Temperature %.1f °C; " % temp + "; ".join(parts))[:4000],
           "time": _text(point["time"], 40), "source": "Based on data from MET Norway (CC BY 4.0, https://api.met.no/doc/License)"}
    return out, {"MET Norway": _text(props.get("meta", {}).get("updated_at"), 40) or None}


# Release time of each pinned library version: the "data as of" date of its holiday rules.
HOLIDAYS_RELEASES = {"0.108": datetime(2026, 11, 2, 22, 32, 10, tzinfo=timezone.utc).timestamp()}  # PyPI upload


def holiday_country(place: str, countries: dict) -> str | None:
    """Country code from an ISO alpha-2/alpha-3 code or an English country name ("South Korea")."""
    key = re.sub(r"[^a-z]", "", place.lower())
    for module, entry in countries.items():
        class_name, alpha2, alpha3 = entry[0], entry[1], entry[2]
        names = {re.sub(r"[^a-z]", "", module), class_name.lower(), alpha2.lower(), alpha3.lower()}
        if key in names:
            return alpha2
    return None


def country_name(code: str, countries: dict) -> str:
    for module, entry in countries.items():
        if entry[1] == code:
            return module.replace("_", " ").title()
    return code


AI_CRAWLERS = ("GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "PerplexityBot", "CCBot")

ANSWER_CUES = (  # (question pattern, sentence pattern) for extractive answers
    (r"\bwho\b", r"\b(?:created|designed|developed|invented|founded|wrote|written|authored|conceived|began|by)\b"),
    (r"\bwhen\b|\bwhat year\b", r"\b(?:1[0-9]{3}|20[0-9]{2})\b"),
    (r"\bhow (?:tall|high|long|big|deep|far|heavy|old|many|much)\b",
     r"\b\d[\d,.]*\s?(?:m|km|metres|meters|feet|ft|kg|tonnes|years|°C|°F|%|percent|million|billion)\b"),
    (r"\bhow (?:tall|high)\b", r"\b(?:height|elevation|tall|high)\b"),
    (r"\bcapital\b", r"\bcapital\b"),
    (r"\bwhere\b", r"\b(?:located|lies|situated|in|on)\s+(?:the\s+)?[A-Z][a-z]+"),
)
SUBJECT = re.compile(r"^(?P<lead>(?:what|who)\s+(?:is|are|was|were)\s+(?:an?\s+|the\s+)?|(?:tell me about|explain|define)\s+)?"
                     r"(?P<s>[^?]{2,120}?)\s*(?P<q>\?)?$", re.I)


def subject_title(question: str) -> str | None:
    """The page title to try first: "What is anomaly detection?" -> "Anomaly detection"; a short bare topic stays
    itself. Longer questions (more than 6 words left) have no single subject."""
    m = SUBJECT.match(" ".join(question.split()))
    if not m or (m["q"] and not m["lead"]):      # "Who created X?" is a question, not a title
        return None
    subject = m["s"].strip(" .")
    if not subject or len(subject.split()) > 6:
        return None
    return subject[0].upper() + subject[1:]


def search_terms(question: str) -> str:
    """Wikipedia search text: the question itself, except "capital (city) of X" searches X (the full question
    ranks "Capital punishment in X" first)."""
    m = re.search(r"\bcapital(?: city)? of (.+?)\??$", question, re.I)
    return (m[1] if m else question.rstrip("?"))[:300]


QUESTION_WORDS = frozenset("what who whom whose which when where why how does did do was were is are can could "
                           "the city name".split())

# Unit -> (dimension, factor to the SI base unit). Exact definitions (NIST SP 811); US customary units.
UNITS = {
    "meter": ("length", 1.0), "kilometer": ("length", 1000.0), "centimeter": ("length", 0.01), "millimeter": ("length", 0.001),
    "mile": ("length", 1609.344), "yard": ("length", 0.9144), "foot": ("length", 0.3048), "inch": ("length", 0.0254),
    "nautical mile": ("length", 1852.0),
    "kilogram": ("mass", 1.0), "gram": ("mass", 0.001), "milligram": ("mass", 1e-6), "tonne": ("mass", 1000.0),
    "pound": ("mass", 0.45359237), "ounce": ("mass", 0.028349523125), "stone": ("mass", 6.35029318), "short ton": ("mass", 907.18474),
    "liter": ("volume", 0.001), "milliliter": ("volume", 1e-6), "cubic meter": ("volume", 1.0),
    "gallon": ("volume", 0.003785411784), "quart": ("volume", 0.000946352946), "pint": ("volume", 0.000473176473),
    "cup": ("volume", 0.0002365882365), "fluid ounce": ("volume", 2.95735295625e-5),
    "square meter": ("area", 1.0), "square kilometer": ("area", 1e6), "hectare": ("area", 1e4), "acre": ("area", 4046.8564224),
    "square foot": ("area", 0.09290304), "square mile": ("area", 2589988.110336),
    "meter per second": ("speed", 1.0), "kilometer per hour": ("speed", 1000 / 3600), "mile per hour": ("speed", 0.44704),
    "knot": ("speed", 1852 / 3600),
    "second": ("time", 1.0), "minute": ("time", 60.0), "hour": ("time", 3600.0), "day": ("time", 86400.0), "week": ("time", 604800.0),
    "byte": ("data", 1.0), "kilobyte": ("data", 1e3), "megabyte": ("data", 1e6), "gigabyte": ("data", 1e9), "terabyte": ("data", 1e12),
    "kibibyte": ("data", 1024.0), "mebibyte": ("data", 1024.0 ** 2), "gibibyte": ("data", 1024.0 ** 3), "bit": ("data", 0.125),
    "celsius": ("temperature", None), "fahrenheit": ("temperature", None), "kelvin": ("temperature", None),
}
UNIT_ALIASES = {"m": "meter", "metre": "meter", "km": "kilometer", "kilometre": "kilometer", "cm": "centimeter", "mm": "millimeter",
                "mi": "mile", "yd": "yard", "ft": "foot", "feet": "foot", "in": "inch", "inches": "inch", "nmi": "nautical mile",
                "kg": "kilogram", "g": "gram", "mg": "milligram", "t": "tonne", "metric ton": "tonne", "lb": "pound", "lbs": "pound",
                "oz": "ounce", "l": "liter", "litre": "liter", "ml": "milliliter", "gal": "gallon", "us gallon": "gallon",
                "fl oz": "fluid ounce", "m2": "square meter", "km2": "square kilometer", "ha": "hectare", "sq ft": "square foot",
                "m/s": "meter per second", "km/h": "kilometer per hour", "kph": "kilometer per hour", "mph": "mile per hour",
                "kn": "knot", "s": "second", "sec": "second", "min": "minute", "h": "hour", "hr": "hour",
                "b": "byte", "kb": "kilobyte", "mb": "megabyte", "gb": "gigabyte", "tb": "terabyte", "kib": "kibibyte",
                "mib": "mebibyte", "gib": "gibibyte", "c": "celsius", "°c": "celsius", "f": "fahrenheit", "°f": "fahrenheit",
                "k": "kelvin"}


def unit_name(text: str) -> str:
    key = " ".join(text.strip().lower().split())
    if key in UNIT_ALIASES:
        return UNIT_ALIASES[key]
    if key in UNITS:
        return key
    for plural, single in (("ies", "y"), ("es", ""), ("s", "")):  # miles, inches, centuries
        if key.endswith(plural) and key[: -len(plural)] + single in UNITS:
            return key[: -len(plural)] + single
    key = key.replace("kilometres", "kilometer").replace("metres", "meter")
    if key in UNITS:
        return key
    raise ValueError(f"Unknown unit: {text[:40]}")


def convert_units(value: float, src: str, dst: str):
    a, b = unit_name(src), unit_name(dst)
    (dim_a, fa), (dim_b, fb) = UNITS[a], UNITS[b]
    if dim_a != dim_b:
        raise ValueError(f"Cannot convert {dim_a} ({a}) to {dim_b} ({b}).")
    if dim_a == "temperature":
        kelvin = {"celsius": value + 273.15, "fahrenheit": (value - 32) * 5 / 9 + 273.15, "kelvin": value}[a]
        return {"celsius": kelvin - 273.15, "fahrenheit": (kelvin - 273.15) * 9 / 5 + 32, "kelvin": kelvin}[b], a, b
    return value * fa / fb, a, b


STOPWORDS = frozenset("a an and are as at be by for from in is it of on or the to with all you we our this that "
                      "using via towards".split())


def lead(text: str, limit: int) -> str:
    """The first paragraphs of an extract, cut at a sentence end within ``limit`` characters."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + " ..."


def arxiv_entries(body: bytes) -> list[dict]:
    """Atom feed -> papers.search items. Feeds with a DTD or entities are refused (no entity expansion)."""
    import xml.etree.ElementTree as ET
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise ValueError("DTD in feed")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(body)
    items = []
    for entry in root.findall("a:entry", ns)[:50]:
        raw_id = (entry.findtext("a:id", "", ns) or "").strip()
        m = re.fullmatch(r"https?://arxiv\.org/abs/([a-z.-]*/?[0-9.]+?)(v[0-9]+)?", raw_id)
        title = _text(entry.findtext("a:title", "", ns), 4000)
        if not m or not title:
            continue
        item = {"title": title, "id": "arXiv:" + m[1], "url": "https://arxiv.org/abs/" + m[1]}
        year = (entry.findtext("a:published", "", ns) or "")[:4]
        if year.isdigit():
            item["year"] = int(year)
        items.append(item)
    return items


def ecb_rates(body: bytes):
    """ECB daily XML -> (date, {currency: units per euro}). Feeds with a DTD or entities are refused."""
    import xml.etree.ElementTree as ET
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise ValueError("DTD in feed")
    root = ET.fromstring(body)
    day, rates = None, {}
    for cube in root.iter():
        if cube.tag.endswith("Cube") and cube.get("time"):
            day = cube.get("time")
        if cube.tag.endswith("Cube") and cube.get("currency") and cube.get("rate"):
            code, value = cube.get("currency"), float(cube.get("rate"))
            if re.fullmatch(r"[A-Z]{3}", code) and value > 0:
                rates[code] = value
    if not day or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or len(rates) < 10:
        raise ValueError("unexpected ECB feed")
    return day, rates


def tz_zone(text: str) -> str | None:
    """An IANA zone from a zone name or a city that is a zone's last part ("new york" -> America/New_York)."""
    import zoneinfo
    zones = zoneinfo.available_timezones()
    text = (text or "").strip()
    if text in zones:
        return text
    key = re.sub(r"[\s_-]+", "_", text.lower())
    exact = {z.lower(): z for z in zones}
    if key in exact:
        return exact[key]
    cities = {}
    for z in zones:
        if "/" in z and not z.startswith(("Etc/", "SystemV/", "US/")):
            cities.setdefault(z.rsplit("/", 1)[1].lower(), []).append(z)
    found = cities.get(key) or []
    return sorted(found)[0] if len(found) >= 1 and len({z.split("/")[0] for z in found}) == 1 else None


def tz_version() -> str | None:
    import zoneinfo
    for root in zoneinfo.TZPATH:
        try:
            first = (Path(root) / "tzdata.zi").read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            m = re.search(r"version (\S+)", first)
            if m:
                return m[1]
        except (OSError, IndexError):
            continue
    try:
        import tzdata
        return tzdata.IANA_VERSION
    except Exception:
        return None


def pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name or "").lower()


_DEFAULT: FallbackAgents | None = None
_DEFAULT_LOCK = threading.Lock()


def run(agent_id: str, arguments: dict) -> dict:
    """Entry point for the necklace runner (``kind: agentcon`` chain links)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = FallbackAgents()
    return _DEFAULT.execute(agent_id, arguments)


class SlotAnswer(dict):
    """A slot's contract-shaped answer. The envelope's attribution rides along as an attribute, not a key, so the
    slot normalizer sees exactly the contract fields while the runner can still carry sources and licenses into
    the necklace output (precision review R29, PM 11-15)."""
    attribution: dict | None = None


def attribution(envelope: dict) -> dict:
    """Who answered and under which terms: agent, sources (name, URL, license, notice), retrieval time, cache state
    and data freshness, plus per-field sources when the answer mixes them."""
    out = {"agent": envelope.get("agent"), "tool": envelope.get("tool"),
           "sources": [dict(s) for s in envelope.get("sources") or []],
           "retrieved_at": envelope.get("retrieved_at"), "cache": dict(envelope.get("cache") or {}),
           "freshness": dict(envelope.get("freshness") or {}), "partial": bool(envelope.get("partial"))}
    if envelope.get("field_sources"):
        out["field_sources"] = envelope["field_sources"]
    return out


def slot_output(envelope: dict) -> dict:
    """The contract-shaped part a slot keeps, carrying the envelope's attribution (see SlotAnswer)."""
    out = SlotAnswer(envelope["result"])
    out.attribution = attribution(envelope)
    return out
