"""Measured value of a necklace from one gate round's own raw lines (PM 11-17): what promotion may say, and nothing
that was not measured.

    .venv/bin/python -m scripts.necklace_value_report <slug> <split> <YYYYMMDD> [--root gateway-data/necklaces]
        [--out reports] [--version N]

Reads <root>/retest/<day>.jsonl (case, single and member lines of the round) and writes
reports/necklace-value-<slug>-<day>/README.md (Korean, for the team) and value.json, with three English lines for the
public pages. Four numbers:

1. accuracy: the necklace's share of graded cases passed, the best single member's share on the same cases, and the
   difference (delta, percentage points)
2. time per case: p50 and p95 of the run's latency. This is ORIGIN-PATH time (the gate runs on the engine path: no
   Cloudflare hop, no new connection); public-address time is measured apart after release (user_slo)
3. tokens: one necklace answer against what an agent reads when it calls the same members itself (every member call
   of the same run, arguments and answers; value.measure). Tokens are characters / 4 (value.CHARS_PER_TOKEN), an
   ESTIMATE of a tokenizer, the same rule on both sides. The full value (finding and merging) uses estimated find sizes
   and is marked so
4. fallbacks: cases where a required step was answered by a member after the first (rank > 1)

The public lines are written only when the round's verdict file says the necklace passed; otherwise the README says
the numbers are not for publishing.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def pct(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo))


def read_lines(root: Path, day: str) -> list[dict]:
    path = Path(root) / "retest" / f"{day}.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def measure(lines: list[dict], slug: str, split: str, version: int | None = None) -> dict:
    def ours(l):
        return l.get("slug") == slug and (version is None or l.get("version") in (None, version))
    cases = {}
    for l in lines:                                   # a rerun line for the same case replaces the earlier one
        if l.get("type") == "case" and ours(l) and l.get("set") == split:
            cases[l["case_id"]] = l
    excluded = [l for l in lines if l.get("type") == "excluded" and ours(l) and l.get("set") == split]
    graded = {c: l for c, l in cases.items() if l.get("ok") is not None}
    passed = {c for c, l in graded.items() if l["ok"]}
    per = defaultdict(dict)
    for l in lines:
        if l.get("type") == "single" and ours(l) and l.get("case_id") in graded and l.get("ok") is not None:
            per[str(l.get("resource_id") or l.get("agent_id"))][l["case_id"]] = bool(l["ok"])
    singles = []
    for member, res in per.items():
        same = sorted(res)
        singles.append({"member": member, "cases": len(same), "correct": sum(res[c] for c in same),
                        "rate": round(sum(res[c] for c in same) / len(same), 3),
                        "necklace_rate_same_cases": round(sum(c in passed for c in same) / len(same), 3)})
    singles.sort(key=lambda r: (-r["rate"], -r["cases"]))
    best = singles[0] if singles else None
    latency = [int(l.get("latency_ms") or 0) for l in graded.values()]
    values = [l["value"] for l in graded.values() if l.get("value")]

    def side(name):
        rows = [v[name]["tokens"] for v in values if v.get(name)]
        return {"median": statistics.median(rows) if rows else None, "p95": pct(rows, .95), "total": sum(rows)}
    estimated = sorted({e for v in values for e in (v.get("direct_full") or {}).get("estimated") or []})
    fallback_cases, by_slot = 0, Counter()
    for l in graded.values():
        late = [s for s, info in (l.get("slots") or {}).items() if (info or {}).get("rank") not in (None, 1)
                and (info or {}).get("status") in ("answered", "partial")]
        if late:
            fallback_cases += 1
            by_slot.update(late)
    lead_errors = Counter()
    for l in lines:
        if l.get("type") == "member" and ours(l) and l.get("ok") is False:
            lead_errors[(l.get("slot"), str(l.get("resource_id") or l.get("tool")), l.get("error_class"))] += 1
    out = {"slug": slug, "split": split, "cases_run": len(cases), "graded": len(graded), "excluded": len(excluded),
           "excluded_why": dict(Counter(e.get("why") for e in excluded)),
           "accuracy": {"necklace": {"correct": len(passed), "of": len(graded),
                                     "rate": round(len(passed) / len(graded), 3) if graded else None},
                        "singles": singles, "best_single": best,
                        "delta_points": round(100 * (best["necklace_rate_same_cases"] - best["rate"]), 1) if best else None},
           "time_ms": {"path": "origin (engine path; public-address time measured apart)",
                       "p50": pct(latency, .5), "p95": pct(latency, .95)},
           "tokens": {"rule": "characters / 4 on both sides (an estimate of a tokenizer)",
                      "necklace_answer": side("necklace"), "agent_reads_member_answers": side("direct"),
                      "agent_full_with_finding_and_merging": dict(side("direct_full"), estimated_parts=estimated)},
           "fallbacks": {"cases": fallback_cases, "by_slot": dict(by_slot),
                         "failed_member_calls": [{"slot": s, "member": m, "error": e, "count": n}
                                                 for (s, m, e), n in lead_errors.most_common(10)]}}
    t = out["tokens"]
    if t["necklace_answer"]["median"] and t["agent_reads_member_answers"]["median"]:
        t["ratio_member_answers_to_necklace"] = round(t["agent_reads_member_answers"]["median"]
                                                      / t["necklace_answer"]["median"], 2)
    if t["necklace_answer"]["median"] and t["agent_full_with_finding_and_merging"]["median"]:
        t["ratio_full_to_necklace"] = round(t["agent_full_with_finding_and_merging"]["median"]
                                            / t["necklace_answer"]["median"], 2)
    return out


def verdict_for(slug: str, day: str, logs: Path) -> dict | None:
    for path in sorted((Path(logs) / "rounds").glob(f"{slug}-v*-{day}-verdict.json")):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def passed(verdict: dict | None) -> bool:
    """The round passed: the verdict file says so, or its runner result reached the pass line (28 of 30)."""
    if not verdict:
        return False
    if verdict.get("verdict") == "pass" or verdict.get("passed") is True:
        return True
    rr = verdict.get("runner_result") or {}
    try:
        from agent_market.necklaces.gate_rules import ROUND_PASS, ROUND as ROUND_CASES
    except ImportError:
        ROUND_PASS, ROUND_CASES = 28, 30
    return isinstance(rr.get("passed"), int) and rr.get("of") == ROUND_CASES and rr["passed"] >= ROUND_PASS


def path_label(verdict: dict | None) -> str:
    path = str((verdict or {}).get("path") or "")
    if "relay" in path:
        return "relay 경로 시간(이 맥 → Cloudflare → 원서버, 멤버마다 왕복 포함)"
    return "원서버 경로 시간(engine 경로: Cloudflare 경유·새 연결 제외)"


def public_lines(m: dict) -> list[str]:
    a, t, tm = m["accuracy"], m["tokens"], m["time_ms"]
    lines = [f"Correct on {a['necklace']['correct']} of {a['necklace']['of']} held-out test cases"
             + (f", against {a['best_single']['correct']} of {a['best_single']['cases']} for the best single agent on "
                f"the same cases" if a.get("best_single") else "") + "."]
    lines.append(f"One call answered in {tm['p50'] / 1000:.1f} s (median) and {tm['p95'] / 1000:.1f} s (95th percentile), "
                 "measured on our server path.")
    full = t.get("ratio_full_to_necklace")
    reads = t.get("ratio_member_answers_to_necklace")
    if full and full > 1:
        lines.append(f"Calling the same agents yourself means reading about {full:g} times as many tokens once finding "
                     "and merging are counted (estimated, characters / 4).")
    elif reads:
        lines.append(f"The member answers alone are {reads:g} times the size of the necklace answer (estimated, "
                     "characters / 4); the saving is in not finding and merging them yourself.")
    return lines


def readme(m: dict, verdict: dict | None) -> str:
    a, t, tm, fb = m["accuracy"], m["tokens"], m["time_ms"], m["fallbacks"]
    ok = passed(verdict)
    rows = "\n".join(f"| {s['member']} | {s['correct']}/{s['cases']} | {s['rate']:.0%} | {s['necklace_rate_same_cases']:.0%} |"
                     for s in a["singles"]) or "| (단일 멤버 줄 없음) | - | - | - |"
    pub = "\n".join("- " + x for x in public_lines(m)) if ok else (
        "- 공개 금지: 이 회차의 판정 파일이 통과를 말하지 않습니다(판정 전이거나 미통과). 홍보에는 쓰지 않습니다.")
    return f"""# 목걸이 효과: {m['slug']} ({m['split']})

