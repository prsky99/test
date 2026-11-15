"""R81 (precision review 11-15): agent-facing documents say the same as the code — up to three agents, the score
parts from the scoring code, no screen menu order in llms.txt, and x402 as it is run (collection paused, grade B cap)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rank_rule_is_built_from_the_scoring_weights():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import data_quality as DQ
    import report_v2 as V
    text = V.rank_rule()
    assert f'data quality {sum(DQ.WEIGHTS.values())}' in text and f'evidence {sum(DQ.EVIDENCE_WEIGHTS.values())}' in text
    assert f'report text {DQ.WRITING_WEIGHT}' in text and f'{V.PASS_MARK}+' in text and 'writing 40' not in text


def test_agent_front_and_llms_say_up_to_three_and_x402_as_run():
    front_doc = (ROOT / 'AGENT_FRONT.md').read_text()
    assert 'returns one relevant agent' not in front_doc and 'up to three relevant agents' in front_doc
    from agent_market.concierge.front import llms_txt
    text = llms_txt('https://agentconcierge.biz', {}, None)
    assert 'navigation item follows' not in text
    assert 'new x402 collection is paused' in text and 'grade is at most B' in text
