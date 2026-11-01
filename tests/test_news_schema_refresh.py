"""An explicit output-only schema review cannot override unrelated security gates."""
import copy
import json
import sqlite3
import stat
import time

import httpx
import pytest

from agent_market.capability_registry import Registry, digest, full_tools, known_schema_failure
from agent_market.collector import usage
from agent_market.concierge.notify import Courier
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store
from agent_market.workflow_templates import NEWS_URL, definitions
from agent_market.workflows import WorkflowRuntime
from scripts import refresh_news_schema as refresh
from tests.test_workflow_runtime import wait
from tests.test_workflow_template_catalog import RecipeTransport, register


@pytest.fixture
def reviewed(tmp_path,monkeypatch):
    transport=RecipeTransport();base=transport.tools[NEWS_URL]['trending']
    old=[]
    for name in ('trending','trending_digest'):
        tool=copy.deepcopy(base);tool['name']=name
        tool['outputSchema']={'type':'object','properties':{'as_of':{'type':['string','null'],'description':'Optional observation timestamp'}},'required':[]}
        old.append(tool)
    new=copy.deepcopy(old)
    for tool in new:
        schema=tool['outputSchema'];schema['properties']['as_of']={'type':'string','description':'Observation timestamp'}
        schema['properties']['source']={'type':'object','properties':{'name':{'type':'string'},'url':{'type':'string'}}}
        schema['required']=['as_of','source']
    monkeypatch.setattr(refresh,'BEFORE',digest(full_tools(old)))
    monkeypatch.setattr(refresh,'APPROVED',digest(full_tools(new)))
    monkeypatch.setattr(refresh,'COMPACT',usage.tools_hash(usage.compact_tools(new)))
    transport.tools[NEWS_URL]={tool['name']:tool for tool in new}
    proof_path=tmp_path/'proof.sqlite3';proof=register(Store(str(proof_path)),transport)
    for endpoint,tools in transport.tools.items():
        rid=proof.query('SELECT id FROM resources WHERE url=?',(endpoint,))[0][0]
        compact=usage.compact_tools(list(tools.values()))
        proof.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},changes=None,trial=None,full_tools=list(tools.values()))
    with proof.tx()as db:db.execute("UPDATE resources SET health_status='healthy',eval_security='ok',auth_observed=0")
    client=httpx.Client(transport=transport);runtime=WorkflowRuntime(proof,McpProxy(proof,allow_private=True,http=client),Courier())
    workflow=next(row for row in proof.list_workflows(is_template=1)[0]if row['name']==definitions()[0]['name'])
    for _ in range(2):assert wait(runtime,runtime.submit(workflow,actor='isolated',source='verification'))['status']=='succeeded'
    resource=dict(proof.query('SELECT * FROM resources WHERE url=?',(NEWS_URL,))[0])
    meta={'resource_key':resource['key'],'url':NEWS_URL,'before_full_hash':refresh.BEFORE,'approved_full_hash':refresh.APPROVED,
          'compact_hash':refresh.COMPACT,'input_annotations_names_unchanged':True,'reviewed_output_schema_paths':8}
    with proof.tx()as db:db.execute('INSERT INTO meta(key,value)VALUES(?,?)',('reviewed_news_schema_v1',json.dumps(meta)))
    path=tmp_path/'target.sqlite3'
    connection=sqlite3.connect(path);proof._db.backup(connection);connection.close()
    store=Store(str(path));rid=resource['id']
    with store.tx()as db:
        db.execute("UPDATE resources SET usage_full_tools=?,usage_full_hash=?,health_status='quarantined' WHERE id=?",(json.dumps(full_tools(old)),refresh.BEFORE,rid))
    registry=Registry(store);now=time.time();registry.record(registry.current(rid),scope='execution',outcome='failed',started=now,finished=now,code='SCHEMA_CHANGED')
    try:yield store,proof,path,proof_path,tmp_path/'private-backups',rid
    finally:client.close();proof._db.close();store._db.close()


def rows(store,table):
    return [tuple(row)for row in store.query('SELECT * FROM '+table+' ORDER BY 1')]


