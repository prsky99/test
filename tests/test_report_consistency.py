import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_consistency as rc  # noqa: E402

MD = """## Verification Summary

Bruntet was probed. Result: **passed** (HTTP 200, 49 ms, AQEF-30 Score: 91.0/100).

## Measured Facts

| Check | Observed |
| --- | --- |
| Agent name | Bruntet |

Provider description: Bruntet

### Pros

- Card served in 49 ms.
- Streaming is declared as unsupported.

### Cons

- Old con.

## Scope

Agent Card retrieval only.

## Recommended Workflow Integration

Old workflow.
"""


def report(**over):
    base = {'id': 1, 'test_method': 'A2A Agent Card', 'evidence_scope': 'transport', 'eval_grade': 'B',
            'eval_score': 89.2, 'latency_ms': 49.1, 'agent_name': 'Bruntet',
            'pros': json.dumps(['Card served in 49 ms.', 'Streaming is declared as unsupported.']),
            'cons': json.dumps(['Task execution was not tested.']), 'workflow_recommendation': 'New workflow.',
            'content_md': MD, 'output_wire': json.dumps({'telemetry': {'p50_ms': 49.1, 'p95_ms': 49.1,
                                                                        'jitter_ms': 0.0, 'trials': 1}})}
    base.update(over)
    return base


def test_normalize_fixes_every_rule_and_is_idempotent():
    r = report()
    assert set(rc.check(r)) >= {'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7'}
    new, applied = rc.normalize(r)
    assert rc.check(new) == []
    md = new['content_md']
    assert 'AQEF-30 Score: 89.2/100, Grade B' in md
    assert rc.SCOPE_SENTENCE in md and '| Recorded latency (unrounded) | 49.1 ms |' in md
    assert '- Task execution was not tested.' in md and 'Old con' not in md
    assert 'New workflow.' in md and 'Old workflow' not in md
    assert rc.EMPTY_DESCRIPTION in md and rc.EMPTY_DESCRIPTION_CON in json.loads(new['cons'])
    assert 'Streaming is declared as unsupported.' in json.loads(new['cons'])
    assert json.loads(new['output_wire'])['telemetry']['p95_ms'] is None
    again, applied_again = rc.normalize(new)
    assert again == new and applied_again == []


def test_execution_reports_need_no_transport_sentence_and_text_lists_become_json():
    r = report(test_method='MCP Tool Call', pros='Fast; Small', cons='Few tools.', content_md='# R\n')
    new, _ = rc.normalize(r)
    assert rc.SCOPE_SENTENCE not in new['content_md']
    assert json.loads(new['pros']) == ['Fast.', 'Small.'] and rc.check(new) == []


def test_restored_records_get_the_historical_note():
    new, applied = rc.normalize(report(evidence_scope='legacy', test_method='MCP Tool Call', content_md='# R\n'))
    assert 'C8' in applied and new['content_md'].startswith('> Historical record')
