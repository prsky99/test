"""Answer set for the mcp-registry substitute gate (agent team 11-16, PM: 11-17 13:10 gate).

    .venv/bin/python -m scripts.gold_mcp_registry --split substitute-r1 [--listed 24 --absent 6]
    .venv/bin/python -m scripts.gold_mcp_registry --split substitute-r2 --exclude-split substitute-r1   # a re-judgement

Truth is read once from the Official MCP Registry list (CC0) and frozen in
gateway-data/necklaces/gold/mcp-server-trust-check/<split>.jsonl: the server's name, latest version, publish time,
status and repository. Listed servers are taken at a fixed stride through the union of five namespace searches
(the plain list is in name order, so its first pages hold only names starting with "a"); absent cases are made-up
names under a namespace nobody owns, whose
right answer is listed false. Every call is reserved in the shared ledger as 'reference_checks'; five searches, no paging. Nothing else is called. The gate compares names exactly, and a version newer than the frozen one
also passes (a server may publish between building the set and the gate).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "https://registry.modelcontextprotocol.io/v0.1/servers"
SLUG = "mcp-server-trust-check"
UA = {"User-Agent": "AgentValCon-gold/1.0 (+https://agentconcierge.biz; contact@agentconcierge.biz)",
      "Accept": "application/json"}


# The list is in name order, so its first pages hold only names starting with "a" (11-16: 164 servers, all a*).
# One search per namespace kind instead, each 100 rows: GitHub-verified names and reverse-DNS names of common TLDs.
SEARCHES = ("io.github", "com.", "ai.", "dev.", "app.")


def fetch_pages(get, searches=SEARCHES, limit=100):
    rows = []
    for q in searches:
        data = get(BASE, {"search": q, "limit": limit})
        rows += [r for r in data.get("servers") or [] if isinstance(r, dict) and isinstance(r.get("server"), dict)]
    return rows


def latest_only(rows):
    """One row per server name: the row flagged latest by the registry (else the newest publish time)."""
    best = {}
    for r in rows:
        meta = (r.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
        name = r["server"].get("name")
        if not name or meta.get("status") not in (None, "active"):
            continue
        key = (bool(meta.get("isLatest")), str(meta.get("publishedAt") or ""))
        if name not in best or key > best[name][0]:
            best[name] = (key, r, meta)
    return [(r, meta) for _, r, meta in sorted(best.values(), key=lambda x: x[1]["server"]["name"])]


def seen_names(folder: Path, splits) -> set:
    """Server names already used by earlier splits (deploy/NECKLACE_GATE.md: a re-judgement never reuses a case)."""
    names = set()
    for split in splits:
        path = folder / f"{split}.jsonl"
        if split and not path.exists():
            raise SystemExit(f"--exclude-split {split}: {path} not found")
        if split:
            names |= {json.loads(l)["input"]["name"] for l in path.read_text().splitlines() if l.strip()}
    return names


def build(rows, listed=24, absent=6, seed="substitute-r1", exclude=frozenset()):
    rows = [(r, meta) for r, meta in rows if r["server"]["name"] not in exclude]
    chosen = rows[:: max(1, len(rows) // listed)][:listed] if rows else []
    cases = []
    for r, meta in chosen:
        s = r["server"]
        repo = s.get("repository")
        repo_url = repo.get("url") if isinstance(repo, dict) else repo
        cases.append({"case_id": "mcp:" + s["name"], "input": {"name": s["name"]}, "stratum": "listed",
                      "task_type": "substitute", "truth": {
                          "listed": True, "name": s["name"], "version": s.get("version"),
                          "published_at": meta.get("publishedAt"), "status": meta.get("status") or "active",
                          "repository": repo_url if isinstance(repo_url, str) else None}})
    for i in range(absent):
        tag = hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()[:10]
        name = f"io.github.agentvalcon-absent-{tag}/server-{i}"
        cases.append({"case_id": "mcp:absent-" + tag, "input": {"name": name}, "stratum": "absent",
                      "task_type": "substitute", "truth": {"listed": False}})
    return cases


def main(argv=None) -> int:
    from agent_market.concierge.http_security import validate_public_url
    from agent_market.provider_budget import reserve
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--split", default="substitute-r1")
    p.add_argument("--listed", type=int, default=24)
    p.add_argument("--absent", type=int, default=6)
    p.add_argument("--exclude-split", default="", help="comma-separated earlier splits whose servers are left out")
    ns = p.parse_args(argv)
    seen = seen_names(ROOT / "gateway-data/necklaces/gold" / SLUG, [x.strip() for x in ns.exclude_split.split(",")])
    out = ROOT / "gateway-data/necklaces/gold" / SLUG / f"{ns.split}.jsonl"
    if out.exists():
        print(f"{out} exists; a split is never rewritten"); return 2
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = httpx.Client(headers=UA, timeout=15, follow_redirects=False)

    def get(url, params):
        ok, why = reserve(url, "reference_checks")
        if not ok:
            raise SystemExit(f"ledger refused: {why}")
        validate_public_url(url)
        r = client.get(url, params=params)
        if r.status_code in (403, 429):   # a provider limit stops the build (ops 11-17)
            from agent_market.provider_budget import note
            note(url, "reference_checks", 429, evidence={"origin": "provider_http", "retry_after": r.headers.get("Retry-After")})
            raise SystemExit(f"provider refused ({r.status_code}); stopped, nothing written")
        r.raise_for_status()
        time.sleep(1.0)
        return r.json()
    rows = latest_only(fetch_pages(get))
    cases = build(rows, ns.listed, ns.absent, ns.split, exclude=seen)
    if len(cases) < ns.listed + ns.absent:
        print(f"only {len(cases)} cases; not written"); return 1
    src = [{"name": "Official MCP Registry (preview; CC0)", "url": BASE, "fetched_at": fetched}]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for c in cases:
            fh.write(json.dumps({**c, "truth_sources": src}, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases to {out} ({len(rows)} servers seen, {len(seen)} left out from {ns.exclude_split or 'no split'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
