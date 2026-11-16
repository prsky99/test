"""One necklace gate round with the PM 11-16 15:02 exclusion rule, outside the gate harness (option (a)).

The harness (agent_market.necklaces.retest) is not changed. After a round has run
(`python -m agent_market.necklaces.retest <slug> --split <split> --system gate ...`), this script

  status  reads that round's lines from gateway-data/necklaces/retest/<day>.jsonl and gives the round result;
  rerun   measures again, once, only the cases the round set apart (excluded: no answer was obtained), 10 to 60
          minutes after the round's last line, under the split name "<split>-rerun", then gives the round result.

The rule (deploy/NECKLACE_GATE.md section 1):
  1. The denominator is 30. A round passes with at least 28 passed cases. An excluded case is not a pass.
  2. An excluded case is measured again once in the same round, 10 to 60 minutes after the first measurement.
     A case that got an answer (passed or failed) is never measured again.
  3. Excluded again: the case is "unmeasured", kept apart from wrong answers.
  4. Round result: pass (28 or more passed), fail (3 or more answered cases failed), or unmeasured (2 or fewer
     failures but fewer than 28 passed because of exclusions).

Each result is written to logs/ops/necklace-gate/round-<slug>-v<version>-<split>-<time>.json (never overwritten).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_market.necklaces.gate_rules import ROUND, ROUND_PASS  # noqa: E402

FAIL_LIMIT = ROUND - ROUND_PASS + 1      # 3 answered failures make 28 of 30 impossible
RERUN_AFTER_S = 10 * 60
RERUN_WITHIN_S = 60 * 60
RERUN_SUFFIX = "-rerun"
OUT = Path("logs/ops/necklace-gate")
DEFAULT_DATA = Path("gateway-data/necklaces")


def _ts(iso: str) -> float:
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()


def round_lines(lines: list[dict], slug: str, split: str, version: int | None = None) -> list[dict]:
    """The case and excluded lines of one round (and of its rerun split)."""
    sets = (split, split + RERUN_SUFFIX)
    return [l for l in lines if l.get("slug") == slug and l.get("set") in sets and l.get("type") in ("case", "excluded")
            and (version is None or l.get("version") == version)]


def result(lines: list[dict], split: str) -> dict:
    """The round result under the rule from the first measurement and, for excluded cases, the rerun."""
    first = {}
    for l in lines:
        if l["set"] == split:
            first[l["case_id"]] = l                     # the latest first-measurement line of a case
    again = {l["case_id"]: l for l in lines if l["set"] == split + RERUN_SUFFIX}
    passed, failed, unmeasured, pending = [], [], [], []
    for case_id, line in sorted(first.items()):
        final = line
        if line["type"] == "excluded":
            final = again.get(case_id)
            if final is None:
                pending.append(case_id)
                continue
        if final["type"] == "excluded":
            unmeasured.append(case_id)
        elif final.get("ok") is True:
            passed.append(case_id)
        else:
            failed.append(case_id)
    if len(passed) >= ROUND_PASS:
        verdict = "pass"
    elif len(failed) >= FAIL_LIMIT:
        verdict = "fail"
    elif pending:
        verdict = "rerun_due"                           # excluded cases not measured again yet
    else:
        verdict = "unmeasured"
    ends = [_ts(l["at"]) for l in lines if l["set"] == split and l.get("at")]
    return {"verdict": verdict, "denominator": ROUND, "pass_needed": ROUND_PASS, "measured": len(first),
            "passed": len(passed), "failed": len(failed), "unmeasured": len(unmeasured), "rerun_due": pending,
            "failed_cases": failed, "unmeasured_cases": unmeasured,
            "first_measurement_ended": max(ends) if ends else None,
            "versions": sorted({l.get("version") for l in lines})}


def rerun_window(first_end: float | None, now: float) -> str | None:
    """None when a rerun may start now, else why not."""
    if first_end is None:
        return "no first measurement"
    if now - first_end < RERUN_AFTER_S:
        return f"too early: {int((RERUN_AFTER_S - (now - first_end)) // 60) + 1} min to wait"
    if now - first_end > RERUN_WITHIN_S:
        return "too late: more than 60 min after the first measurement (the round stays as it is)"
    return None


def read_day(data: Path, day: str) -> list[dict]:
    path = Path(data) / "retest" / f"{day}.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_result(folder: Path, slug: str, version, split: str, body: dict, stamp: str | None = None) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    base = f"round-{slug}-v{version}-{split}-{stamp or time.strftime('%Y%m%d-%H%M%S')}"
    text = json.dumps(body, ensure_ascii=False, indent=1) + "\n"
    for n in range(1, 1000):
        path = folder / (base + (f"-{n}" if n > 1 else "") + ".json")
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(text)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"no free file name for {base}")


def rerun_cases(defn: dict, cases: list[dict], data: Path, split: str, system: str, base: str) -> dict:
    """The same relay path as `python -m agent_market.necklaces.retest` (main), on the excluded cases only."""
    import httpx
    from agent_market.necklaces import retest, runner
    pacer = retest.RelayPacer()
    with httpx.Client(timeout=12, headers={"User-Agent": "AgentValCon-NecklaceRetest/1.0"}) as client:
        call = runner.budgeted_caller(retest.gateway_caller(client, base, pacer), system, retest.provider_url)
        return retest.run_set(defn, cases, call, root=data, split=split + RERUN_SUFFIX, singles=False, pacer=pacer,
                              watch_state=retest.gate_watch_state(data))


def main(argv=None, now=time.time, runner_fn=rerun_cases) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("status", "rerun"))
    parser.add_argument("slug")
    parser.add_argument("--split", required=True)
    parser.add_argument("--day", default=time.strftime("%Y%m%d"), help="the round's retest day file (YYYYMMDD)")
    parser.add_argument("--version", type=int, help="the definition version of the round (default: current)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--system", default="gate", choices=("gate", "necklace_retest", "adhoc"))
    parser.add_argument("--activate-planned", action="store_true", help="as the round ran (retest --activate-planned)")
    parser.add_argument("--base", default="https://agentconcierge.biz")
    args = parser.parse_args(argv)
    from agent_market.necklaces import model, retest
    defn = next(d for d in model.load_valid() if d["slug"] == args.slug)
    version = args.version or defn["version"]
    lines = round_lines(read_day(args.data, args.day), args.slug, args.split, version)
    body = result(lines, args.split)
    if not body["measured"]:
        print(json.dumps({"error": f"no round lines for {args.slug} v{version} {args.split} on {args.day}"}))
        return 2
    if args.command == "rerun" and body["rerun_due"]:
        if version != defn["version"]:
            print(json.dumps({"error": f"the round ran v{version}; the definition is now v{defn['version']}"}))
            return 2
        why = rerun_window(body["first_measurement_ended"], now())
        if why:
            print(json.dumps({"rerun": "not started", "why": why, **body}, ensure_ascii=False))
            return 75 if why.startswith("too early") else 1
        if args.activate_planned:
            for slot in defn["slots"]:
                for m in slot["chain"]:
                    if m["kind"] == "agentcon" and m.get("state") == "planned":
                        m["state"] = "active"
        wanted = set(body["rerun_due"])
        cases = [c for c in retest.load_cases(args.data, args.slug, args.split) if c["case_id"] in wanted]
        body["rerun"] = runner_fn(defn, cases, args.data, args.split, args.system, args.base)
        lines = round_lines(read_day(args.data, args.day), args.slug, args.split, version)
        body = {**result(lines, args.split), "rerun": body["rerun"]}
    body.update(slug=args.slug, version=version, split=args.split, day=args.day,
                rule="deploy/NECKLACE_GATE.md section 1 (PM 11-16 15:02)")
    path = write_result(args.out, args.slug, version, args.split, body)
    print(json.dumps({"file": str(path), **{k: body[k] for k in ("verdict", "passed", "failed", "unmeasured",
                                                                  "rerun_due")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
