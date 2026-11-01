"""Read real public sources through an activated, disposable frontend composition.

No existing DB or server is accepted. Actual external source HTTPS is distinct
from the isolated ASGI frontend and the trusted in-process owned handler.
"""
import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.gateway.store import Store
from agent_market.owned_data_agents.catalog import SPECS
from agent_market.owned_data_agents.verification import wait


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--live',required=True,action='store_true')
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    root=Path(args.output)
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    store=Store(str(root/'isolated.sqlite3'))
    front=Front(store,public_url='https://agentconcierge.biz')
    app=create_front_app(front,owned_data_agents_enabled=True,manage_book_lifecycle=False)
    def forbid_self_http(*args, **kwargs):
        raise AssertionError('Owned agents must execute locally, without public-origin MCP HTTP.')
    front.proxy._client = forbid_self_http
    report={'scope':'Activated isolated frontend, real public source HTTPS; no operating server restart',
        'operating_database_actions':0,'project_server_actions':0,
        'agent_execution':'Local in-process handlers; public-origin MCP HTTP is forbidden during this acceptance',
        'testbench':[],'agents':[],'workflows':[]}
    try:
        with TestClient(app,base_url='https://agentconcierge.biz') as client:
            examples=client.get('/api/test/presets').json()['live_examples']
            for example in examples:
                response=client.post('/api/test/execute',json={'resource_id':example['resource_id'],
                    'tool':example['tool'],'arguments':example['args']})
                result=response.json()
                report['testbench'].append({'id':example['id'],'http_status':response.status_code,
                    'ok':result.get('execution_succeeded') is True,'output':result.get('output')})
            for identity,spec in SPECS.items():
                rid=next(rid for rid,pair in front.proxy._owned_data_dispatch.bindings.items() if pair[0]==identity)
                result=front.proxy.execute(rid,spec['tool'],spec['example'],public=True)
                report['agents'].append({'id':identity,'ok':result.get('ok') is True,
                    'output':result.get('result',{}).get('structuredContent'),'error_code':result.get('error_code')})
            workflows,_=store.list_workflows(is_template=1,active_only=True)
            for workflow in workflows:
                result=wait(front.workflows,front.workflows.submit(workflow,public=True,source='verification'))
                report['workflows'].append({'name':workflow['name'],'status':result['status'],'nodes':result['node_results']})
            report['completed']=(len(report['testbench'])==5 and len(report['agents'])==7 and len(report['workflows'])==3
                and all(r['ok'] for r in report['testbench']+report['agents'])
                and all(r['status']=='succeeded' for r in report['workflows']))
    finally:
        (root/'verification.json').write_text(json.dumps(report,indent=2,ensure_ascii=True))
        front.book.close()
        clear_front_caches()
        store._db.close()
    print(json.dumps({'completed':report.get('completed',False),'testbench':len(report['testbench']),
        'agents':len(report['agents']),'workflows':len(report['workflows'])}))
    return 0 if report.get('completed') else 1


if __name__=='__main__':
    raise SystemExit(main())