자동 생성(scripts/necklace_value_report.py). 회차 원자료(retest 줄)에서만 계산했고, 재지 않은 숫자는 넣지 않았습니다.

## 1. 정답률
- 목걸이: {a['necklace']['correct']}/{a['necklace']['of']} ({(a['necklace']['rate'] or 0):.0%}), 실행 {m['cases_run']}건, 제외 {m['excluded']}건 {m['excluded_why'] or ''}
- 같은 사례의 단일 멤버:

| 멤버 | 맞힘 | 정답률 | 같은 사례 목걸이 |
|---|---|---|---|
{rows}

- Δ(목걸이 − 최고 단일, 같은 사례): {a['delta_points']}%p

## 2. 사례당 시간({path_label(verdict)})
- p50 {tm['p50']} ms, p95 {tm['p95']} ms. 공개 주소 기준 시간은 공개 뒤 user_slo로 따로 잽니다.

## 3. 토큰(추정: 글자 수 ÷ 4, 양쪽 같은 규칙)
- 목걸이 답 1회: 중앙값 {t['necklace_answer']['median']}, p95 {t['necklace_answer']['p95']}
- 멤버를 직접 부를 때 읽는 답(같은 회차의 멤버 호출 전부): 중앙값 {t['agent_reads_member_answers']['median']} (비율 {t.get('ratio_member_answers_to_necklace')})
- 찾기·정리 포함 전체 값: 중앙값 {t['agent_full_with_finding_and_merging']['median']} (비율 {t.get('ratio_full_to_necklace')}), 추정 부분: {', '.join(t['agent_full_with_finding_and_merging']['estimated_parts']) or '없음'}