def test_dry_run_private_output_and_apply_preserve_history(reviewed,capsys):
    store,proof,path,proof_path,backup,rid=reviewed
    before=store.resource(rid);history=rows(store,'capability_evidence');runs=rows(store,'workflow_runs')
    source_before=rows(proof,'resources');workflows=rows(store,'agent_workflows')
    assert refresh.main(['--db',str(path),'--proof-db',str(proof_path)])==0
    output=capsys.readouterr();assert not output.err and 'https://'not in output.out and 'schema'not in output.out.replace('reviewed_output_schema_paths','').replace('schema_quarantine_cleared','')
    assert json.loads(output.out)['eligible']==1 and store.resource(rid)==before and not backup.exists()
    result=refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)
    assert result['changed']==1 and result['schema_quarantine_cleared']
    assert store.resource(rid)['usage_full_hash']==refresh.APPROVED and not known_schema_failure(store,store.resource(rid))
    assert store.resource(rid)['health_status']=='healthy'and store.resource(rid)['eval_security']==before['eval_security']
    assert rows(store,'capability_evidence')==history and rows(store,'workflow_runs')==runs
    assert rows(store,'agent_workflows')==workflows and rows(proof,'resources')==source_before
    files=list(backup.glob('*.json'));assert len(files)==1
    assert stat.S_IMODE(backup.stat().st_mode)==0o700 and stat.S_IMODE(files[0].stat().st_mode)==0o600
    saved=json.loads(files[0].read_text());assert saved['before']==before and saved['before_digest']==digest(before)
    assert refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)['changed']==0
    assert len(list(backup.glob('*.json')))==1


@pytest.mark.parametrize('assessment',['quarantine','review'])
def test_security_assessment_never_cleared(reviewed,assessment):
    store,_,path,proof_path,backup,rid=reviewed
    with store.tx()as db:db.execute('UPDATE resources SET eval_security=? WHERE id=?',(assessment,rid))
    before=store.resource(rid)
    with pytest.raises(refresh.ReplacementError,match='security_or_binding'):
        refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)
    assert store.resource(rid)==before and not backup.exists()


def test_unrelated_health_quarantine_not_cleared(reviewed):
    store,_,path,proof_path,backup,rid=reviewed
    with store.tx()as db:db.execute("DELETE FROM capability_evidence WHERE code='SCHEMA_CHANGED'")
    with pytest.raises(refresh.ReplacementError,match='unrelated_health'):
        refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)
    assert store.resource(rid)['health_status']=='quarantined'and not backup.exists()


def test_fsync_failure_keeps_original_row(reviewed,monkeypatch):
    store,_,path,proof_path,backup,rid=reviewed;before=store.resource(rid)
    def fail(_):raise OSError('isolated failure')
    monkeypatch.setattr(refresh.os,'fsync',fail)
    with pytest.raises(OSError):refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)
    assert store.resource(rid)==before


def test_changed_target_after_preflight_is_not_overwritten(reviewed,monkeypatch):
    store,_,path,proof_path,backup,rid=reviewed;original=refresh.Database
    def opened(file,*,readonly=True):
        if not readonly:
            with store.tx()as db:db.execute("UPDATE resources SET description='Concurrent edit' WHERE id=?",(rid,))
        return original(file,readonly=readonly)
    monkeypatch.setattr(refresh,'Database',opened)
    with pytest.raises(refresh.ReplacementError,match='changed_since_preflight'):
        refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)
    assert store.resource(rid)['description']=='Concurrent edit'and not backup.exists()


def test_unexpected_trigger_change_rolls_back(reviewed):
    store,_,path,proof_path,backup,rid=reviewed;before=store.resource(rid)
    with store.tx()as db:db.execute("CREATE TRIGGER unexpected_refresh AFTER UPDATE OF usage_full_hash ON resources BEGIN UPDATE resources SET name='Unexpected' WHERE id=NEW.id; END")
    with pytest.raises(refresh.ReplacementError,match='unexpected_update_result'):
        refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)
    assert store.resource(rid)==before and len(list(backup.glob('*.json')))==1


@pytest.mark.parametrize('mode',['one_run','stale','empty_content','changed_pin'])
def test_missing_or_changed_execution_proof_refused(reviewed,mode):
    store,proof,path,proof_path,backup,rid=reviewed;before=store.resource(rid)
    with proof.tx()as db:
        if mode=='one_run':db.execute('DELETE FROM workflow_runs WHERE id=(SELECT id FROM workflow_runs ORDER BY finished LIMIT 1)')
        elif mode=='stale':db.execute('UPDATE workflow_runs SET finished=?',(time.time()-3600,))
        elif mode=='empty_content':db.execute("UPDATE workflow_node_runs SET output='{}' WHERE node_id='news'")
        else:db.execute("UPDATE resources SET usage_full_hash='unexpected' WHERE url=?",(NEWS_URL,))
    with pytest.raises(refresh.ReplacementError):refresh.refresh_news_schema(path,proof_path,apply=True,backup_directory=backup)
    assert store.resource(rid)==before and not backup.exists()
