"""Answer set for the package-readme substitute gate (agent team 11-17, PM 10:4x; package-risk-audit v2 usage seat).

    .venv/bin/python -m scripts.gold_package_readme --from holdout-r2,holdout-v2-activity --split readme-r1

npm packages from package-risk-audit splits (in the order given, each package once, until 30) are checked against
an independent copy of their README: the README.md at the default branch (HEAD) of the GitHub repository the npm
entry names, read from raw.githubusercontent.com. The truth is that README's code blocks that are code (not shell or
install lines, the same rule as the agent) and its SHA-256; the gate passes when the agent's first example is one of
those blocks (whitespace compared loosely), or when both have none. Package-readme was built without reading these
splits. Two calls a package (npm /<name>/latest for the repository, then the README), one second apart, reserved in
the shared ledger as 'gate'. A split is never rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SLUG = "package-risk-audit"
GITHUB = re.compile(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?].*)?$")


def code_blocks(readme: str) -> list[str]:
    from agent_market.fallback_agents.agents import readme_examples   # the agent's own rule for what is code
    return readme_examples(readme)


def repo_of(latest: dict) -> tuple[str, str] | None:
    repo = latest.get("repository")
    url = repo.get("url") if isinstance(repo, dict) else repo
    m = GITHUB.search(str(url or ""))
    return (m.group(1), m.group(2)) if m else None


def build(packages: list[str], get_latest, get_readme, keep: int = 30, origin: dict | None = None) -> list[dict]:
    """ORIGIN maps a package to the split it came from; each case records it (PM 11-17 12:0x: fill cases are named)."""
    cases = []
    for package in packages:
        latest = get_latest(package)
        repo = repo_of(latest or {})
        if not repo:
            continue
        readme = get_readme(*repo)
        if readme is None:
            continue
        cases.append({"case_id": f"readme:{package}", "input": {"package": package, "ecosystem": "npm"},
                      "task_type": "substitute", "stratum": "npm", "source_split": (origin or {}).get(package),
                      "truth": {"package": package, "repository_github": f"{repo[0]}/{repo[1]}",
                                "readme_sha256": hashlib.sha256(readme.encode()).hexdigest(),
                                "code_blocks": code_blocks(readme)[:8]}})
        if len(cases) >= keep:
            break
    return cases


def main(argv=None) -> int:
    from agent_market.concierge.http_security import validate_public_url
    from agent_market.provider_budget import reserve
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="source", default="holdout-r2,holdout-v2-activity")
    p.add_argument("--split", default="readme-r1")
    ns = p.parse_args(argv)
    folder = ROOT / "gateway-data/necklaces/gold" / SLUG
    out = folder / f"{ns.split}.jsonl"
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    packages, origin = [], {}
    for split in ns.source.split(","):
        for line in (folder / f"{split}.jsonl").read_text().splitlines():
            case = json.loads(line) if line.strip() else {}
            inp = case.get("input") or {}
            name = inp.get("package") or (case.get("truth") or {}).get("package")
            if (inp.get("ecosystem") in (None, "npm")) and isinstance(name, str) and name not in packages:
                packages.append(name)
                origin[name] = split
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": "AgentValCon-gold/1.0"})

    def fetch(url):
        ok, why = reserve(url, "gate")
        if not ok:
            raise SystemExit(f"ledger refused: {why}")
        validate_public_url(url)
        r = client.get(url)
        time.sleep(1.0)
        return r if r.status_code == 200 else None

    def get_latest(package):
        r = fetch("https://registry.npmjs.org/" + quote(package, safe="@") + "/latest")
        return r.json() if r is not None else None

    def get_readme(owner, repo):
        r = fetch(f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md")
        return r.text if r is not None else None
    cases = build(packages, get_latest, get_readme, origin=origin)
    if len(cases) < 30:
        print(f"only {len(cases)} cases from {len(packages)} packages; not written"); return 1
    src = [{"name": "GitHub repository README (raw.githubusercontent.com, default branch), each under its own license",
            "url": "https://raw.githubusercontent.com/", "fetched_at": fetched},
           {"name": "npm public registry (repository field only)", "url": "https://registry.npmjs.org/", "fetched_at": fetched}]
    with out.open("w") as fh:
        for c in cases:
            fh.write(json.dumps({**c, "truth_sources": src}, ensure_ascii=False) + "\n")
    by_split = {}
    for c in cases:
        by_split.setdefault(c["source_split"], []).append(c["case_id"])
    print(f"wrote {len(cases)} cases to {out} at {fetched} (from {ns.source})")
    for split, ids in by_split.items():      # the round record names the cases each split filled
        print(f"  {split}: {len(ids)} cases: {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
