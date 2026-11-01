"""An explicit proven replacement preserves published IDs, history and consent."""
import json
import os
import sqlite3
import stat

import pytest

from agent_market.gateway.store import Store
from agent_market.workflow_templates import bind_resources, definitions
from agent_market.workflows import WorkflowRuntime
from scripts import replace_news_workflow as migration
from tests.test_workflow_template_catalog import verified, register  # noqa: F401


@pytest.fixture
def destination(verified,tmp_path):
    proof,transport=verified
    path=tmp_path/'target.sqlite3'
    store=register(Store(str(path)),transport)
    # The controlled transport completed its calls; public admission also needs
    # an explicit recorded health/auth fixture, independent of execution proofs.
    for catalog in (proof,store):
        with catalog.tx()as db:
            db.execute("UPDATE resources SET health_status='healthy',eval_security='ok',auth_observed=0")
    rid=store.upsert_resource({'key':'old-news','kind':'mcp','source':'isolated',
        'name':'Legacy news','url':migration.OLD_URL,'description':'Legacy test provider',
        'category':'data_utility','price_usdc':0})
    old=migration.legacy_definition()
    workflow=next(w for w in store.list_workflows(is_template=1)[0]if w['name']==old['name'])
    store.update_workflow(workflow['id'],bind_resources(store,old))
    runtime=WorkflowRuntime(store)
    with store.tx()as db:
        db.execute("INSERT INTO workflow_runs(id,workflow_id,digest,snapshot,actor,source,status,created) VALUES('retained-history',?,'old','{}','fixture','verification','failed',1)",(workflow['id'],))
    try:yield store,proof,path,tmp_path/'private-backups',workflow['id']
    finally:store._db.close()


def table(store,name):
    return [tuple(row)for row in store.query('SELECT * FROM '+name+' ORDER BY 1')]


def test_dry_run_does_not_change_databases_or_disclose_provider_data(destination,capsys):
    store,proof,path,backup,_=destination
    before=table(store,'agent_workflows');proof_changes=proof._db.total_changes
    assert migration.main(['--db',str(path),'--proof-db',proof.path])==0
    output=capsys.readouterr();result=json.loads(output.out)
    assert result['eligible']==1 and result['changed']==0 and result['mode']=='dry_run'
    assert table(store,'agent_workflows')==before and proof._db.total_changes==proof_changes
    assert not backup.exists() and not output.err
    assert 'https://'not in output.out and 'run_key'not in output.out and 'snapshot'not in output.out


def test_apply_preserves_ids_history_other_templates_and_private_backup(destination):
    store,proof,path,backup,wid=destination
    history=table(store,'workflow_runs');seeds=table(store,'workflow_seed_registry')
    other=[tuple(r)for r in store.query('SELECT * FROM agent_workflows WHERE id<>? ORDER BY id',(wid,))]
    original=dict(store.query('SELECT * FROM agent_workflows WHERE id=?',(wid,))[0])
    resources=table(store,'resources')
    result=migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert result['changed']==1 and result['resources_modified']==result['historical_runs_modified']==0
    current=store.get_workflow(wid);expected=bind_resources(store,definitions()[0])
    assert current['id']==wid and current['nodes']==expected['nodes'] and current['edges']==expected['edges']
    assert current['description']==expected['description']
    assert table(store,'workflow_runs')==history and table(store,'workflow_seed_registry')==seeds
    assert table(store,'resources')==resources
    assert [tuple(r)for r in store.query('SELECT * FROM agent_workflows WHERE id<>? ORDER BY id',(wid,))]==other
    files=list(backup.glob('*.json'));assert len(files)==1
    assert stat.S_IMODE(backup.stat().st_mode)==0o700 and stat.S_IMODE(files[0].stat().st_mode)==0o600
    saved=json.loads(files[0].read_text());assert saved['before']==original
    assert saved['before_digest']==migration.digest(original)
    again=migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert again['changed']==again['eligible']==0 and len(list(backup.glob('*.json')))==1


@pytest.mark.parametrize('change',[{'name':'My reviewed news title'},{'description':'My saved description'},
                                  {'tags':'custom-saved-tags'},{'is_active':0}])
