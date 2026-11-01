"""Explicit local-owner live qualification/publication, after all roles are deployed.

This command never deploys, restarts or starts an HTTP service. It requires the
existing private owner settings and matching immutable frontend/admin/jobs/execution
sources before any catalog, approval, workflow or routing mutation.
"""
import argparse
import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES=('agent_market/gateway/dashboard.py','agent_market/gateway/dashboard.html','agent_market/owned_data_agents/engine.py','agent_market/owned_data_agents/source_limits.py','agent_market/workflows.py','agent_market/workflow_products.py','agent_market/workflow_fallback.py',
       'agent_market/workflow_product_blueprints.py','agent_market/workflow_product_operator.py',
       'agent_market/workflow_product_package.py','agent_market/workflow_io_profiles.py',
       'agent_market/workflow_transforms.py','agent_market/concierge/execution_policy.py',
       'agent_market/capability_registry.py','agent_market/concierge/front.py','agent_market/application_store_sql.json',
       'new/en/assets/operating.js','new/en/index.html','new/en/workflows.html',
       'agent_market/concierge/workflow_product_assets/app.js','agent_market/concierge/workflow_product_assets/style.css')

EXECUTION_FILES=('agent_market/edge_gateway/native.py',)

def admin_product_scope(path):
    """Pin router/auth bootstrap and product routes, not unrelated workbenches."""
    tree=ast.parse(path.read_bytes())
    routers=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='dashboard_router']
    if len(routers)!=1:raise ValueError('A single administrator router is required.')
    router=routers[0]
    prefix_end=next(i for i,n in enumerate(router.body) if isinstance(n,ast.FunctionDef) and n.name=='log_op')
    required={'authorize','guard','require_sadmin','workflow_product_package','export_workflow_app','workflow_app_options'}
    functions={n.name:n for n in router.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in required}
    if set(functions)!=required:raise ValueError('The reviewed administrator product scope is required.')
    # All module setup and router initialization through auth/auditing are pinned.
    # Later unrelated finance/research workbench installation is not this product.
    parts=[ast.dump(n,include_attributes=False) for n in tree.body if n is not router]
    parts.extend(ast.dump(n,include_attributes=False) for n in router.body[:prefix_end+1])
    parts.extend(ast.dump(functions[name],include_attributes=False) for name in sorted(required))
    parts.append(ast.dump(router.args,include_attributes=False))
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def source_matches(name,root,frozen,expected):
    staged=frozen/name;current=root/name
    if expected!=hashlib.sha256(staged.read_bytes()).hexdigest():return False
    if expected==hashlib.sha256(current.read_bytes()).hexdigest():return True
    if name!='agent_market/gateway/dashboard.py':return False
    try:return admin_product_scope(current)==admin_product_scope(staged)
    except (ValueError,SyntaxError,StopIteration):return False


def worker_matches(manager,role,release):
    pid=manager.pid(role,'main')
    if type(pid) is not int or pid<=0:return False
    frozen=manager.path(release)
    result=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=5)
    expected=str(frozen/'.venv/bin/python')+' -B '+str(frozen/'service_entry.py')+' --role '+role+' --release '+release+' '
    return result.returncode==0 and result.stdout.strip().startswith(expected)


def deployed(manager,control):
    state=manager.state();checked={}
    for role in ('frontend','admin','jobs','execution'):
        service=state['services'][role]
        selected=service['slots'][service['active']] if role not in ('jobs','execution') else service
        release=selected['release'] if isinstance(selected,dict) else selected;root=manager.path(release)
        manifest=json.loads((root/'release.json').read_text())['sha256']
        checked_files=FILES+EXECUTION_FILES if role=='execution' else FILES
        if any(not source_matches(name,ROOT,root,manifest.get(name)) for name in checked_files):
            raise ValueError('Deploy the current product sources to all four roles before live qualification.')
        if role in ('jobs','execution'):
            status=control.status(role)
            if not status.get('available') or status.get('release',release)!=release or not worker_matches(manager,role,release):raise ValueError('The current execution worker is not ready.')
        else:manager.probe(role,service['active'],release)
        checked[role]=release
    return checked


