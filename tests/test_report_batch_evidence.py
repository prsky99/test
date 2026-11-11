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
