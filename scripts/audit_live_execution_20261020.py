"""User-authorized bounded live tests of existing public informational examples.

Uses the operating service, never fabricates execution results and never saves
workflow bearer keys. No account, recipient, permission or server setting changes.
"""
import hashlib
import json
from pathlib import Path
import time
import httpx

OUT=Path(__file__).resolve().parents[1]/'reports/frontend-ux-ai-review-2026-10-20'


def main():
    result={'scope':'operating service, user-authorized public informational execution',
            'backend':'http://127.0.0.1:8400','live':True,'examples':[],'workflows':[],
            'account_mutations':False,'outbound_email_or_push':False}
    def save():
        (OUT/'live-execution-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    with httpx.Client(base_url='http://127.0.0.1:8400',timeout=35,
        headers={'Origin':'https://agentconcierge.biz','Accept':'application/json'}) as c:
        examples=json.loads((OUT/'live-presets.json').read_text())['live_examples']
        for example in examples:
            if not example.get('available'):continue
            request={'resource_id':example['resource_id'],'tool':example['tool'],
                     'arguments':example['args'],'message':'','timeout_seconds':8}
            row={'name':example['title'],'request':request,'started_at':time.time()}
            result['examples'].append(row);save();started=time.monotonic()
            try:
                r=c.post('/api/test/execute',json=request);row['http_status']=r.status_code
                data=r.json()
                row['response']={k:data.get(k) for k in ('ok','execution_succeeded','transport_ok','protocol_valid','simulated','task_status','status_code','latency_ms','output','error_message','error_code','tested_at','detail') if k in data}
                if r.status_code==429:row['retry_after']=r.headers.get('retry-after');save();break
            except Exception as exc:row['transport_exception']=type(exc).__name__
            row['seconds']=round(time.monotonic()-started,3);save()
            print(json.dumps({'example':row['name'],'http':row.get('http_status'),'seconds':row['seconds'],'status':row.get('response',{}).get('task_status'),'completed':row.get('response',{}).get('execution_succeeded')}),flush=True)
        templates=json.loads((OUT/'live-templates.json').read_text())['templates']
        for name in ('Daily Tech News & AI Research Digest','Country & Economic Indicator Brief','Package Metadata & Advisory Review'):
            template=next((t for t in templates if t['name']==name),None)
            if not template:continue
            if template.get('execution_availability',{}).get('available') is False:
                result['workflows'].append({'name':name,'not_executed':'published availability guard','availability':template['execution_availability']});save();continue
            row={'name':name,'started_at':time.time(),'request':{'template_id':template['id'],'definition_hash':template['definition_hash']}}
            result['workflows'].append(row);save();started=time.monotonic()
            try:
                r=c.post('/api/workflows/run',json=row['request']);row['submission_http']=r.status_code
                data=r.json()
                if r.status_code!=202:
                    row['submission_error']=data.get('error',data.get('detail','unavailable'));save();continue
                key=data['run_key'];run_id=data['run_id'];row['reference']=hashlib.sha256(run_id.encode()).hexdigest()[:12]
                for attempt in range(45):
                    time.sleep(1.5)
                    response=c.get('/api/workflows/runs/'+run_id,headers={'X-Workflow-Key':key})
                    row['last_read_http']=response.status_code
                    if response.status_code!=200:
                        row['read_error']='status_unavailable';break
                    status=response.json()
                    row['status']=status.get('status');row['execution_outcome']=status.get('execution_outcome')
                    row['polls']=attempt+1
                    row['result']={k:v for k,v in status.items() if k not in ('run_key','key','access_hash','snapshot','definition','actor','owner')}
                    save()
                    if row['status'] in ('succeeded','failed','cancelled'):break
                if row.get('status') not in ('succeeded','failed','cancelled'):
                    row['observation']='Observation ended; no automatic retry or completion assertion.'
            except Exception as exc:row['transport_exception']=type(exc).__name__
            row['seconds']=round(time.monotonic()-started,3);save()
            print(json.dumps({'workflow':name,'http':row.get('submission_http'),'seconds':row.get('seconds'),'status':row.get('status'),'outcome':row.get('execution_outcome')}),flush=True)
    save()


if __name__=='__main__':main()