def prepare_owner_approval(runtime,resource_id,tool,contract_id,tools,guard):
    """Explicit owner approval within the native writer transaction.

    Registry's optional SQLite BEGIN guard cannot be nested in PostgreSQL's
    already-open transaction. Authenticate this trusted local owner inside the
    native writer scope, use the standard validated internal approval API, and
    audit it. This helper is never exposed as a public request or staff bypass.
    """
    from agent_market.capability_registry import Registry
    from agent_market.collector import usage
    from agent_market.gateway.admin_auth import record_audit
    registry=Registry(runtime.store)
    if guard() is not True:raise PermissionError('Current local owner authority is required.')
    runtime.store.record_usage(resource_id,usage.compact_tools(tools),usage.tools_hash(usage.compact_tools(tools)),{},None,None,full_tools=tools)
    with runtime.store.tx() as db:
        if guard() is not True:raise PermissionError('Current local owner authority is required.')
        resource=runtime.store.resource(resource_id);version=registry.current(resource)
        rows=runtime.store.query('SELECT tool FROM capability_approvals WHERE version_id=? AND contract_id=?',(version['id'],contract_id))
        if rows and rows[0]['tool']!=tool:raise ValueError('A conflicting current approval requires explicit review.')
        if rows:return False
        approved=registry.approve(resource,contract_id,tool)
        if approved['id']!=version['id']:raise ValueError('The reviewed native tool version changed.')
        record_audit(db,'local-owner-command','owner','workflow_product_contract_approval','Explicit owner research contract approval',
            target=str(resource_id),details={'contract_id':contract_id,'tool':tool,'version_id':approved['id']})
    return True


