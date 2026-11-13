"""Gold answer sets for necklaces, frozen from public sources.

Each necklace gets 90 cases: ``tuning`` (30, used while building), and two
held-out rounds ``holdout-r1`` and ``holdout-r2`` (30 each) that only the ops
launch gate runs, four hours apart (PM 2026-11-14: 57/60 in total and 28/30 in
each round). The split is stratified and deterministic, and the held-out files
are never read by the tuning tools.

Truth comes from the public source of record at build time and is stored with
its URL and fetch time:

- package-risk-audit: OSV (advisories, aliases folded) and the npm / PyPI
  registries (latest version)
- cve-incident-brief: CISA KEV catalog, NVD CVE API 2.0 (CVSS, primary score;
  cvelistV5 CNA/ADP metrics as the fallback when NVD fails), FIRST EPSS

Calls are read-only GETs/POSTs to public endpoints, one at a time per host with
spacing, backing off on 429 and 5xx. No keys, no personal data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

USER_AGENT = "AgentValCon-GoldSet/1.0 (+https://agentconcierge.biz; contact@agentconcierge.biz)"
SPLITS = ("tuning", "holdout-r1", "holdout-r2")
PER_SPLIT = 30
SEED = "necklace-gold-v1"
# Minimum seconds between calls to one host. NVD asks keyless clients for at most
# 5 requests in 30 seconds.
SPACING = {"services.nvd.nist.gov": 6.5, "api.osv.dev": 0.5, "registry.npmjs.org": 0.5, "pypi.org": 0.5,
           "api.first.org": 1.0, "www.cisa.gov": 1.0, "raw.githubusercontent.com": 1.0,
           "www.sec.gov": 1.0, "api.gleif.org": 1.0}

NPM = ["lodash", "minimist", "express", "axios", "jsonwebtoken", "moment", "handlebars", "marked", "node-fetch",
       "ws", "semver", "tar", "qs", "follow-redirects", "ejs", "jquery", "underscore", "shell-quote", "glob-parent",
       "path-parse", "y18n", "yargs-parser", "trim-newlines", "ini", "hosted-git-info", "postcss", "nth-check",
       "json5", "word-wrap", "tough-cookie"]
PYPI = ["requests", "urllib3", "django", "flask", "jinja2", "pillow", "pyyaml", "cryptography", "werkzeug",
        "sqlalchemy", "numpy", "aiohttp", "tornado", "paramiko", "lxml", "twisted", "pyjwt", "markdown",
        "bleach", "babel", "starlette", "gunicorn", "scrapy", "notebook", "ansible"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Fetcher:
    """Polite JSON client: spacing per host, retries with backoff, generic User-Agent."""

    def __init__(self, spacing: dict | None = None, retries: int = 4, timeout: float = 40.0, sleep=time.sleep):
        self.spacing = dict(SPACING, **(spacing or {}))
        self.retries, self.timeout, self.sleep = retries, timeout, sleep
        self.last: dict[str, float] = {}
        self.calls = 0

    def _wait(self, host: str):
        gap = self.spacing.get(host, 1.0) - (time.monotonic() - self.last.get(host, -1e9))
        if gap > 0:
            self.sleep(gap)
        self.last[host] = time.monotonic()

    def json(self, url: str, body: dict | None = None):
        host = urlparse(url).hostname or ""
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(self.retries + 1):
            self._wait(host)
            self.calls += 1
            req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                         headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                  **({"Content-Type": "application/json"} if data else {})})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise
                retry = exc.headers.get("Retry-After") if exc.headers else None
                self.sleep(min(float(retry) if retry and retry.isdigit() else 2 ** (attempt + 2), 120))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                if attempt == self.retries:
                    raise
                self.sleep(2 ** (attempt + 2))
        return None


def fold(vulns: list[dict]) -> list[dict]:
    """One item per advisory: its id plus every alias (GHSA, CVE, PYSEC ...)."""
    items = []
    for v in vulns or []:
        ids = sorted({v["id"], *(v.get("aliases") or [])})
        items.append({"id": v["id"], "ids": ids})
    return sorted(items, key=lambda x: x["id"])


def pick_affected_version(vulns: list[dict], name: str) -> str | None:
    """A concrete affected version: an enumerated version if OSV lists them, else an 'introduced' event."""
    for v in sorted(vulns or [], key=lambda x: x.get("id", "")):
        for aff in v.get("affected") or []:
            if (aff.get("package") or {}).get("name", "").lower() != name.lower():
                continue
            versions = aff.get("versions") or []
            if versions:
                return versions[len(versions) // 2]
            for rng in aff.get("ranges") or []:
                for ev in rng.get("events") or []:
                    intro = ev.get("introduced")
                    if intro and intro != "0":
                        return intro
    return None


def osv_query(f: Fetcher, name: str, ecosystem: str, version: str | None = None) -> list[dict]:
    body = {"package": {"name": name, "ecosystem": ecosystem}}
    if version:
        body["version"] = version
    vulns, page = [], None
    for _ in range(10):
        if page:
            body["page_token"] = page
        out = f.json("https://api.osv.dev/v1/query", body) or {}
        vulns += out.get("vulns") or []
        page = out.get("next_page_token")
        if not page:
            break
    return vulns


def latest_version(f: Fetcher, name: str, ecosystem: str) -> str | None:
    if ecosystem == "npm":
        out = f.json(f"https://registry.npmjs.org/{quote(name, safe='@')}/latest") or {}
        return out.get("version")
    out = f.json(f"https://pypi.org/pypi/{quote(name)}/json") or {}
    return (out.get("info") or {}).get("version")


def package_cases(f: Fetcher) -> list[dict]:
    cases = []
    for ecosystem, names in (("npm", NPM), ("PyPI", PYPI)):
        for name in names:
            latest = latest_version(f, name, ecosystem)
            reg_url = (f"https://registry.npmjs.org/{name}/latest" if ecosystem == "npm"
                       else f"https://pypi.org/pypi/{name}/json")
            all_vulns = osv_query(f, name, ecosystem)
            old = pick_affected_version(all_vulns, name)
            for version, stratum in ((old, "vulnerable"), (latest, "current")):
                if not version:
                    continue
                truth_vulns = fold(osv_query(f, name, ecosystem, version))
                if stratum == "vulnerable" and not truth_vulns:
                    continue
                cases.append({
                    "case_id": f"{ecosystem}:{name}@{version}",
                    "task_type": "same_role",
                    "stratum": "vulnerable" if truth_vulns else "clean",
                    "input": {"package": name, "ecosystem": ecosystem, "version": version},
                    "truth": {"advisories": truth_vulns, "latest_version": latest},
                    "truth_sources": [{"name": "OSV", "url": "https://api.osv.dev/v1/query", "fetched_at": _now()},
                                      {"name": f"{ecosystem} registry", "url": reg_url, "fetched_at": _now()}],
                })
    return cases


def nvd_cvss(f: Fetcher, cve_id: str) -> dict | None:
    try:
        out = f.json(f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}")
    except Exception:
        return None
    vulns = (out or {}).get("vulnerabilities") or []
    if not vulns:
        return None
    cve = vulns[0]["cve"]
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        metrics = (cve.get("metrics") or {}).get(key) or []
        chosen = next((m for m in metrics if m.get("type") == "Primary"), metrics[0] if metrics else None)
        if chosen:
            data = chosen["cvssData"]
            return {"score": data["baseScore"], "version": data["version"], "source": "NVD",
                    "published": cve.get("published")}
    return {"score": None, "version": None, "source": "NVD", "published": cve.get("published")}


def cvelist_cvss(f: Fetcher, cve_id: str) -> dict | None:
    _, year, number = cve_id.split("-")
    bucket = number[:-3] + "xxx"
    out = f.json(f"https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/{year}/{bucket}/{cve_id}.json")
    if not out:
        return None
    containers = out.get("containers") or {}
    blocks = [containers.get("cna") or {}] + list(containers.get("adp") or [])
    for block in blocks:
        # The newest CVSS version a block carries, the same order as the NVD metric choice.
        for key in ("cvssV4_0", "cvssV3_1", "cvssV3_0", "cvssV2_0"):
            for metric in block.get("metrics") or []:
                if key in metric:
                    return {"score": metric[key].get("baseScore"), "version": metric[key].get("version"),
                            "source": "cvelistV5", "published": (out.get("cveMetadata") or {}).get("datePublished")}
    return {"score": None, "version": None, "source": "cvelistV5",
            "published": (out.get("cveMetadata") or {}).get("datePublished")}


def cvelist_metrics(f: Fetcher, cve_id: str) -> dict | None:
    """The score the CVE record itself carries: the CNA's metric, else the first ADP metric (for
    example CISA-ADP), with the provider's short name. Used to score agents that report the CVE
    record rather than NVD (agent team, PM approval 11-14)."""
    _, year, number = cve_id.split("-")
    out = f.json(f"https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/{year}/{number[:-3]}xxx/{cve_id}.json")
    if not out:
        return None
    containers = out.get("containers") or {}
    blocks = [("cna", containers.get("cna") or {})] + [("adp", b) for b in containers.get("adp") or []]
    for kind, block in blocks:
        # The newest CVSS version a block carries (a CNA may publish 3.1 and 4.0 together),
        # the same order as the NVD metric choice and the record agents.
        for key in ("cvssV4_0", "cvssV3_1", "cvssV3_0", "cvssV2_0"):
            for metric in block.get("metrics") or []:
                if key in metric and metric[key].get("baseScore") is not None:
                    provider = (block.get("providerMetadata") or {}).get("shortName")
                    return {"score": metric[key]["baseScore"], "version": metric[key].get("version"),
                            "from": kind, "provider": provider}
    return {"score": None, "version": None, "from": None, "provider": None}


def add_record_truth(f: Fetcher, cases: list[dict], force: bool = False) -> int:
    """Add truth.cvss_record (cvelistV5 CNA, else ADP) to CVE cases that lack it (or all, with force)."""
    added = 0
    for case in cases:
        if "cvss_record" in case["truth"] and not force:
            continue
        case["truth"]["cvss_record"] = cvelist_metrics(f, case["case_id"])
        case["truth_sources"] = [s for s in case["truth_sources"] if s.get("name") != "cvelistV5"]
        case["truth_sources"].append({"name": "cvelistV5", "url": "https://github.com/CVEProject/cvelistV5",
                                      "fetched_at": _now()})
        added += 1
    return added


def epss(f: Fetcher, cve_ids: list[str]) -> dict[str, float]:
    scores = {}
    for i in range(0, len(cve_ids), 50):
        out = f.json("https://api.first.org/data/v1/epss?cve=" + ",".join(cve_ids[i:i + 50])) or {}
        for row in out.get("data") or []:
            scores[row["cve"]] = float(row["epss"])
    return scores


def _rank(key: str) -> str:
    return hashlib.sha256(f"{SEED}:{key}".encode()).hexdigest()


def cve_cases(f: Fetcher, package_case_list: list[dict], per_stratum: int = 45) -> list[dict]:
    kev = f.json("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json") or {}
    kev_rows = {row["cveID"]: row for row in kev.get("vulnerabilities") or []}
    # KEV sample spread over the years the entries were added.
    by_year: dict[str, list[str]] = {}
    for cid, row in kev_rows.items():
        by_year.setdefault(row.get("dateAdded", "")[:4], []).append(cid)
    for ids in by_year.values():
        ids.sort(key=_rank)
    kev_pick, years = [], sorted(by_year)
    while len(kev_pick) < per_stratum and any(by_year.values()):
        for year in years:
            if by_year[year] and len(kev_pick) < per_stratum:
                kev_pick.append(by_year[year].pop(0))
    # Not-in-KEV CVEs reuse the aliases already found for the package cases.
    aliases = sorted({i for c in package_case_list for adv in c["truth"]["advisories"] for i in adv["ids"]
                      if i.startswith("CVE-") and i not in kev_rows}, key=_rank)
    picks = [(cid, True) for cid in kev_pick] + [(cid, False) for cid in aliases[:per_stratum]]
    scores = epss(f, [cid for cid, _ in picks])
    cases = []
    for cid, in_kev in picks:
        record = nvd_cvss(f, cid) or cvelist_cvss(f, cid)
        if not record or record.get("score") is None:
            continue
        row = kev_rows.get(cid) or {}
        cases.append({
            "case_id": cid,
            "task_type": "same_role",
            "stratum": "kev" if in_kev else "not_kev",
            "input": {"cve_id": cid},
            "truth": {"cvss": record, "kev": in_kev, "kev_date_added": row.get("dateAdded"),
                      "epss": scores.get(cid)},
            "truth_sources": [{"name": "CISA KEV", "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog", "fetched_at": _now()},
                              {"name": record["source"], "url": "https://nvd.nist.gov/vuln/detail/" + cid, "fetched_at": _now()},
                              {"name": "FIRST EPSS", "url": "https://api.first.org/data/v1/epss", "fetched_at": _now()}],
        })
    return cases


# Non-US listed companies whose English legal name is registered as such in GLEIF; only an exact,
# active, single match in the expected country is kept as truth.
NON_US = [("SAP SE", "SAP", "DE"), ("Siemens Aktiengesellschaft", "Siemens", "DE"), ("Allianz SE", "Allianz", "DE"),
          ("BASF SE", "BASF", "DE"), ("Deutsche Bank Aktiengesellschaft", "Deutsche Bank", "DE"),
          ("ASML Holding N.V.", "ASML", "NL"), ("Novartis AG", "Novartis", "CH"), ("Roche Holding AG", "Roche", "CH"),
          ("Nestlé S.A.", "Nestle", "CH"), ("HSBC Holdings plc", "HSBC", "GB"), ("Unilever PLC", "Unilever", "GB"),
          ("AstraZeneca PLC", "AstraZeneca", "GB"), ("Shell plc", "Shell", "GB"), ("BP P.L.C.", "BP", "GB"),
          ("TotalEnergies SE", "TotalEnergies", "FR"), ("LVMH Moët Hennessy Louis Vuitton SE", "LVMH", "FR"),
          ("Banco Santander, S.A.", "Santander", "ES"), ("Nokia Oyj", "Nokia", "FI"), ("Equinor ASA", "Equinor", "NO"),
          ("Novo Nordisk A/S", "Novo Nordisk", "DK"), ("Telefonaktiebolaget LM Ericsson", "Ericsson", "SE")]


def gleif_exact(f: Fetcher, legal_name: str, country: str) -> str | None:
    """The LEI of the one active entity whose legal name equals LEGAL_NAME (case-insensitive) in COUNTRY."""
    out = f.json("https://api.gleif.org/api/v1/lei-records?page%5Bsize%5D=10&filter%5Bentity.legalName%5D="
                  + quote(legal_name)) or {}
    hits = [r for r in out.get("data") or []
            if r["attributes"]["entity"]["legalName"]["name"].casefold() == legal_name.casefold()
            and r["attributes"]["entity"]["legalAddress"]["country"] == country
            and r["attributes"]["entity"].get("status") == "ACTIVE"]
    return hits[0]["id"] if len(hits) == 1 else None


def typed_name(sec_title: str) -> str:
    """How a person would type an SEC filer title: no state markers (/MD/, a trailing DE), plain capitals."""
    name = re.sub(r"\s*/[A-Z]{2,}/\s*", " ", sec_title).strip()
    parts = name.split()
    if len(parts) >= 3 and re.fullmatch(r"[A-Z]{2}", parts[-1]):
        name = " ".join(parts[:-1])
    if name.isupper():
        name = " ".join(w if len(w) <= 3 and w.isalpha() and w not in ("INC", "CO", "THE", "AND") else w.capitalize()
                        for w in name.split())
    return name


def company_cases(f: Fetcher, us: int = 75) -> list[dict]:
    tickers = f.json("https://www.sec.gov/files/company_tickers.json") or {}
    rows = sorted(tickers.values(), key=lambda r: r["cik_str"])        # deterministic, then ranked below
    rows = sorted(rows[:600], key=lambda r: _rank(str(r["cik_str"])))  # the first 600 CIKs: long-listed issuers
    cases, seen = [], set()
    for row in rows:
        if sum(1 for c in cases if c["stratum"] == "us") >= us:
            break
        title = row["title"].strip()
        if row["cik_str"] in seen or not title:
            continue
        seen.add(row["cik_str"])
        lei = gleif_exact(f, title, "US")
        cases.append({"case_id": f"US:CIK{row['cik_str']}", "task_type": "same_role", "stratum": "us",
                      "input": {"name": typed_name(title), "country": "US"},
                      "truth": {"cik": str(row["cik_str"]), "ticker": row["ticker"], "lei": lei, "sec_title": title},
                      "truth_sources": [{"name": "SEC company tickers", "url": "https://www.sec.gov/files/company_tickers.json", "fetched_at": _now()},
                                        {"name": "GLEIF", "url": "https://api.gleif.org/api/v1/lei-records", "fetched_at": _now()}]})
    for legal, common, country in NON_US:
        lei = gleif_exact(f, legal, country)
        if lei and not any(c["truth"].get("lei") == lei for c in cases):
            cases.append({"case_id": f"{country}:{lei}", "task_type": "same_role", "stratum": "non_us",
                          "input": {"name": common, "country": country},
                          "truth": {"lei": lei, "legal_name": legal, "cik": None},
                          "truth_sources": [{"name": "GLEIF", "url": f"https://api.gleif.org/api/v1/lei-records/{lei}", "fetched_at": _now()}]})
    return cases


def split(cases: list[dict], per_split: int = PER_SPLIT) -> dict[str, list[dict]]:
    """Stratified and deterministic.

    Each stratum gets a quota of the total in proportion to its size; its cases are
    then dealt round-robin over the three splits, continuing the turn from the
    previous stratum, so every split holds the same mix within one case.
    """
    out = {name: [] for name in SPLITS}
    strata: dict[str, list[dict]] = {}
    for case in sorted(cases, key=lambda c: _rank(c["case_id"])):
        strata.setdefault(case["stratum"], []).append(case)
    total = min(len(cases), per_split * len(SPLITS))
    names = sorted(strata)
    quotas = {n: (total * len(strata[n])) // len(cases) for n in names} if cases else {}
    for n in sorted(names, key=lambda n: -len(strata[n])):
        if sum(quotas.values()) >= total:
            break
        if quotas[n] < len(strata[n]):
            quotas[n] += 1
    turn = 0
    for n in names:
        for case in strata[n][:quotas[n]]:
            out[SPLITS[turn % len(SPLITS)]].append(case)
            turn += 1
    return out


def write_set(root: Path, slug: str, parts: dict[str, list[dict]], meta: dict) -> dict:
    folder = root / "gold" / slug
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, rows in parts.items():
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        (folder / f"{name}.jsonl").write_text(text, encoding="utf-8")
        strata: dict[str, int] = {}
        for r in rows:
            strata[r["stratum"]] = strata.get(r["stratum"], 0) + 1
        files[name] = {"cases": len(rows), "strata": strata, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    manifest = dict(meta, slug=slug, created_at=_now(), seed=SEED, files=files)
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def build(root: Path, which: list[str], fetcher: Fetcher | None = None, raw_dir: Path | None = None) -> dict:
    f = fetcher or Fetcher()
    out = {}
    pkg = package_cases(f) if {"package-risk-audit", "cve-incident-brief"} & set(which) else []
    if raw_dir:
        raw_dir.mkdir(parents=True, exist_ok=True)
        if pkg:
            (raw_dir / "package-cases.json").write_text(json.dumps(pkg, ensure_ascii=False))
    if "package-risk-audit" in which:
        out["package-risk-audit"] = write_set(root, "package-risk-audit", split(pkg),
                                              {"answer_set": "package-risk-audit-v1", "built_from": len(pkg)})
    if "cve-incident-brief" in which:
        cves = cve_cases(f, pkg)
        add_record_truth(f, cves)
        if raw_dir:
            (raw_dir / "cve-cases.json").write_text(json.dumps(cves, ensure_ascii=False))
        out["cve-incident-brief"] = write_set(root, "cve-incident-brief", split(cves),
                                              {"answer_set": "cve-incident-brief-v1", "built_from": len(cves)})
    if "company-due-diligence" in which:
        companies = company_cases(f)
        if raw_dir:
            (raw_dir / "company-cases.json").write_text(json.dumps(companies, ensure_ascii=False))
        out["company-due-diligence"] = write_set(root, "company-due-diligence", split(companies),
                                                 {"answer_set": "company-due-diligence-v1", "built_from": len(companies)})
    out["calls"] = f.calls
    return out


def resplit(root: Path, raw_dir: Path) -> dict:
    """Write the sets again from saved raw cases, without calling any source."""
    out = {}
    for slug, name, answer_set in (("package-risk-audit", "package-cases.json", "package-risk-audit-v1"),
                                   ("cve-incident-brief", "cve-cases.json", "cve-incident-brief-v1"),
                                   ("company-due-diligence", "company-cases.json", "company-due-diligence-v1")):
        path = raw_dir / name
        if path.exists():
            cases = json.loads(path.read_text(encoding="utf-8"))
            out[slug] = write_set(root, slug, split(cases), {"answer_set": answer_set, "built_from": len(cases),
                                                             "resplit_from": str(path)})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze necklace gold sets from public sources.")
    parser.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    parser.add_argument("--raw", type=Path, default=None, help="also keep the unsplit cases here")
    parser.add_argument("--resplit", action="store_true", help="re-split saved raw cases from --raw, no network")
    parser.add_argument("slugs", nargs="*", default=["package-risk-audit", "cve-incident-brief"])
    args = parser.parse_args(argv)
    if args.resplit:
        if not args.raw:
            parser.error("--resplit needs --raw")
        print(json.dumps(resplit(args.root, args.raw), ensure_ascii=False, indent=1))
        return 0
    print(json.dumps(build(args.root, args.slugs, raw_dir=args.raw), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
