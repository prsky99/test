"""11-10 AQEF-30 grade gate: transport-only probes can never be Grade A (Opus audit: 213/300 grade_inconsistent)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from report_pipeline_common import compute_aqef_score_and_grade, probe_evidence_scope  # noqa: E402


def test_probe_scope_from_method():
    assert probe_evidence_scope('A2A Agent Card') == 'transport'
    assert probe_evidence_scope('MCP Tools List') == 'transport'
    assert probe_evidence_scope('x402 Challenge') == 'transport'
    assert probe_evidence_scope('MCP Tool Call') == 'execution'


def test_transport_probe_with_existing_a_becomes_b():
    score, grade = compute_aqef_score_and_grade(kind='mcp', is_success=1, status_code=200, latency_ms=900,
                                                evidence_scope='transport', existing_grade='A', existing_score=97.4)
    assert (grade, score) == ('B', 89.4)


def test_execution_needs_fast_latency_and_ninety():
    assert compute_aqef_score_and_grade(kind='mcp', is_success=1, status_code=200, latency_ms=2240,
                                        evidence_scope='execution', existing_grade='A', existing_score=94.2)[1] == 'B'
    assert compute_aqef_score_and_grade(kind='mcp', is_success=1, status_code=200, latency_ms=800,
                                        evidence_scope='execution', existing_grade='A', existing_score=94.2) == (94.2, 'A')


def test_fresh_transport_probe_is_never_a():
    score, grade = compute_aqef_score_and_grade(kind='a2a', is_success=1, status_code=200, latency_ms=300,
                                                evidence_scope='transport', executed_at=1.0, execution_finished_at=2.0,
                                                connection_version_id='v', pros=['x'], cons=['y'])
    assert grade != 'A' and score <= 89.4


def test_rewrite_text_does_not_match_inside_longer_numbers():
    import fix_transport_grades as fix
    assert fix.rewrite_text('Recorded Score: **99.0/100**.', 99.0, 89.4) == 'Recorded Score: **89.4/100**.'
    assert fix.rewrite_text('AQEF-30 Score: 99/100).', 99.0, 89.4) == 'AQEF-30 Score: 89.4/100).'
    assert fix.rewrite_text('Recorded Grade **A** | x', 99.0, 89.4) == 'Recorded Grade **B** | x'
    assert fix.rewrite_text('AQEF-30 Grade A requires live execution.', 99.0, 89.4) == \
        'AQEF-30 Grade A requires live execution.'


def test_pros_cons_sections_are_added_from_stored_arrays():
    import fix_transport_grades as fix
    md, added = fix.fix_pros_cons('# Report\n', '["fast"]', '["one trial"]')
    assert added and '### Pros\n- fast' in md and '### Cons\n- one trial' in md
    md, added = fix.fix_pros_cons('## Pros\n- a\n\n## Cons\n- b\n', '[]', '[]')
    assert not added and md.startswith('### Pros')
