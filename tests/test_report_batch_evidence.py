"""The nightly report batch records what a probe really was and ends cleanly when nothing can be published (11-12).

11-12 02:30: all 30 drafts were refused at publication ("a connection-only probe is not task execution"), the
submit step exited 1 and the batch ended in a traceback. The drafts came from card / tools/list probes that
were also written to the registry as *execution* evidence. The publication rule itself is unchanged.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_builder(monkeypatch, out, per_kind='2'):
    monkeypatch.setattr(sys, 'argv', ['build_probed_report_drafts.py', per_kind, str(out)])
    spec = importlib.util.spec_from_file_location('build_probed_report_drafts', ROOT / 'scripts/build_probed_report_drafts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_connection_only_probe_is_recorded_as_transport_and_drafts_nothing(monkeypatch, tmp_path):
    builder = _load_builder(monkeypatch, tmp_path / 'drafts')
    monkeypatch.setenv('ADMIN_SESSION_TOKEN', 'x' * 32)
    monkeypatch.setenv('REPORT_KINDS', 'mcp')
    agents = [{'id': n, 'name': f'Agent {n}', 'url': f'https://agent{n}.example/mcp', 'kind': 'mcp'} for n in range(1, 20)]

    def live_api(token, path):
        if path.startswith('/admin/api/agents?'):
            return {'items': agents if 'grade=A' in path else []}
        if path.startswith('/admin/api/test-reports/existing'):
            return {'ok': True, 'exists': False, 'can_create': True}
        return {'agent': {}}
    recorded = []
    monkeypatch.setattr(builder, 'live_api', live_api)
    monkeypatch.setattr(builder, 'public_https', lambda url: True)
    monkeypatch.setattr(builder, 'is_excluded_agent', lambda res: (False, None))
    monkeypatch.setattr(builder, 'probe_mcp', lambda res: {'ok': True, 'method': 'MCP Tools List', 't0': 1.0, 't1': 2.0,
                                                           'code': 200, 'ms': 120.0})
    monkeypatch.setattr(builder, 'safe_current_version', lambda registry, rid: {'id': rid})
    monkeypatch.setattr(builder, 'safe_record_evidence', lambda registry, ver, **kw: recorded.append(kw['scope']))
    monkeypatch.setattr(builder.GatewayConfig, 'from_env', classmethod(lambda cls: type('C', (), {'db_path': ':memory:'})()))
    monkeypatch.setattr(builder, 'open_runtime_storage', lambda path: type('S', (), {'store': None})())
    monkeypatch.setattr(builder, 'Registry', lambda store: None)

    assert builder.main() == 0                                   # a normal outcome, no exit 1
    assert recorded and set(recorded) == {'transport'}           # never written as execution evidence
    assert len(recorded) == 2 * builder.PROBE_FACTOR              # outbound probes are bounded
    assert not list((tmp_path / 'drafts').glob('*.json'))        # nothing that publication would refuse


def test_submit_withholds_transport_only_drafts_without_failing(tmp_path):
    draft = {'kind': 'mcp', 'resource_id': 7, 'is_success': 1, 'evidence_scope': 'transport'}
    (tmp_path / 'mcp_7.json').write_text(json.dumps(draft))
    done = subprocess.run([sys.executable, str(ROOT / 'scripts/submit_report_drafts.py'), str(tmp_path), '--dry-run'],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'withheld=1 failed=0 reason=no_execution_evidence' in done.stdout
    assert 'connection-only probe is not task execution' in done.stdout   # the rule still applies


def test_a_recorded_collector_trial_turns_an_mcp_candidate_into_an_execution_report(monkeypatch, tmp_path):
    """11-12: the collector's read-only trial call is the version's latest execution evidence; the draft reuses its
    exact start and finish (publication matches them) and records nothing new."""
    builder = _load_builder(monkeypatch, tmp_path / 'drafts')
    now = 1794460000.0
    trial = {'tool': 'get_growth_metrics', 'arguments': '{"region": "kr"}', 'at': now - 600.25, 'ok': True,
             'output_chars': 5530, 'latency_ms': 50, 'finished_at': now - 600.2,
             'sample_output': '{"schema": "kallipolis.growth-metrics.v1", "metrics": [{"name": "users"}]}'}

    class Store:
        def __init__(self, row): self.row = row
        def query(self, sql, params):
            assert sql == builder.LATEST_EXECUTION and params == ('v1',)
            return [self.row] if self.row else []
    evidence = {'scope': 'execution', 'outcome': 'succeeded', 'started': now - 600.25, 'finished': now - 600.2,
                'expires': now + 86400}
    found = builder.recorded_trial(Store(evidence), {'trial_info': json.dumps(trial)}, {'id': 'v1'}, now=now)
    assert found == {'tool': 'get_growth_metrics', 'output_chars': 5530, 'latency_ms': 50.0, 'argument_names': ['region'],
                     'started': now - 600.25, 'finished': now - 600.2}
    # a newer failed run, a different timestamp, an expired or missing record: no execution report
    for row in ({**evidence, 'outcome': 'failed'}, {**evidence, 'started': now - 10}, None):
        assert builder.recorded_trial(Store(row), {'trial_info': json.dumps(trial)}, {'id': 'v1'}, now=now) is None
    # past its expiry but within a week: still the exact record publication matches; older than a week: not used
    assert builder.recorded_trial(Store({**evidence, 'expires': now - 1}), {'trial_info': json.dumps(trial)}, {'id': 'v1'}, now=now)
    assert builder.recorded_trial(Store(evidence), {'trial_info': json.dumps(trial)}, {'id': 'v1'}, now=now + 8 * 86400) is None
    # the tool must still be on the server's list from this run's probe
    assert builder.recorded_trial(Store(evidence), {'trial_info': json.dumps(trial)}, {'id': 'v1'}, now=now, listed={'other'}) is None
    assert builder.recorded_trial(Store(evidence), {'trial_info': json.dumps({**trial, 'ok': False})}, {'id': 'v1'}, now=now) is None

    res = {'id': 7, 'kind': 'mcp', 'name': 'Kallipolis Metrics', 'url': 'https://kallipolis.example/mcp', 'category': 'data_analytics',
           'health_status': 'healthy', 'active': 1, 'eval_grade': 'A', 'description': 'Growth metrics for audits.'}
    p = {'ok': True, 'code': 200, 'ms': 50.0, 'handshake_ms': 420.0, 'p50_ms': 140.0, 'p95_ms': 160.0, 'jitter_ms': 20.0, 'trials': 3,
         'method': 'MCP Tool Call', 't0': found['started'], 't1': found['finished'], 'trial': found,
         'request': 'initialize, tools/list and one read-only tools/call recorded by the catalog collector',
         'data': {'init': {'protocolVersion': '2025-06-18', 'serverInfo': {'name': 'kallipolis', 'version': '1.1.0'}},
                  'tools': [{'name': 'get_growth_metrics', 'description': 'Metrics', 'inputSchema': {'type': 'object'}}]}}
    rec = builder.build(res, p, version_id='v1')
    assert rec['evidence_scope'] == 'execution' and rec['test_method'] == 'MCP Tool Call' and rec['is_success'] == 1
    assert rec['executed_at'] == found['started'] and rec['execution_finished_at'] == found['finished']
    assert rec['tool_name'] == 'get_growth_metrics' and rec['output_wire']['tool_call']['output_chars'] == 5530
    assert 'No tool was invoked' not in rec['content_md'] and builder.lint(rec) == []


def test_a_trial_that_answered_with_failure_or_nothing_is_not_evidence(monkeypatch, tmp_path):
    """PM 11-12: three reports stood on {"ok": false} and one on an empty guide list; such trials are not used."""
    builder = _load_builder(monkeypatch, tmp_path / 'drafts')
    for sample in ('{"ok":false}', '{"success": false, "data": {"x": 1}}', '{"guides":[],"directory":"https://clefdrills.com/x"}',
                   '[]', '', None):
        assert builder.empty_or_refused(sample), sample
    for sample in ('{"count": 122, "destinations": [{"slug": "london"}]}', '1 newest incident: Git flaw',
                   '{"total_matching":16,"returned":1,"signals":[{"id":"s-001"}]}', '{"answer": "Found 1 asset", "facts": []}'):
        assert not builder.empty_or_refused(sample), sample
