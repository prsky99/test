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
from urllib.parse import quote

import jsonschema

from .catalog import SPECS, contract
from .limits import SourceBusy, limiters as make_limiters
from .net import SourceError, get
from .nvd_store import CVE_ID, Snapshot, _text, record as nvd_record
from .versions import in_range

CODES = ("invalid_input", "not_found", "rate_limited", "source_unavailable", "invalid_output", "stale")
# Data age (PM 11-14, user emphasis): every answer states when its source data was updated and how
# old our copy is. A copy older than MAX_AGE is an error ("stale") so the slot moves to the next member.
MAX_AGE = {"nvd-cve": 6 * 3600, "cve-org": 24 * 3600, "cisa-kev": 24 * 3600, "github-advisory": 6 * 3600,
           "package-registry": 6 * 3600, "depsdev-package": 24 * 3600, "gleif-lei": 24 * 3600,
           "sec-edgar": 24 * 3600, "wikipedia-summary": 24 * 3600, "arxiv-search": 48 * 3600}
TTL = {"nvd-cve": (6 * 3600, 6 * 3600), "cve-org": (6 * 3600, 24 * 3600), "github-advisory": (3600, 6 * 3600),
       "epss": (6 * 3600, 48 * 3600), "package-registry": (3600, 6 * 3600), "depsdev-package": (6 * 3600, 24 * 3600),
       "gleif-lei": (6 * 3600, 24 * 3600), "sec-edgar": (6 * 3600, 24 * 3600), "sec-tickers": (6 * 3600, 24 * 3600),
       "wikipedia-summary": (6 * 3600, 24 * 3600), "arxiv-search": (24 * 3600, 48 * 3600)}  # (serve from cache without asking, longest a cached copy may serve)
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
        result, cache, partial, as_of = handler(arguments, lambda: self.budget - (self.clock() - started))
        if cache["age_seconds"] > MAX_AGE[agent_id]:
            raise FallbackUnavailable("stale", f"Our copy of the source is {cache['age_seconds']} s old, over the "
                                               f"{MAX_AGE[agent_id]} s limit. No answer was given from it.")
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
                "cache": cache, "partial": bool(partial),
                "freshness": {"data_as_of": as_of, "age_seconds": cache["age_seconds"],
                              "max_age_seconds": MAX_AGE[agent_id]}}

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
        package, ecosystem = self._package_args(args)
        system = {"npm": "npm", "PyPI": "pypi"}[ecosystem]
        base = "https://api.deps.dev/v3/systems/" + system + "/packages/" + quote(package, safe="")

        def live(rem):
            raw = self._get_json(base, rem, limit=4 * 1024 * 1024)
            default = next((v for v in raw.get("versions") or [] if isinstance(v, dict) and v.get("isDefault")), None)
            if not default:
                raise FallbackUnavailable("not_found", "deps.dev has no default version for this package.")
            version = default["versionKey"]["version"]
            out = {"latest_version": _text(version, 64), "deprecated": bool(default.get("isDeprecated")),
                   "source": "deps.dev"}
            if _text(default.get("publishedAt"), 40):
                out["released_at"] = _text(default.get("publishedAt"), 40)
            as_of = {"deps.dev": _now_iso(self.utc_now())}
            partial = False
            try:
                doc = self._get_json(base + "/versions/" + quote(version, safe=""), rem, limit=2 * 1024 * 1024)
                project = next((p["projectKey"]["id"] for p in doc.get("relatedProjects") or []
                                if isinstance(p, dict) and p.get("relationType") == "SOURCE_REPO"
                                and isinstance((p.get("projectKey") or {}).get("id"), str)), None)
                if project and re.fullmatch(r"(github\.com|gitlab\.com|bitbucket\.org)/[\w.-]+/[\w.-]+", project):
                    out["repository"] = "https://" + project
                    proj = self._get_json("https://api.deps.dev/v3/projects/" + quote(project, safe=""), rem,
                                          limit=1024 * 1024)
                    card = proj.get("scorecard") or {}
                    if isinstance(card.get("overallScore"), (int, float)) and 0 <= card["overallScore"] <= 10:
                        out["scorecard"] = float(card["overallScore"])
                        out["source"] = "deps.dev; OpenSSF Scorecard"
                        as_of["OpenSSF Scorecard"] = _text(card.get("date"), 40) or None
            except (SourceBusy, SourceError, FallbackUnavailable, ValueError, KeyError, TypeError):
                partial = True  # version facts stand; repository/scorecard could not be read in time
            return out, as_of, partial
        (out, as_of, partial), cache = self._cached(("depsdev-package", ecosystem, package.lower()),
                                                    TTL["depsdev-package"], live, remaining)
        return out, cache, partial, as_of

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
            key = company_key(name)
            exact = [r for r in search(core_name(name), rem) if any(company_key(n) == key for n in names(r))]
            if not exact and core_name(name) != name and rem() > 1.2:
                exact = [r for r in search(name, rem) if any(company_key(n) == key for n in names(r))]
            issued = [r for r in exact if (r.get("registration") or {}).get("status") == "ISSUED"] or exact
            if not issued:
                raise FallbackUnavailable("not_found", "GLEIF has no LEI record with this exact legal name.")
            if len(issued) > 1:
                raise FallbackUnavailable("not_found", "Several LEI records share this legal name; add the country.")
            rec = issued[0]
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

    def _sec_edgar(self, args, remaining):
        name, country = self._company_args(args)

        def tickers(rem):
            raw = self._get_json("https://www.sec.gov/files/company_tickers.json", rem, limit=4 * 1024 * 1024,
                                 not_found=())
            index = {}
            for row in raw.values():
                if isinstance(row, dict) and isinstance(row.get("cik_str"), int) and isinstance(row.get("title"), str):
                    # EDGAR titles may carry a state tag ("QUALCOMM INC/DE"); it is not part of the name.
                    title = re.sub(r"\s*/[A-Z]{2,3}/?$", "", row["title"].strip())
                    index.setdefault(company_key(title), set()).add(row["cik_str"])
            if len(index) < 1000:
                raise ValueError("ticker list too small")
            return index, _now_iso(self.utc_now())
        (index, list_as_of), list_cache = self._cached(("sec-tickers",), TTL["sec-tickers"], tickers, remaining)
        ciks = index.get(company_key(name)) or set()
        if not ciks:
            raise FallbackUnavailable("not_found", "No SEC company with a ticker has this name.")
        if len(ciks) > 1:
            raise FallbackUnavailable("not_found", "Several SEC companies share this name.")
        cik = next(iter(ciks))

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
            if len(pages) != 1 or pages[0].get("missing") or pages[0].get("invalid"):
                raise FallbackUnavailable("not_found", "Wikipedia has no article with this title.")
            page = pages[0]
            if "disambiguation" in (page.get("pageprops") or {}):
                raise FallbackUnavailable("not_found", "This title is a disambiguation page; use a more specific title.")
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

    def _arxiv_search(self, args, remaining):
        query = " ".join(args["query"].split())
        limit = args.get("limit", 5)
        words = re.findall(r"[A-Za-z0-9]+", query.lower())
        terms = [w for w in words if w not in STOPWORDS] or words
        if not terms or len(terms) > 12:
            raise FallbackUnavailable("invalid_input", "Use 1 to 12 plain keywords.")

        def live(rem):
            response = get("https://export.arxiv.org/api/query", limiters=self.limiters, http=self.http,
                           seconds=max(0.1, rem() - 0.1), limit=2 * 1024 * 1024, accept="application/atom+xml",
                           params={"search_query": " AND ".join("all:" + t for t in terms),
                                   "start": 0, "max_results": 50})
            return arxiv_entries(response.content), _now_iso(self.utc_now())
        (entries, as_of), cache = self._cached(("arxiv-search", " ".join(terms)), TTL["arxiv-search"], live, remaining)
        # The API's own order does not favor title matches: rank by query words in the title, then by fewer
        # extra title words, then by the API order.
        def rank(pair):
            title_words = re.findall(r"[a-z0-9]+", pair[1]["title"].lower())
            hit = sum(w in set(title_words) for w in set(words))
            return (-hit, len([w for w in title_words if w not in set(words)]), pair[0])
        ranked = sorted(enumerate(entries), key=rank)
        items, seen = [], set()
        for _, item in ranked:
            key = item["title"].casefold()
            if key not in seen:
                seen.add(key)
                items.append(item)
        return {"items": items[:limit], "source": "arXiv"}, cache, False, {"arXiv": as_of}

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


