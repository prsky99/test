"""The gate numbers in code match deploy/NECKLACE_GATE.md and stay consistent (11-14)."""
from pathlib import Path

from agent_market.necklaces import gate_rules as g

DOC = Path(__file__).resolve().parents[1] / 'deploy/NECKLACE_GATE.md'


def test_numbers_are_consistent():
    assert g.TOTAL == 2 * g.ROUND and g.TOTAL_PASS >= 0.95 * g.TOTAL and g.ROUND_PASS * 2 <= g.TOTAL_PASS
    assert g.SUBSTITUTE_PASS / g.SUBSTITUTE_CASES >= 0.95 and g.COMPLETION == 0.95 and g.P95_MS == 5000
    assert g.summary()['necklace']['rounds'] == 2


def test_the_document_states_the_same_numbers():
    text = DOC.read_text(encoding='utf-8')
    for phrase in ('57/60', '28/30', '4시간', '29/30', '5초', '95%'):
        assert phrase in text, phrase
