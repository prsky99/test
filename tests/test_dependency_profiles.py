"""Optional dependencies must not become required to import the service."""
import builtins
import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize('module,class_name',[
    ('agent_market.services','ClaudeWorker'),
    ('agent_market.broker.classifier','ClaudeClassifier'),
])
def test_claude_dependencies_are_only_required_for_explicit_provider_use(monkeypatch,module,class_name):
    original=builtins.__import__
    def without_sdk(name,*args,**kwargs):
        if name=='anthropic' or name.startswith('anthropic.'):
            raise ImportError('isolated missing optional SDK')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',without_sdk)
    imported=importlib.reload(importlib.import_module(module))
    fake=object()
    assert getattr(imported,class_name)(client=fake).client is fake
    with pytest.raises(RuntimeError,match='requirements-anthropic.txt'):
        getattr(imported,class_name)()


def test_profile_audit_understands_extras_and_rejects_unexpected_installs(monkeypatch,tmp_path):
    from scripts import audit_dependency_profile as audit
    (tmp_path/'requirements-runtime.lock').write_text('psycopg[binary]==3.3.6\n')
    class Distribution:
        def __init__(self,name,version):
            self.metadata={'Name':name};self.version=version
    monkeypatch.setattr(audit,'ROOT',tmp_path)
    monkeypatch.setattr(audit.metadata,'distributions',lambda:[Distribution('psycopg','3.3.6'),Distribution('pip','26.2.2')])
    assert audit.inspect('runtime',check_native=False)['ok']
    monkeypatch.setattr(audit.metadata,'distributions',lambda:[Distribution('psycopg','3.3.6'),Distribution('sqlite_vec','0.1.9')])
    report=audit.inspect('runtime',check_native=False)
    assert not report['ok'] and report['unexpected']==['sqlite-vec']


def test_production_profile_separates_test_tools_and_optional_providers():
    root=Path(__file__).resolve().parents[1]
    from scripts.audit_dependency_profile import canonical
    import re
    names={canonical(name) for name in re.findall(r'^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==',(root/'requirements-runtime.lock').read_text(),re.M)}
    assert {'psycopg','psycopg-c','fastapi','starlette','certifi','redis','cryptography'} <= names
    assert not names & {'pytest','playwright','sqlite-vec','anthropic','pip-audit','pip-tools','setuptools','wheel'}


@pytest.mark.skipif(__import__('sys').platform!='darwin',reason='Reviewed macOS native linkage policy')
def test_native_guard_rejects_unreviewed_linkage(monkeypatch,tmp_path):
    import json
    from scripts import audit_dependency_profile as audit
    root=Path(__file__).resolve().parents[1]
    spec=json.loads((root/'deploy/runtime-versions.json').read_text())
    spec['libpq']['directory']='unreviewed-client'
    (tmp_path/'deploy').mkdir()
    (tmp_path/'deploy/runtime-versions.json').write_text(json.dumps(spec))
    monkeypatch.setattr(audit,'ROOT',tmp_path)
    result=audit.native_libraries({'psycopg-c':'3.3.6'})
    assert result['checked'] and not result['ok']


@pytest.mark.skipif(__import__('sys').platform!='darwin',reason='Reviewed macOS native linkage policy')
def test_native_guard_rejects_a_changed_trust_bundle(monkeypatch):
    import sys,json
    from scripts import audit_dependency_profile as audit
    root=Path(__file__).resolve().parents[1]
    spec=json.loads((root/'deploy/runtime-versions.json').read_text())
    ca=Path(sys.base_prefix).parent/spec['openssl']['directory']/'ssl/cert.pem'
    original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda path:b'changed fixture' if path==ca else original(path))
    result=audit.native_libraries({'psycopg-c':'3.3.6'})
    assert result['checked'] and not result['ok'] and not result['trust_bundle_matches']
