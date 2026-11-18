"""The gate numbers in code match deploy/NECKLACE_GATE.md and stay consistent (11-14)."""
from pathlib import Path

from agent_market.necklaces import gate_rules as g

DOC = Path(__file__).resolve().parents[1] / 'deploy/NECKLACE_GATE.md'


def test_numbers_are_consistent():
    assert g.TOTAL == 2 * g.ROUND and g.TOTAL_PASS >= 0.95 * g.TOTAL and g.ROUND_PASS * 2 <= g.TOTAL_PASS
    assert g.SUBSTITUTE_PASS / g.SUBSTITUTE_CASES >= 0.95 and g.COMPLETION == 0.95 and g.P95_MS == 5000
    gate = g.summary()['necklace']                     # 11-18: the necklace gate is the connection test
    assert gate['gate'] == 'connection test' and gate['stage_2_connection_runs'] == 3
    assert gate['accuracy_regraded_at_this_stage'] is False and 'held_out_cases' not in gate


def test_the_document_states_the_same_numbers():
    text = DOC.read_text(encoding='utf-8')
    for phrase in ('57/60', '28/30', '4시간', '29/30', '5초', '95%'):
        assert phrase in text, phrase


def test_published_retest_rules_are_the_ones_that_run():
    """Growth 11-15: the machine page said retest pass_rate 0.95 and an immediate hold, neither of which runs."""
    from agent_market.necklaces import connect_gate
    after = g.summary()['after_opening']               # 11-18: one connection run a day is the lifespan
    assert 'retest' not in g.summary() and after['connection_runs_a_day'] == 1
    assert after['held_when'].endswith(f'{connect_gate.DAILY_STALE_HOURS} hours')
