"""Owner-invoked product qualification; no HTTP server or synthetic business data."""
import time

from .capability_registry import Registry
from .collector import usage
from .workflow_fallback import NOTICE
from .workflow_io_profiles import NOTICE as IO_NOTICE
from .workflow_product_blueprints import definitions,recipes

QUERY='retrieval augmented generation'


def terminal(runtime,job):
    deadline=time.monotonic()+70
    while time.monotonic()<deadline:
        value=runtime.get(job['run_id'])
        if value['status'] in ('succeeded','failed','cancelled'):
            future=runtime.futures.get(job['run_id'])
            if future:future.result(timeout=3)
            if value['status']!='succeeded':raise ValueError('Product validation run did not succeed: '+value['status'])
            return value
        time.sleep(.1)
    raise ValueError('Product validation exceeded the bounded wait; it was not automatically repeated.')


def build(runtime,primary_id,alternate_id,native_tools,*,publish=False,guard=lambda:False):
    """Actual provider tests plus signed per-run controlled preflight outages.

    The caller supplies a trusted highest-administrator or private local-owner
    guard. This is not an HTTP entry point. Existing conflicting tool approvals
    are never replaced, and existing templates are never edited.
    """
    if guard() is not True:raise PermissionError('Explicit owner authorization is required.')
    store=runtime.store;registry=Registry(store);profiles={};specs={};actor=0
    report={'scope':'Actual providers with controlled, private preflight outages.','published':[],'failed':[],'tests':[]}
    initial_enabled=runtime.fallback.control()['enabled']
    existing={}
    for row in store.query('SELECT workflow_id FROM workflow_product_templates ORDER BY workflow_id DESC LIMIT 100'):
        try:
            product=runtime.products.get(row['workflow_id'])
            wf=store.get_workflow(row['workflow_id'])
            if product['stage']=='published' and runtime.products.projection(wf):
                existing.setdefault(product['spec']['slug'],row['workflow_id'])
        except (ValueError,KeyError,TypeError):continue
    slugs={'research-search-api','research-comparison-board','source-bibliography-api'}
    if publish and slugs<=set(existing):
        return {**report,'published':[existing[slug] for slug in sorted(slugs)],'already_published':True,'fallback_enabled':initial_enabled}
    for rid in (primary_id,alternate_id):
        resource=store.resource(rid)
        if not resource or resource['kind']!='mcp' or resource.get('price_usdc') or resource.get('auth_observed')==1:
            raise ValueError('Only reviewed public read-only research sources may be provisioned.')
        tools=native_tools[rid];name='search_research_papers' if rid==primary_id else 'search_arxiv'
        spec=next(t for t in tools if t.get('name')==name);specs[rid]=spec
        # A full native survey is an observation, not a fabricated tool success.
        store.record_usage(rid,usage.compact_tools(tools),usage.tools_hash(usage.compact_tools(tools)),{},None,None,full_tools=tools)
        current=registry.current(store.resource(rid))
        approvals=store.query('SELECT tool FROM capability_approvals WHERE version_id=? AND contract_id=?',(current['id'],'docs.search.v1'))
        if approvals and approvals[0]['tool']!=name:raise ValueError('Existing current-version contract approval conflicts; review it explicitly rather than overwriting it.')
        if not approvals:registry.approve(store.resource(rid),'docs.search.v1',name,guard=guard)
        profile=recipes(rid,name,'docs.search.v1',spec)
        checked=runtime.io_profiles.create({'profile':profile,'cases':[{'query':q,'language':'en','limit':2} for q in (QUERY,'quantum error correction')],
            'authority':True,'notice':IO_NOTICE},actor,guard)
        profiles[rid]=checked['id']
    created=definitions(primary_id,alternate_id,profiles[primary_id],profiles[alternate_id])
    def refresh():
        for rid in (primary_id,alternate_id):
            value=runtime.proxy.execute(rid,specs[rid]['name'],{'query':QUERY,'limit':2},public=True)
            if value.get('ok') is not True:raise ValueError('Fresh actual provider verification failed.')
    def configure(wid,pairs,mode,expiry):
        return runtime.fallback.configure(wid,{'revision':runtime.fallback.inspect(wid)['revision'],'mode':mode,
            'pairs':pairs,'authority':True,'notice':NOTICE,'canary_percent':100 if mode=='active' else 10,
            'max_runs':1000 if mode=='active' else 20,'expires':expiry},actor)
    for product in created:
        if publish and product['slug'] in existing:
            report['published'].append(existing[product['slug']]);continue
        wid=None;entry={'slug':product['slug']};report['tests'].append(entry)
        try:
            if guard() is not True:raise PermissionError('Owner authority was withdrawn.')
            refresh();wid=store.create_workflow(product['workflow']);wf=store.get_workflow(wid);entry['workflow_id']=wid
            expiry=time.time()+23*3600
            configure(wid,product['pairs'],'shadow',expiry)
            spec={k:product[k] for k in ('slug','use_case','inputs')}
            runtime.products.candidate(wid,spec,actor,guard);expiry=runtime.products.get(wid)['expires']
            principal=runtime.principal('admin','local-owner-command',wid,role='superadmin')
            normal=terminal(runtime,runtime.submit(wf,actor='local-owner-command',principal=principal,product_input={}))
            configure(wid,product['pairs'],'canary',expiry)
            if not runtime.fallback.control()['enabled']:
                runtime.fallback.set_control({'enabled':True,'revision':runtime.fallback.control()['revision']},actor)
            drills=[]
            for rid in sorted({p['primary']['resource_id'] for p in runtime.fallback.policy(wid)[0]['pairs']}):
                refresh()
                outcome=terminal(runtime,runtime.submit(wf,actor='local-owner-command',principal=principal,allow_fallback=True,fallback_notice=NOTICE,product_input={},product_drill=rid))
                drills.append(outcome['run_id'])
            runtime.products.accept(wid,normal['run_id'],drills,actor,guard)
            configure(wid,product['pairs'],'active',expiry)
            if publish:runtime.products.publish(wid,actor,guard);report['published'].append(wid)
            entry.update(passed=True,normal_run=normal['run_id'],controlled_outage_runs=drills,expires=expiry)
        except Exception as exc:
            entry.update(passed=False,error_class=type(exc).__name__,reason=str(exc)[:240]);report['failed'].append(wid)
            if wid is not None:
                store.update_workflow(wid,{'is_template':0})
                try:configure(wid,product['pairs'],'disabled',time.time()+600)
                except ValueError:pass
    if not report['published'] and not initial_enabled:
        runtime.fallback.set_control({'enabled':False,'revision':runtime.fallback.control()['revision']},actor)
    report['fallback_enabled']=runtime.fallback.control()['enabled']
    return report