## 4. 대체 발생
- 필수 자리를 첫 멤버가 아닌 다음 멤버가 답한 사례: {fb['cases']}건 {fb['by_slot']}
- 실패한 멤버 호출(상위): {json.dumps(fb['failed_member_calls'], ensure_ascii=False)}

## 5. 공개용 영어 문장
{pub}
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("slug")
    p.add_argument("split")
    p.add_argument("day")
    p.add_argument("--root", type=Path, default=Path("gateway-data/necklaces"))
    p.add_argument("--logs", type=Path, default=Path("logs/ops/necklace-gate"))
    p.add_argument("--out", type=Path, default=Path("reports"))
    p.add_argument("--version", type=int)
    ns = p.parse_args(argv)
    m = measure(read_lines(ns.root, ns.day), ns.slug, ns.split, ns.version)
    if not m["graded"]:
        print(json.dumps({"error": "no graded case lines for this slug, split and day"})); return 1
    verdict = verdict_for(ns.slug, ns.day, ns.logs)
    folder = ns.out / f"necklace-value-{ns.slug}-{ns.day}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "value.json").write_text(json.dumps({**m, "verdict": verdict}, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
    (folder / "README.md").write_text(readme(m, verdict), encoding="utf-8")
    print(json.dumps({"written": str(folder), "graded": m["graded"], "public": passed(verdict)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
