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


def test_old_scores_flat_latency_and_superseded_profile_are_fixed():
    md = ("> [!NOTE]\n> **AQEF-30 grade correction (2026-11-10)**: Grade **B** | AQEF-30 Score: **89.4/100**.\n\n"
          "> [!NOTE]\n> **AQEF-30 Quality Profile**: Recorded Grade **A** | Recorded Score: **96.4/100**.\n\n"
          "## Measured Facts\n\n| Check | Observed |\n| --- | --- |\n| Streaming declared | False |\n"
          "| Latency (p50 / p95 / jitter) | 242 ms / 242 ms / ±0 ms (1 trial) |\n\n"
          "The recorded AQEF-30 score of 96.4/100 reflects a card check.\n")
    r = report(eval_score=89.4, content_md=md, executed_at=1762750000.0,
               pros=json.dumps(['9 tool(s) listed; 9 documented, 9 with input schemas.', 'Fast.']),
               cons=json.dumps(['The recorded grade A and score 96.4/100 rest on a card fetch.']))
    new, _ = rc.normalize(r)
    out = new['content_md']
    assert rc.check(new) == [] and '96.4' not in out + new['cons']
    assert 'Quality Profile' not in out and '| false |' in out
    assert '242 ms (one trial; p95 and jitter not measurable)' in out and '±0' not in out
    assert 'counted from the live tools/list response' in new['pros']
    assert 'recorded grade B' in new['cons'] and rc.SCORE_BASIS in out
    assert '| Evidence | Probe executed 2025-11-10' in out


def test_mcp_total_and_step_statistics_are_worded_consistently():
    text = 'Completed initialize and tools/list in 1288 ms total (step p50: 690 ms, p95: 702 ms, jitter: ±40 ms).'
    out = rc.fix_step_text(text)
    assert 'for the two calls' in out and 'median 690 ms, slowest 702 ms, range 40 ms' in out and 'p95' not in out
    row = '| Step latency (p50 / p95 / jitter) | 690 ms / 702 ms / ±40 ms (3 RPC steps) |'
    assert rc.fix_step_text(row) == '| Request latency (median / slowest / range) | 690 ms / 702 ms / 40 ms (3 requests) |'
    assert rc.fix_step_text('(HTTP 200, 1288 ms total, AQEF-30') == '(HTTP 200, 1288 ms for initialize and tools/list, AQEF-30'
    assert rc.fix_step_text(out) == out


def test_transport_label_with_a_real_call_is_detected():
    assert rc.executed_method({'test_method': 'MCP Tools List', 'input_wire': '{"method": "tools/call"}'}) == 'MCP Tool Call'
    assert rc.executed_method({'test_method': 'MCP Tools List', 'input_wire': '{"query": "Vail"}'}) == 'MCP Tool Call'
    assert rc.executed_method({'test_method': 'A2A Agent Card',
                               'input_wire': '{"jsonrpc": "2.0", "method": "agent.route"}'}) == 'A2A Message'
    assert rc.executed_method({'test_method': 'A2A Agent Card', 'input_wire': '{"method": "GET (3-probe burst)", "trials": 3}'}) is None
    assert rc.executed_method({'test_method': 'MCP Tools List',
                               'input_wire': '{"method": "POST initialize + tools/list", "trials": 3}'}) is None


def test_dropped_pros_and_cons_sections_come_back_from_the_fields():
    md = '## Verification Summary\n\nx\n\n## Scope\n\ny\n\n## Recommended Workflow Integration\n\nNew workflow.\n'
    new, applied = rc.normalize(report(content_md=md))
    assert 'C19' in applied and rc.check(new) == []
    assert new['content_md'].index('### Pros') < new['content_md'].index('## Scope')