def test_saved_variations_are_never_overwritten(destination,change):
    store,proof,path,backup,wid=destination
    store.update_workflow(wid,change);before=table(store,'agent_workflows')
    with pytest.raises(migration.ReplacementError,match='was_edited'):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert table(store,'agent_workflows')==before and not backup.exists()


def test_custom_graph_is_not_replaced(destination):
    store,proof,path,backup,wid=destination
    workflow=store.get_workflow(wid);workflow['nodes'][1]['data']['input']['limit']=1
    store.update_workflow(wid,workflow)
    with pytest.raises(migration.ReplacementError,match='legacy_graph_was_edited'):
        migration.replace_news_workflow(path,proof.path)
    assert not backup.exists()


def test_protocol_success_without_actual_source_items_is_not_proof(destination):
    store,proof,path,backup,_=destination
    with proof.tx()as db:
        db.execute("UPDATE workflow_node_runs SET output=? WHERE node_id='news'",(json.dumps({'text':'Quota guidance with a dashboard link'}),))
    before=table(store,'agent_workflows')
    with pytest.raises(migration.ReplacementError,match='source_backed_content_required'):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert table(store,'agent_workflows')==before and not backup.exists()


def test_changed_registered_schema_refuses_replacement(destination):
    store,proof,path,backup,_=destination
    with store.tx()as db:
        db.execute("UPDATE resources SET usage_tools_hash='changed' WHERE url=?",(definitions()[0]['nodes'][1]['data']['resource_ref']['url'],))
    before=table(store,'agent_workflows')
    with pytest.raises(migration.ReplacementError,match='replacement_connection_changed'):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert table(store,'agent_workflows')==before and not backup.exists()


def test_backup_fsync_failure_prevents_update(destination,monkeypatch):
    store,proof,path,backup,_=destination
    before=table(store,'agent_workflows')
    def fail(_):raise OSError('isolated backup failure')
    monkeypatch.setattr(migration.os,'fsync',fail)
    with pytest.raises(OSError):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert table(store,'agent_workflows')==before


def test_backup_directory_permissions_and_symlinks_are_rejected(destination,tmp_path):
    store,proof,path,backup,_=destination
    backup.mkdir(mode=0o755);backup.chmod(0o755)
    with pytest.raises(migration.ReplacementError,match='private_backup'):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    backup.rmdir();actual=tmp_path/'actual';actual.mkdir(mode=0o700);backup.symlink_to(actual,target_is_directory=True)
    with pytest.raises(migration.ReplacementError,match='private_backup'):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)


def test_changed_target_after_preflight_aborts_without_backup(destination,monkeypatch):
    store,proof,path,backup,wid=destination
    original=migration.Database
    def opened(file,*,readonly=True):
        if not readonly:store.update_workflow(wid,{'description':'Concurrent saved change'})
        return original(file,readonly=readonly)
    monkeypatch.setattr(migration,'Database',opened)
    with pytest.raises(migration.ReplacementError,match='was_edited|changed_since_preflight'):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert store.get_workflow(wid)['description']=='Concurrent saved change' and not backup.exists()


def test_transaction_failure_keeps_original_and_retains_durable_backup(destination):
    store,proof,path,backup,wid=destination
    before=table(store,'agent_workflows')
    with store.tx()as db:
        db.execute("CREATE TRIGGER refuse_replacement BEFORE UPDATE ON agent_workflows BEGIN SELECT RAISE(ABORT,'isolated refusal'); END")
    with pytest.raises(sqlite3.IntegrityError):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert table(store,'agent_workflows')==before and len(list(backup.glob('*.json')))==1


def test_unexpected_trigger_row_changes_roll_back(destination):
    store,proof,path,backup,wid=destination
    before=table(store,'agent_workflows')
    with store.tx()as db:
        db.execute("CREATE TRIGGER mutate_title AFTER UPDATE ON agent_workflows BEGIN UPDATE agent_workflows SET name='unexpected' WHERE id=NEW.id; END")
    with pytest.raises(migration.ReplacementError,match='unexpected_update_result'):
        migration.replace_news_workflow(path,proof.path,apply=True,backup_directory=backup)
    assert table(store,'agent_workflows')==before
