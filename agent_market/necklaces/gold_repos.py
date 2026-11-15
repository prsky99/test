"""package-risk-audit v2 answer set for the activity step (agent team 11-15; design reports/necklace-3slot-designs-2026-11-15).

For every npm package of the package-risk-audit answer sets the truth is:
- repository_github: owner/name from npm's own repository field (registry.npmjs.org/<package>/latest), the value the
  meta step hands to the activity step;
- latest_release_tag and latest_release_date: GitHub's newest published release of that repository
  (api.github.com/repos/<owner>/<name>/releases?per_page=1), or none when it publishes no GitHub releases;
- latest_version: npm's latest version.
Every call goes through the shared ledger as reference_checks (npm and GitHub per day, GitHub also per hour), so the
builder resumes: each run fetches what the shares allow, keeps progress in repos-progress.json and writes the split
once every package is done. A package whose repository is not on GitHub, or whose repository GitHub does not know, is
left out with the reason. Releases change, so the split is valid for 14 days.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from .gold import USER_AGENT, _now
from .judge import DEFAULT_ROOT

SLUG = "package-risk-audit"
SPLIT = "holdout-v2-activity"
SYSTEM = "reference_checks"
VALID_DAYS = 14
NPM = "https://registry.npmjs.org/{package}/latest"
RELEASES = "https://api.github.com/repos/{repo}/releases?per_page=1"
GITHUB = re.compile(r"github\.com[/:]([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?(?:[/#?].*)?$")


class Budget(Exception):
    pass


def fetch_json(url: str, reserve=None, note=None, github_reserve=None, opener=None):
    """GET url as JSON through the ledger; (status, body). Raises Budget when a share says no."""
    import urllib.error
    import urllib.request
    from .. import provider_budget as pb
    reserve, note = reserve or pb.reserve, note or pb.note
    ok, why = reserve(url, SYSTEM)
    if not ok:
        raise Budget(why)
    if "api.github.com" in url:
        ok, why = (github_reserve or pb.github_reserve)(SYSTEM)
        if not ok:
            raise Budget(why)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request = urllib.request.Request(url, headers=headers)
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            note(url, SYSTEM, status, evidence="provider_http")
            return status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        note(url, SYSTEM, exc.code, evidence="provider_http")
        if exc.code == 404:
            return 404, None
        raise


def packages(root: Path) -> list[str]:
    out = []
    for path in sorted((Path(root) / "gold" / SLUG).glob("*.jsonl")):
        if path.stem == SPLIT:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                name = (case.get("input") or {}).get("package")
                if (case.get("input") or {}).get("ecosystem") == "npm" and name and name not in out:
                    out.append(name)
    return out


def repo_of(manifest: dict) -> str | None:
    repo = (manifest or {}).get("repository")
    url = repo.get("url") if isinstance(repo, dict) else repo
    text = str(url or "").strip()
    short = re.fullmatch(r"(?:github:)?([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})", text)
    if short:                       # npm's shorthand: "owner/name" and "github:owner/name" mean GitHub
        return f"{short.group(1)}/{short.group(2).removesuffix('.git')}"
    found = GITHUB.search(text)
    return f"{found.group(1)}/{found.group(2)}" if found else None


def step(root: Path = DEFAULT_ROOT, get=fetch_json) -> dict:
    """Fetch what the ledger allows; returns {done, left, dropped, stopped}."""
    folder = Path(root) / "gold" / SLUG
    progress_path = folder / "repos-progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
    stopped = None
    try:
        for name in packages(root):
            row = progress.setdefault(name, {})
            if "dropped" in row or "release" in row:
                continue
            if "repository_github" not in row:
                url = NPM.format(package=quote(name, safe="@"))
                status, body = get(url)
                if status == 404 or not body:
                    row["dropped"] = "npm has no such package"
                    continue
                row.update(latest_version=body.get("version"), npm_url=url, npm_at=_now())
                repo = repo_of(body)
                if not repo:
                    row["dropped"] = "npm repository is not on GitHub"
                    continue
                row["repository_github"] = repo
            url = RELEASES.format(repo=row["repository_github"])
            status, body = get(url)
            if status == 404:
                row["dropped"] = "GitHub does not know the repository"
                continue
            newest = body[0] if isinstance(body, list) and body else None
            row["release"] = {"tag": newest.get("tag_name"), "date": str(newest.get("published_at") or "")[:10]} \
                if newest else None
            row.update(github_url=url, github_at=_now())
    except Budget as exc:
        stopped = str(exc)
    folder.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    done = [n for n, r in progress.items() if "release" in r]
    left = [n for n in packages(root) if n not in done and "dropped" not in progress.get(n, {})]
    out = {"done": len(done), "left": len(left), "dropped": {n: r["dropped"] for n, r in progress.items() if "dropped" in r},
           "stopped": stopped}
    if not left:
        out["written"] = write_split(root, progress)
    return out


def write_split(root: Path, progress: dict, today: date | None = None) -> dict:
    today = today or date.today()
    cases = []
    for name, row in sorted(progress.items()):
        if "release" not in row:
            continue
        release = row["release"]
        truth = {"repository_github": row["repository_github"], "latest_version": row.get("latest_version"),
                 "latest_release_tag": release["tag"] if release else None,
                 "latest_release_date": release["date"] if release else None,
                 "github_releases": bool(release), "valid_until": (today + timedelta(days=VALID_DAYS)).isoformat()}
        cases.append({"case_id": f"npm-activity:{name}", "task_type": "same_role", "stratum": "releases" if release else "no_releases",
                      "input": {"package": name, "ecosystem": "npm"}, "truth": truth,
                      "truth_sources": [{"name": "npm registry", "url": row["npm_url"], "fetched_at": row["npm_at"]},
                                        {"name": "GitHub releases", "url": row["github_url"], "fetched_at": row["github_at"]}]})
    folder = Path(root) / "gold" / SLUG
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (folder / f"{SPLIT}.jsonl").write_text(text, encoding="utf-8")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("files", {})[SPLIT] = {"cases": len(cases), "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                               "for": "package-risk-audit v2 activity step (github.releases.v1)"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"cases": len(cases), "no_releases": sum(1 for c in cases if c["stratum"] == "no_releases")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(step(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