_SUFFIX = {"incorporated": "inc", "corporation": "corp", "company": "co", "limited": "ltd", "the": "",
           "aktiengesellschaft": "ag"}
_LEGAL_FORMS = {"inc", "corp", "co", "ltd", "llc", "plc", "ag", "gmbh", "sa", "nv", "bv", "se", "spa", "kk", "lp",
                "llp", "pte", "incorporated", "corporation", "company", "limited", "aktiengesellschaft"}


def company_key(name: str) -> str:
    """Legal-name key: case, punctuation and common suffix spellings do not matter (Inc. = Incorporated)."""
    words = re.sub(r"[^0-9a-z&]+", " ", (name or "").lower().replace("&amp;", "&")).split()
    return " ".join(w for w in (_SUFFIX.get(w, w) for w in words) if w)


def core_name(name: str) -> str:
    """The name without trailing legal-form words ("Amazon.com, Inc." -> "Amazon.com"), for a wider
    GLEIF search (never used for matching)."""
    words = [w.strip(",;") for w in name.split()]
    while len(words) > 1 and re.sub(r"\W", "", words[-1]).lower() in _LEGAL_FORMS:
        words.pop()
    return " ".join(w for w in words if w)


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


def slot_output(envelope: dict) -> dict:
    """The contract-shaped part a slot keeps."""
    return envelope["result"]
