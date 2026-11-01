"""Immutable release/readiness gates accept real deployment state shapes."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from scripts import qualify_workflow_products as cli


@pytest.fixture
def rollout(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'ROOT',tmp_path)
    monkeypatch.setattr(cli,'worker_matches',lambda *args:True)
    release=tmp_path/'release';release.mkdir();manifest={}
    for name in (*cli.FILES,*cli.EXECUTION_FILES):
        for root in (tmp_path,release):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('reviewed source '+name)
        manifest[name]=hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()
    (release/'release.json').write_text(json.dumps({'sha256':manifest}))
    state={'services':{role:({'active':'b','slots':{'b':'candidate'}} if role in ('frontend','admin') else {'release':'candidate'}) for role in ('frontend','admin','jobs','execution')}}
    probes=[]
    manager=SimpleNamespace(state=lambda:state,path=lambda name:release,probe=lambda *args:probes.append(args))
    control=SimpleNamespace(status=lambda role:{'available':True,'release':'candidate'})
    return manager,control,release,probes


def test_four_roles_accept_string_web_slots_and_worker_release_dicts(rollout):
    manager,control,_,probes=rollout
    result=cli.deployed(manager,control)
    assert set(result)=={'frontend','admin','jobs','execution'} and len(probes)==2


def test_source_drift_blocks_before_any_probe(rollout):
    manager,control,release,probes=rollout
    (release/cli.FILES[0]).write_text('changed without manifest update')
    with pytest.raises(ValueError,match='Deploy'):cli.deployed(manager,control)
    assert probes==[]


@pytest.mark.parametrize('status',[{'available':False,'release':'candidate'},{'available':True,'release':'old'}])
def test_unready_or_old_worker_cannot_qualify(rollout,status):
    manager,control,_,_=rollout;control.status=lambda role:status
    with pytest.raises(ValueError,match='not ready'):cli.deployed(manager,control)


@pytest.mark.parametrize('suffix,expected',[(' --settings private-path',True),('old --settings private-path',False)])
def test_running_worker_command_must_match_exact_release(tmp_path,monkeypatch,suffix,expected):
    manager=SimpleNamespace(pid=lambda *args:123,path=lambda release:tmp_path)
    command=str(tmp_path/'.venv/bin/python')+' -B '+str(tmp_path/'service_entry.py')+' --role execution --release candidate'+suffix
    monkeypatch.setattr(cli.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0,stdout=command))
    assert cli.worker_matches(manager,'execution','candidate') is expected


def test_current_heartbeat_without_release_uses_running_command_proof(rollout):
    manager,control,_,_=rollout;control.status=lambda role:{'available':True}
    assert len(cli.deployed(manager,control))==4


from tests.test_workflow_fallback import routing,tool  # noqa: E402,F401


def test_owner_approval_requires_authority_and_preserves_existing_contract(routing):
    rt,wf,ids,*_=routing
    assert cli.prepare_owner_approval(rt,ids[0],'search_docs','docs.search.v1',[tool()],lambda:True) is False
    with pytest.raises(PermissionError):cli.prepare_owner_approval(rt,ids[0],'search_docs','docs.search.v1',[tool()],lambda:False)


def test_explicit_owner_approval_is_retained_audited_and_cannot_replace_tool(routing):
    from agent_market.capability_registry import Registry
    rt,wf,ids,*_=routing;version=Registry(rt.store).current(rt.store.resource(ids[0]))
    with rt.store.tx() as db:db.execute('DELETE FROM capability_approvals WHERE version_id=?',(version['id'],))
    assert cli.prepare_owner_approval(rt,ids[0],'search_docs','docs.search.v1',[tool()],lambda:True) is True
    assert rt.store.query('SELECT tool FROM capability_approvals WHERE version_id=? AND contract_id=?',(version['id'],'docs.search.v1'))[0]['tool']=='search_docs'
    with pytest.raises(ValueError,match='conflicting'):cli.prepare_owner_approval(rt,ids[0],'other_tool','docs.search.v1',[tool()],lambda:True)
    assert rt.store.query("SELECT COUNT(*) FROM admin_audit_logs WHERE action='workflow_product_contract_approval'")[0][0]==1


def test_withdrawn_product_set_is_not_partially_or_silently_republished(routing):
    rt,*_=routing
    assert cli.requalify_withdrawn(rt,lambda:True) is None
    assert not rt.fallback.control()['enabled']


def test_withdrawn_products_requalify_same_ids_with_new_dispatch_proofs(routing):
    from tests.test_workflow_products import published
    from tests.test_workflow_runtime import save
    from copy import deepcopy
    rt,wf,ids,calls,modes,hooks,remote=routing;identities=[]
    for slug in ('research-search-api','research-comparison-board','source-bibliography-api'):
        clone=save(rt.store,deepcopy(wf['nodes']),name=slug,is_template=0)
        _,product,_=published((rt,clone,ids,calls,modes,hooks,remote),slug)
        rt.store.update_workflow(product['id'],{'is_template':0});identities.append(product['id'])
    before=rt.store.query('SELECT COUNT(*) FROM agent_workflows')[0][0]
    result=cli.requalify_withdrawn(rt,lambda:True)
    assert result['failed']==[] and set(result['published'])==set(identities)
    assert rt.store.query('SELECT COUNT(*) FROM agent_workflows')[0][0]==before
    assert all(rt.store.get_workflow(wid)['is_template'] for wid in identities)


def test_admin_scope_retains_auth_and_product_code_while_finance_installation_changes(tmp_path):
    path=tmp_path/'dashboard.py'
    code='''from anywhere import APIRouter

def dashboard_router(store):
    router=APIRouter()
    def authorize():return 'required'
    def guard():return authorize()
    def require_sadmin():return guard()
    auth=[guard]
    def log_op():return 'audit'
    def workflow_product_package():return 'checked product'
    def export_workflow_app():return 'legacy'
    def workflow_app_options():return 'options'
    finance='before'
'''
    path.write_text(code);before=cli.admin_product_scope(path)
    path.write_text(code.replace("finance='before'","finance='after'"));assert cli.admin_product_scope(path)==before
    path.write_text(code.replace("return 'required'","return 'bypassed'"));assert cli.admin_product_scope(path)!=before
    path.write_text(code.replace("return 'checked product'","return 'unchecked'"));assert cli.admin_product_scope(path)!=before
