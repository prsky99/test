"""personality-fortune-brief tuning set (PM 11-18 14:5x): 30 fixed cases computed from public definitions and the contract's
rule, and the judges."""
from collections import Counter

from agent_market.fallback_agents.agents import FallbackAgents, FallbackUnavailable
from agent_market.fallback_agents.gold_check import SLUG, applies, case_arguments, judge
from agent_market.necklaces import mbti_gate
from datetime import date
from scripts.gold_mbti_tuning import CASES


def run(a, c):
    try:
        return a.execute(c["agent"], case_arguments(c["agent"], c))["result"], None
    except FallbackUnavailable as exc:
        return None, exc.code


def test_thirty_cases_cover_both_agents_all_types_and_the_refusals():
    by = Counter(c["agent"] for c in CASES)
    assert len(CASES) == 30 and by == {"personality-profile": 18, "personality-fortune": 12}
    assert len({c["case_id"] for c in CASES}) == 30
    assert sum(1 for c in CASES if c["truth"].get("refused")) == 2                  # before 1912, after 2100
    assert len({c["truth"]["type"] for c in CASES if c["agent"] == "personality-profile" and "type" in c["truth"]}) == 16
    assert all(SLUG[c["agent"]] == "personality-fortune-brief" and c["truth_sources"][0]["url"].startswith("https://")
               for c in CASES)


def test_the_truth_agrees_with_the_gates_own_rule():
    """The set recomputes the contract's rule on its own; the workflow's gate module must give the same dates."""
    for c in CASES:
        if c["agent"] != "personality-profile" or c["truth"].get("refused"):
            continue
        inp, truth = c["input"], c["truth"]
        today = date.fromisoformat(inp["today"])
        assert mbti_gate.sample_birth_date(inp["type"], inp["age"], today).isoformat() == truth["sample_birth_date"]
        assert [d.isoformat() for d in mbti_gate.sample_range(inp["age"], today)] == truth["sample_range"]


def test_the_substitutes_pass_every_tuning_case(tmp_path):
    a = FallbackAgents(data_dir=tmp_path)
    for c in CASES:
        other = "personality-fortune" if c["agent"] == "personality-profile" else "personality-profile"
        assert applies(c["agent"], c) and not applies(other, c)
        result, error = run(a, c)
        assert judge(c["agent"], c, result, error)["pass"], c["case_id"]


def test_the_judges_fail_wrong_or_invented_answers(tmp_path):
    by_id = {c["case_id"]: c for c in CASES}
    a = FallbackAgents(data_dir=tmp_path)
    case = by_id["personality:entj-41"]
    good, _ = run(a, case)
    assert judge("personality-profile", case, good, None)["pass"]
    other_day = next(d for d in good["sample_range"] if d != good["sample_birth_date"])  # in range, not by the rule
    assert not judge("personality-profile", case, {**good, "sample_birth_date": other_day}, None)["pass"]
    assert not judge("personality-profile", case, {**good, "temperament": "NF"}, None)["pass"]
    refused = by_id["personality:refused-before-1912"]
    assert not judge("personality-profile", refused, good, None)["pass"]                   # answered instead
    assert not judge("personality-profile", refused, None, "source_unavailable")["pass"]   # wrong code
    reading = by_id["personality:read-esfp-bare"]
    out, _ = run(a, reading)
    assert judge("personality-fortune", reading, out, None)["pass"]
    assert not judge("personality-fortune", reading, {**out, "answer": out["answer"].replace(mbti_gate.TRADEMARK, "")},
                     None)["pass"]
    flipped = {**out, "axes": {**out["axes"], "energy": {"letter": "I", "line": "x"}}}
    assert not judge("personality-fortune", reading, flipped, None)["pass"]
