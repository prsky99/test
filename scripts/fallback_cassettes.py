"""Record and replay the AgentValCon fallback agents' HTTP, to show a refactor changed no answer (PM 11-16).

agents.py is split into per-source modules by 11-24. Instead of re-running every approved substitute's gate, the
PM accepted a byte-for-byte replay: record each approved substitute's gate inputs, contract inputs and role tasks
once against the real sources, then run the old and the new code on the same recorded answers with frozen clocks
and compare the whole envelopes. Error paths (404, 429, a timeout, an empty body) are replayed from fixed fakes.
Any difference sends only that substitute to a new gate set.

    .venv/bin/python -m scripts.fallback_cassettes record sec-edgar wiki-grounding   # live, ledger 'cassettes'
    .venv/bin/python -m scripts.fallback_cassettes baseline sec-edgar                # replay, write the baseline
    .venv/bin/python -m scripts.fallback_cassettes check sec-edgar                   # replay, compare to it

Everything lives under gateway-data/fallback-agents/cassettes/ (not committed). Recording reserves every call in
the shared ledger as 'cassettes' and checks every address is public first (a client of our own skips net.get's
preflight); replay makes no outside call at all.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit, urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = ROOT / "gateway-data" / "fallback-agents"
HOME = DATA / "cassettes"
LOCAL_FILES = ("airports.json", "kev-catalog.json", "nvd-cve.sqlite3", "tz-grid.bin", "country-grid.bin")
KEEP_HEADERS = ("content-type", "retry-after", "last-modified", "etag", "x-ratelimit-remaining", "x-ratelimit-reset")
FROZEN = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)      # the replay clock; any fixed instant will do
ERROR_PATHS = ("http_404", "http_429", "timeout", "empty_body")


# ---------------------------------------------------------------- what to record
def gate_cases(agent_id: str) -> list[dict]:
    """The gate cases of the substitute's current approval, by the case ids in its verdict's raw file."""
    from agent_market.fallback_agents import gold_check
    approvals = json.loads((ROOT / "gateway-data/necklaces/approvals.json").read_text())
    rows = [s for s in approvals.get("substitutes") or [] if s.get("agent_id") == agent_id
            and s.get("state") in ("approved", "provisional")]
    if not rows:
        return []
    verdict = Path(ROOT / (rows[-1].get("gate_record") or {}).get("verdict", ""))
    raw = verdict.with_name(verdict.name.replace("verdict-", "raw-").replace(".json", ".jsonl"))
    ids = []
    if raw.exists():
        ids = [r["case_id"] for r in map(json.loads, raw.read_text().splitlines()) if r.get("agent") == agent_id]
    slug = gold_check.SLUG.get(agent_id)
    cases = {}
    for path in sorted((ROOT / "gateway-data/necklaces/gold" / str(slug)).glob("*.jsonl")):
        for line in path.read_text().splitlines():
            case = json.loads(line)
            cases.setdefault(case["case_id"], case)
    return [{"kind": "gate", "id": cid, "args": gold_check.case_arguments(agent_id, cases[cid])}
            for cid in dict.fromkeys(ids) if cid in cases]


def inputs(agent_id: str) -> list[dict]:
    """Gate cases, contract inputs and role tasks: everything the approval was judged on."""
    from agent_market.fallback_agents.catalog import SPECS
    from agent_market.necklaces import role_tasks
    out = gate_cases(agent_id)
    contract_inputs = json.loads((ROOT / "reports/fallback-agents-2026-11-14/contract-test-inputs.json").read_text())
    out += [{"kind": "contract", "id": f"contract-{i}", "args": row[0]}
            for i, row in enumerate(contract_inputs.get(agent_id) or [])]
    rag = Path(role_tasks.FILE).with_name("role-tasks-rag-v1.jsonl")
    tasks = role_tasks.load() + (role_tasks.load(rag) if rag.exists() else [])
    contract = SPECS[agent_id]["contract"]
    out += [{"kind": "role", "id": t["case_id"], "args": t["input"]} for t in tasks if t.get("contract") == contract]
    return out


# ---------------------------------------------------------------- cassette transports
def request_key(request: httpx.Request) -> str:
    parts = urlsplit(str(request.url))
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return request.method + " " + urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


class RecordingTransport(httpx.BaseTransport):
    """Sends through the real transport after a public-address check and keeps every exchange."""

    def __init__(self, sink):
        self.real, self.sink = httpx.HTTPTransport(), sink

    def handle_request(self, request):
        from agent_market.concierge.http_security import validate_public_url
        validate_public_url(str(request.url))
        try:
            response = self.real.handle_request(request)
            body = response.read()
        except httpx.TimeoutException as exc:
            self.sink({"key": request_key(request), "error": type(exc).__name__})
            raise
        self.sink({"key": request_key(request), "status": response.status_code,
                   "headers": {k: v for k, v in response.headers.items() if k.lower() in KEEP_HEADERS},
                   "body": base64.b64encode(body).decode()})
        return httpx.Response(response.status_code, headers=response.headers, content=body, request=request)


class ReplayTransport(httpx.BaseTransport):
    """Answers from the cassette in recorded order per request; an unrecorded request is a connect error."""

    def __init__(self, exchanges):
        self.queue: dict[str, list] = {}
        for ex in exchanges:
            self.queue.setdefault(ex["key"], []).append(ex)
        self.missing: list[str] = []

    def handle_request(self, request):
        key = request_key(request)
        found = self.queue.get(key) or []
        if not found:
            self.missing.append(key)
            raise httpx.ConnectError("not recorded", request=request)
        ex = found.pop(0) if len(found) > 1 else found[0]
        if ex.get("error"):
            raise httpx.ReadTimeout("recorded timeout", request=request)
        return httpx.Response(ex["status"], headers=ex["headers"], content=base64.b64decode(ex["body"]), request=request)


class ErrorTransport(httpx.BaseTransport):
    def __init__(self, kind):
        self.kind = kind

    def handle_request(self, request):
        if self.kind == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if self.kind == "http_404":
            return httpx.Response(404, json={}, request=request)
        if self.kind == "http_429":
            return httpx.Response(429, headers={"retry-after": "30"}, json={}, request=request)
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"", request=request)


# ---------------------------------------------------------------- running the agents
class FrozenClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, seconds)


def agents_for(transport, data_dir: Path):
    from agent_market.fallback_agents.agents import FallbackAgents
    from agent_market.fallback_agents.limits import limiters
    clock = FrozenClock()
    work = data_dir / "_run"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for name in LOCAL_FILES:               # big read-only files linked; the ones an agent rewrites (KEV) copied
        if (data_dir / name).exists():
            if name.endswith(".json"):
                shutil.copy2(data_dir / name, work / name)
            else:
                (work / name).symlink_to(data_dir / name)
    agents = FallbackAgents(http=httpx.Client(transport=transport), data_dir=work, clock=clock,
                            wall=lambda: FROZEN.timestamp() + clock.t, utc_now=lambda: FROZEN,
                            limiters=limiters(clock=clock, sleep=clock.sleep))
    agents.resolve = agents.connect = None     # TLS reads are not in any approved substitute; never live here
    return agents


def run_one(agents, agent_id, args) -> dict:
    from agent_market.fallback_agents.agents import FallbackUnavailable
    try:
        envelope = agents.execute(agent_id, args)
        return {"envelope": envelope}
    except FallbackUnavailable as exc:
        return {"error": exc.code, "message": str(exc)}


def canonical(row) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- commands
def record(agent_ids, home=HOME, system="cassettes"):
    from agent_market.fallback_agents.agents import FallbackAgents
    from agent_market.fallback_agents.net import budget
    from agent_market.provider_budget import SHARE
    if system not in SHARE:
        raise SystemExit(f"the ledger has no '{system}' share yet (ops: provider_budget.SHARE); nothing recorded")
    home.mkdir(parents=True, exist_ok=True)
    data = home / "data"
    if not data.exists():                      # one snapshot of the local data files for every replay
        data.mkdir()
        for name in LOCAL_FILES:
            if (DATA / name).exists():
                shutil.copy2(DATA / name, data / name)
    report = {}
    for agent_id in agent_ids:
        path = home / f"{agent_id}.jsonl"
        done = {json.loads(l)["case"] for l in path.read_text().splitlines()} if path.exists() else set()
        todo = [c for c in inputs(agent_id) if c["kind"] + ":" + c["id"] not in done]
        recorded, refused = 0, 0
        with path.open("a") as fh:
            for case in todo:
                exchanges = []
                agents = FallbackAgents(http=httpx.Client(transport=RecordingTransport(exchanges.append)))
                with budget(system):
                    row = run_one(agents, agent_id, case["args"])
                if row.get("error") in ("rate_limited", "source_unavailable") and not exchanges:
                    refused += 1                 # the ledger or our pacing said no: record this case another day
                    continue
                fh.write(json.dumps({"case": case["kind"] + ":" + case["id"], "args": case["args"],
                                     "exchanges": exchanges, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
                recorded += 1
        report[agent_id] = {"recorded": recorded, "refused_by_ledger": refused, "already": len(done),
                            "of": len(todo) + len(done)}
    return report


def replay(agent_ids, home=HOME) -> dict:
    """{agent: [{case, output}]} on the recorded answers plus the four error paths, current code."""
    out = {}
    for agent_id in agent_ids:
        path = home / f"{agent_id}.jsonl"
        rows = []
        cases = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
        for case in cases:
            transport = ReplayTransport(case["exchanges"])
            row = run_one(agents_for(transport, home / "data"), agent_id, case["args"])
            rows.append({"case": case["case"], "output": row, "unrecorded": transport.missing})
        if cases:
            first = cases[0]["args"]
            for kind in ERROR_PATHS:
                row = run_one(agents_for(ErrorTransport(kind), home / "data"), agent_id, first)
                rows.append({"case": "error:" + kind, "output": row, "unrecorded": []})
        out[agent_id] = rows
    return out


def baseline(agent_ids, home=HOME) -> dict:
    report = {}
    for agent_id, rows in replay(agent_ids, home).items():
        (home / f"{agent_id}.baseline.jsonl").write_text("".join(canonical(r) + "\n" for r in rows))
        report[agent_id] = {"cases": len(rows), "sha256": hashlib.sha256(
            "".join(canonical(r) for r in rows).encode()).hexdigest()[:16]}
    return report


def check(agent_ids, home=HOME) -> dict:
    report = {}
    for agent_id, rows in replay(agent_ids, home).items():
        path = home / f"{agent_id}.baseline.jsonl"
        if not path.exists():
            report[agent_id] = {"same": False, "why": "no baseline"}
            continue
        want = path.read_text().splitlines()
        got = [canonical(r) for r in rows]
        differ = [json.loads(w)["case"] for w, g in zip(want, got) if w != g]
        report[agent_id] = {"same": not differ and len(want) == len(got), "cases": len(got),
                            "different": differ[:20], "count_changed": len(want) != len(got)}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("record", "baseline", "check", "inputs"))
    parser.add_argument("agents", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "inputs":
        result = {a: len(inputs(a)) for a in args.agents}
    else:
        result = {"record": record, "baseline": baseline, "check": check}[args.command](args.agents)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if args.command == "check" and not all(r.get("same") for r in result.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
