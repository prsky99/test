"""Three real, read-only workflow recipes bound to registered public endpoints."""
from copy import deepcopy
import json
import time

VERSION = 'live-workflow-hub-v1'
NEWS_URL = 'https://trending.openkrill.app/mcp'
NEWS_RESEARCH_URL = 'https://papers.openkrill.app/mcp'
DOCS_URL = 'https://capacitor-mcp.capawesome.io/mcp'
PADEL_URL = 'https://padeltrue.com/mcp'
NEWS_TOOL = 'trending'
NEWS_RESEARCH_TOOL = 'search_papers'
NEWS_TECH_ARGS = {
    'topic': 'developer-tools', 'window': '24h', 'limit': 3,
}
NEWS_RESEARCH_ARGS = {
    'query': 'large language model reasoning', 'open_access_only': True, 'limit': 3,
}


def agent(identity, name, url, tool, arguments, projection, index):
    return {'id':identity,'type':'agent','kind':'mcp','name':name,
            'position':{'x':60+280*index,'y':160},
            'data':{'resource_ref':{'kind':'mcp','url':url},'action':tool,
                    'input':arguments,'output_select':projection}}


def definitions():
    news_fields = {'title':'title','url':'url','source':'source_name','published_at':'published_at'}
    recipes=[
        ('daily-tech-research','Daily Tech News & AI Research Digest',
         'Retrieve technology updates from the last 24 hours and AI research papers with source links.','data_utility',[
            agent('news','Recent Technology News',NEWS_URL,NEWS_TOOL,NEWS_TECH_ARGS,
                  {'path':'structuredContent.posts','fields':news_fields,'limit':3,'max_text':3200},1),
            agent('research','AI Research Papers',NEWS_RESEARCH_URL,NEWS_RESEARCH_TOOL,NEWS_RESEARCH_ARGS,
                  {'path':'structuredContent.results','fields':{'title':'title','url':'url',
                   'year':'year','venue':'venue','doi':'doi'},'limit':3,'max_text':4000},2)]),
        ('capacitor-camera','Capacitor Camera Integration Brief',
         'Find official camera permission guidance and matching Capacitor plugins.','dev_tools',[
            agent('docs','Camera Permission Documentation',DOCS_URL,'search_docs',{'query':'camera permissions android ios','limit':2},
                  {'path':'structuredContent.results','fields':{'title':'title','url':'url','summary':'snippet'},'limit':2},1),
            agent('plugins','Camera Plugin Options',DOCS_URL,'list_plugins',{'query':'camera','limit':2},
                  {'path':'content.0.text','max_text':8000},2)]),
        ('padel-comparison','Padel Racket Discovery & Comparison',
         'Find two Nox AT10 models, then compare their exact catalogue identifiers. Ratings are calculated estimates.','sports_health',[
            agent('rackets','Find Two Racket Models',PADEL_URL,'search_rackets',{'query':'nox at10','limit':2},
                  {'path':'structuredContent.results','fields':{'slug':'slug','name':'name','year':'year','shape':'shape','ratings':'ratings','url':'page'},'limit':2},1),
            agent('comparison','Compare the Selected Models',PADEL_URL,'compare_rackets',
                  {'a':"{{$node['rackets'].output.structuredContent.results.0.slug}}",'b':"{{$node['rackets'].output.structuredContent.results.1.slug}}"},
                  {'path':'content.0.text','max_text':16000},2)])]
    result=[]
    for key,name,description,category,nodes in recipes:
        trigger={'id':'start','type':'trigger','kind':'trigger','name':'Manual Trigger','position':{'x':60,'y':160},'data':{}}
        result.append({'seed_key':VERSION+':'+key,'name':name,'description':description,'category':category,
                       'trigger_type':'manual','tags':'catalog-workflow,read-only,'+key,'is_template':1,'is_active':1,
                       'author':'Agent Concierge','rating_avg':0,'nodes':[trigger]+nodes,
                       'edges':[{'id':'start-first','source':'start','target':nodes[0]['id']},
                                {'id':'first-second','source':nodes[0]['id'],'target':nodes[1]['id']}]})
    return deepcopy(result)


def bind_resources(store, workflow):
    """Resolve an unbound endpoint reference without guessing a resource ID."""
    changed=False
    for node in workflow.get('nodes',[]):
        data=node.get('data',{});ref=data.get('resource_ref')
        if node.get('resource_id') or data.get('resource_id') or not isinstance(ref,dict):continue
        if not isinstance(ref.get('url'),str) or ref.get('kind')!='mcp':continue
        from .owned_data_agents.activation import resource_rows
        rows=resource_rows(store,ref['url'])
        if rows is None:
            rows=store.query('SELECT id FROM resources WHERE kind=? AND url=? ORDER BY active DESC,id DESC LIMIT 1',('mcp',ref['url']))
        if rows:
            node['resource_id']=data['resource_id']=rows[0]['id'];changed=True
    if changed:
        from .gateway.store import _graph_to_steps
        workflow['steps']=_graph_to_steps(workflow['nodes'],workflow.get('edges',[]))
    return workflow


def seed(store):
    """Only the three reviewed recipes are automatically seeded; saved edits stay intact."""
    with store.tx() as db:
        db.execute('CREATE TABLE IF NOT EXISTS workflow_seed_registry (seed_key TEXT PRIMARY KEY, workflow_id INTEGER NOT NULL UNIQUE)')
        # Retire old builtin entries once. Deliberate replacement of every current hub item
        # is handled by the install command, with a recoverable backup.
        marker='workflow_hub_recipes_v1'
        if not db.execute('SELECT 1 FROM meta WHERE key=?',(marker,)).fetchone():
            old_ids=[r[0] for r in db.execute("SELECT workflow_id FROM workflow_seed_registry WHERE seed_key NOT LIKE ?",(VERSION+':%',))]
            for identity in old_ids:
                db.execute('UPDATE agent_workflows SET is_template=0,is_active=0 WHERE id=? AND is_template=1',(identity,))
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(marker,json.dumps({'version':VERSION,'at':time.time()})))
        for definition in definitions():
            found=db.execute('SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?',(definition['seed_key'],)).fetchone()
            if found:continue
            workflow=bind_resources(store,definition)
            identity=store.create_workflow(workflow)
            db.execute('INSERT INTO workflow_seed_registry VALUES (?,?)',(definition['seed_key'],identity))
