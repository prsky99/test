"""cve-incident-brief v2 answer set for the fix step (agent team 11-15; design reports/necklace-3slot-designs-2026-11-15).

The 90 CVE cases of the cve-incident-brief answer sets already carry NVD's CVSS and CISA KEV truth. This adds
truth.fixes: every package GitHub's reviewed security advisory for the CVE names with its first patched version
(api.github.com/advisories?cve_id=..., one call per CVE). A CVE without a reviewed advisory or without any patched
version (operating systems, appliances) gets no fixes and stays out of the fix step (applies). CVEs whose record
GitHub, Snyk, the Django Software Foundation or Red Hat issued are asked first, since they are the open-source ones.
Calls are reference_checks through the ledger (GitHub per day and per hour); the builder resumes and writes the
split holdout-v2-fix (only cases with fixes) once every CVE is asked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from .gold import _now
from .gold_repos import Budget, fetch_json
from .judge import DEFAULT_ROOT

SLUG = "cve-incident-brief"
SPLIT = "holdout-v2-fix"
SOURCES = ("tuning", "holdout-r1", "holdout-r2")
ADVISORIES = "https://api.github.com/advisories?type=reviewed&cve_id={cve}"
FIRST = ("GitHub_M", "snyk", "DSF", "redhat", None, "CISA-ADP", "VulnCheck", "mitre", "hackerone")


def cases(root: Path) -> list[dict]:
    out, seen = [], set()
    for split in SOURCES:
        path = Path(root) / "gold" / SLUG / f"{split}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
            if line.strip():
                case = json.loads(line)
                if case["case_id"] not in seen:
                    seen.add(case["case_id"])
                    out.append(case)
    rank = {p: i for i, p in enumerate(FIRST)}
    return sorted(out, key=lambda c: rank.get((c["truth"].get("cvss_record") or {}).get("provider"), len(FIRST)))


def fixes_of(advisories) -> list[dict]:
    out = []
    for adv in advisories or []:
        for vuln in adv.get("vulnerabilities") or []:
            package, patched = vuln.get("package") or {}, vuln.get("first_patched_version")
            if isinstance(patched, dict):
                patched = patched.get("identifier")
            if package.get("name") and patched:
                item = {"ecosystem": package.get("ecosystem"), "name": package["name"], "first_patched_version": patched}
                if item not in out:
                    out.append(item)
    return out


def step(root: Path = DEFAULT_ROOT, get=fetch_json) -> dict:
    folder = Path(root) / "gold" / SLUG
    progress_path = folder / "fixes-progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
    stopped = None
    try:
        for case in cases(root):
            cve = case["input"]["cve_id"]
            if cve in progress:
                continue
            url = ADVISORIES.format(cve=quote(cve))
            status, body = get(url)
            progress[cve] = {"fixes": fixes_of(body if status == 200 else []), "url": url, "at": _now(),
                             "advisories": [a.get("ghsa_id") for a in body or [] if isinstance(a, dict)]}
    except Budget as exc:
        stopped = str(exc)
    folder.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    all_cases = cases(root)
    left = [c["case_id"] for c in all_cases if c["input"]["cve_id"] not in progress]
    out = {"asked": len(progress), "with_fixes": sum(1 for r in progress.values() if r["fixes"]), "left": len(left),
           "stopped": stopped}
    if not left:
        out["written"] = write_split(root, all_cases, progress)
    return out


def write_split(root: Path, all_cases: list[dict], progress: dict) -> dict:
    chosen = []
    for case in all_cases:
        row = progress.get(case["input"]["cve_id"]) or {}
        if not row.get("fixes"):
            continue
        case = json.loads(json.dumps(case))
        case["truth"]["fixes"] = row["fixes"]
        case["truth_sources"] = list(case.get("truth_sources") or []) + [
            {"name": "GitHub Advisory Database (reviewed)", "url": row["url"], "fetched_at": row["at"],
             "advisories": row["advisories"]}]
        chosen.append(case)
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in chosen)
    (folder / f"{SPLIT}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    strata: dict[str, int] = {}
    for c in chosen:
        strata[c.get("stratum")] = strata.get(c.get("stratum"), 0) + 1
    manifest.setdefault("files", {})[SPLIT] = {"cases": len(chosen), "strata": strata,
                                               "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                               "for": "cve-incident-brief v2 fix step (software-incident gate)"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(chosen), "strata": strata}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
