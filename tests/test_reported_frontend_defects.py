"""Guard the reported generator, metadata and legacy date compatibility defects."""
import importlib
from pathlib import Path
import shutil

from agent_market.concierge.public_metadata import apply,robots
from agent_market.gateway.store import Store
from agent_market.report_time import report_timestamp


def test_metadata_changes_only_document_head_and_preserves_embedded_programs():
    program='<script nonce="keep">const sample=`<meta name="description" content="runtime"><title>Runtime</title></head>`;</script>'
    body='<body><script>const app=`<head><meta name="description" content="App"><title>App</title></head>`;</script></body></html>'
    original='<html><head><meta name="description" content="Old">'+program+'</head>'+body
    result=apply(original,'about')
    assert program in result and result.endswith(body)
    assert '<meta name="description" content="Old">' not in result
    assert robots('https://agentconcierge.biz').find('/admin')==-1


def test_account_generation_is_repeatable_and_includes_each_runtime_once(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'new'))
    build=importlib.import_module('build_en')
    out=tmp_path/'generated';out.mkdir();(out/'assets').mkdir()
    for name in ('sign-in','sign-up','workspace','account'):
        shutil.copyfile(root/'new/en'/f'{name}.html',out/f'{name}.html')
    monkeypatch.setattr(build,'OUT',out)
    build.account_pages();first={p:p.read_bytes() for p in out.rglob('*') if p.is_file()}
    build.account_pages();assert all(p.read_bytes()==raw for p,raw in first.items())
    for name,asset in [('sign-in','sign-in-live'),('sign-up','sign-in-live'),('workspace','workspace-live'),('account','workspace-live')]:
        assert (out/f'{name}.html').read_text().count('src="assets/'+asset+'.js"')==1


def test_stored_report_metadata_accepts_documented_legacy_utc_without_execution_evidence():
    store=Store()
    try:
        rid=store.create_test_report({'title':'Legacy metadata','kind':'mcp','agent_url':'https://legacy.example/mcp',
            'created_at':'2026-10-20T01:23:45','updated_at':'2026-10-20 01:23:45'})
        report=store.get_test_report(rid)
        assert report['created_at']==report['updated_at']==report_timestamp('2026-10-20T01:23:45Z')
        assert report['evidence_scope']=='legacy' and report['executed_at'] is None
    finally:store._db.close()