def requalify_withdrawn(runtime,guard):
    """Retest the same withdrawn product IDs after an execution delivery repair."""
    import time
    from agent_market.workflow_fallback import NOTICE
    from agent_market.workflow_product_operator import terminal
    slugs={'research-search-api','research-comparison-board','source-bibliography-api'};found={}
    for row in runtime.store.query('SELECT workflow_id FROM workflow_product_templates ORDER BY workflow_id DESC LIMIT 100'):
        try:
            product=runtime.products.get(row['workflow_id']);workflow=runtime.store.get_workflow(row['workflow_id'])
            if product['spec']['slug'] in slugs and not workflow.get('is_template') and product['stage'] in ('verified','published'):
                found.setdefault(product['spec']['slug'],(workflow,product))
        except (ValueError,KeyError,TypeError):continue
    if set(found)!=slugs:return None
    report={'scope':'Same operating product IDs; actual configured delivery; private controlled preflight outages.',
            'published':[],'failed':[],'tests':[],'requalified_withdrawn':True}
    for slug in sorted(found):
        workflow,product=found[slug];wid=workflow['id'];entry={'slug':slug,'workflow_id':wid};report['tests'].append(entry)
        try:
            if guard() is not True:raise PermissionError('Current local owner authority is required.')
            old,_=runtime.fallback.policy(wid)
            if not old or old['fingerprint']!=product['binding']:raise ValueError('Review the changed routing policy separately.')
            pairs=[{'node_id':pair['node_id'],'resource_id':pair['alternate']['resource_id'],'contract_id':pair['contract_id'],
                    **({'alternate_io_profile':pair['alternate']['io_profile']} if pair['alternate'].get('io_profile') else {})} for pair in old['pairs']]
            expiry=min(product['expires'],time.time()+23*3600)
            def refresh():
                checked=set()
                for pair in old['pairs']:
                    for side in ('primary','alternate'):
                        pin=pair[side];key=(pin['resource_id'],pin['approval']['tool'])
                        if key in checked:continue
                        arguments={'query':'retrieval augmented generation','language':'en','limit':2}
                        if pin.get('io_profile'):
                            from agent_market.workflow_transforms import apply
                            arguments=apply(runtime.io_profiles.get(pin['io_profile'])['input_transform'],arguments)
                        value=runtime.proxy.execute(key[0],key[1],arguments,public=True)
                        if value.get('ok') is not True:raise ValueError('Current native provider verification failed.')
                        checked.add(key)
            def configure(mode):
                return runtime.fallback.configure(wid,{'revision':runtime.fallback.inspect(wid)['revision'],'mode':mode,'pairs':pairs,
                    'authority':True,'notice':NOTICE,'canary_percent':100 if mode=='active' else 10,'max_runs':1000 if mode=='active' else 20,'expires':expiry},0)
            refresh();configure('shadow');runtime.products.candidate(wid,product['spec'],0,guard)
            principal=runtime.principal('admin','local-owner-command',wid,role='superadmin')
            normal=terminal(runtime,runtime.submit(workflow,actor='local-owner-command',principal=principal,product_input={}))
            configure('canary')
            if not runtime.fallback.control()['enabled']:runtime.fallback.set_control({'enabled':True,'revision':runtime.fallback.control()['revision']},0)
            drills=[]
            for resource_id in sorted({pair['primary']['resource_id'] for pair in old['pairs']}):
                refresh()
                value=terminal(runtime,runtime.submit(workflow,actor='local-owner-command',principal=principal,allow_fallback=True,
                    fallback_notice=NOTICE,product_input={},product_drill=resource_id));drills.append(value['run_id'])
            runtime.products.accept(wid,normal['run_id'],drills,0,guard);configure('active');runtime.products.publish(wid,0,guard)
            entry.update(passed=True,normal_run=normal['run_id'],controlled_outage_runs=drills,expires=expiry);report['published'].append(wid)
        except Exception as exc:
            entry.update(passed=False,error_class=type(exc).__name__,reason=str(exc)[:200]);report['failed'].append(wid)
            runtime.store.update_workflow(wid,{'is_template':0})
    if not report['published'] and runtime.fallback.control()['enabled']:
        runtime.fallback.set_control({'enabled':False,'revision':runtime.fallback.control()['revision']},0)
    report['fallback_enabled']=runtime.fallback.control()['enabled']
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--authorize-public-provider-tests',action='store_true')
    parser.add_argument('--publish-passed',action='store_true');args=parser.parse_args()
    if args.apply and not(args.authorize_public_provider_tests and args.publish_passed):parser.error('Apply requires explicit public-provider test and passed-only publication authorization.')
    from scripts.service_deploy import Deployment
    from agent_market.application_runtime import _private_bytes,open_runtime_storage
    manager=Deployment(ROOT)
    _private_bytes(str(manager.settings),65536)
    with manager.lock():
        control=manager.control()
        try:
            try:releases=deployed(manager,control)
            except ValueError:
                print(json.dumps({'ready':False,'error':'CURRENT_PRODUCT_RELEASE_REQUIRED','mutations':0}));return 1
        finally:control.close()
        if not args.apply:print(json.dumps({'ready':True,'releases':releases,'mutations':0}));return 0
        from scripts.agentcon_config import read_edge_gateway_settings
        edge_settings=read_edge_gateway_settings(str(ROOT/'gateway-data/edge-gateway.env'))
        for name in ('AGENT_EDGE_GATEWAY_CONFIG','AGENT_EDGE_CLOUDFLARE_TOKEN_FILE'):
            if edge_settings.get(name) and not Path(edge_settings[name]).is_absolute():edge_settings[name]=str(ROOT/edge_settings[name])
        os.environ.update(edge_settings)
        from agent_market.workflows import WorkflowRuntime
        from agent_market.concierge.proxy import McpProxy
        from agent_market.broker.discovery import public_client
        from agent_market.collector.capabilities import CapabilityProber
        from agent_market.owned_data_agents.dispatch import OwnedDispatch
        from agent_market.owned_data_agents.engine import DataAgents
        from agent_market.owned_data_agents.catalog import tool_spec
        from agent_market.workflow_product_operator import build
        from agent_market.gateway.admin_auth import record_audit
        storage=open_runtime_storage(':memory:');store=storage.store;proxy=McpProxy(store);runtime=WorkflowRuntime(store,proxy)
        try:
            a,b=133019,34807
            from agent_market.owned_data_agents.service import PREFIX
            owned=store.resource(a)
            if not owned or owned['key']!='agentconcierge-owned:research-papers' or owned['source']!='agentconcierge-owned' or owned['url']!='https://agentconcierge.biz'+PREFIX+'/research-papers/mcp':
                raise ValueError('The expected local research binding changed.')
            if store.resource(b)['url']!='https://papers.openkrill.app/mcp':raise ValueError('The reviewed independent provider changed.')
            with public_client(timeout=12) as client:tools=CapabilityProber(None).probe(store.resource(b)['url'],client)['tools']
            proxy._owned_data_dispatch=OwnedDispatch(store,DataAgents(),{'research-papers':a},'https://agentconcierge.biz')
            owner_guard=lambda:os.getuid()==manager.settings.stat().st_uid
            native_tools={a:[tool_spec('research-papers')],b:tools}
            if getattr(store,'backend',None)=='postgresql':
                prepare_owner_approval(runtime,a,'search_research_papers','docs.search.v1',native_tools[a],owner_guard)
                prepare_owner_approval(runtime,b,'search_arxiv','docs.search.v1',native_tools[b],owner_guard)
            report=requalify_withdrawn(runtime,owner_guard)
            if report is None:report=build(runtime,a,b,native_tools,publish=True,guard=owner_guard)
            report['releases']=releases
            with store.tx() as db:record_audit(db,'local-owner-command','owner','workflow_product_qualification','Passed-only workflow product publication',status='SUCCESS' if not report['failed'] else 'PARTIAL',details=report)
            directory=ROOT/'reports/workflow-product-templates-2026-10-24'
            (directory/'operating-qualification.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report));return 0 if len(report['published'])==3 and not report['failed'] else 1
        finally:
            for future in runtime.futures.values():future.result(timeout=70)
            storage.close()


if __name__=='__main__':raise SystemExit(main())
