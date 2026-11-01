"""Resumable low-rate public Gateway campaign; read-only Provider inputs only."""
import argparse
import fcntl
from collections import Counter
import hashlib
import heapq
import json
import os
from pathlib import Path
import signal
import time
from urllib.parse import urlsplit

import httpx

from scripts.audit_edge_provider_inventory import safe_probe_input, PROMPT

STOP = False

def stop(*_):
    global STOP
    STOP = True


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2)+'\n'); os.chmod(temp, 0o600); temp.replace(path)


def append(path, value):
    fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
    with os.fdopen(fd,'a') as f: f.write(json.dumps(value,separators=(',',':'))+'\n'); f.flush()


def connection(root):
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import open_runtime_storage
    from agent_market.edge_gateway.config import load
    from agent_market.edge_gateway.service import Service
    from agent_market.concierge.notify import Courier
    from types import SimpleNamespace
    values=read_settings(root/'gateway-data/agentcon.env')
    for key in ('APPLICATION_POSTGRES_DSN_FILE','APPLICATION_WORKFLOW_KEY_FILE'):
        if key in values: values[key]=str((root/values[key]).resolve())
    storage=open_runtime_storage(str(root/'gateway-data/gateway.db'),values=values)
    os.environ['AGENT_EDGE_GATEWAY_CONFIG']=str(root/'gateway-data/edge-gateway.json')
    front=SimpleNamespace(store=storage.store,courier=Courier())
    return storage,front,Service(front,load())


def receipt(store,key):
    digest=hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest()
    with store.tx(readonly=True):
        found=store._execute('SELECT id,resource_id,backend,state,error_code,attempt FROM edge_gateway_runs WHERE idempotency=%s',(digest,)).fetchall()
        if not found:return None
        row=dict(found[0]);events=store._execute('SELECT outcome,output_bytes FROM edge_gateway_events WHERE run_id=%s',(row['id'],)).fetchall()
    return {**row,'events':[dict(e) for e in events]}


def wire(item):
    kind=item['protocol'];value=item['input']
    if kind=='mcp':
        if not safe_probe_input(value['arguments']):raise ValueError('Unsafe recorded recipe')
        return 'POST', {'jsonrpc':'2.0','id':'validation-'+str(item['id']),'method':'tools/call','params':{'name':value['tool'],'arguments':value['arguments']}}
    if kind=='x402':return 'GET',None
    if value.get('message') != PROMPT: raise ValueError('Unreviewed A2A prompt')
    method='SendMessage' if item.get('spec_version')=='1.0' else 'message/send'
    message={'role':'ROLE_USER' if method=='SendMessage' else 'user','messageId':'provider-validation','parts':[{'text':value['message']} if method=='SendMessage' else {'kind':'text','text':value['message']}]}
    return 'POST',{'jsonrpc':'2.0','id':'validation-'+str(item['id']),'method':method,'params':{'message':message,'configuration':{'returnImmediately':False} if method=='SendMessage' else {'blocking':True}}}


def metric(client,root,output,start):
    from agent_market.edge_gateway.monitor import read_api_token
    day=time.strftime('%Y-%m-%dT00:00:00Z',time.gmtime())
    iso=lambda t:time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(t))
    query='''query($account:string,$start:string,$end:string,$day:string){viewer{accounts(filter:{accountTag:$account}){
      usage:workersInvocationsAdaptive(limit:1,filter:{datetime_geq:$day,datetime_leq:$end}){sum{requests}}
      worker:workersInvocationsAdaptive(limit:1000,filter:{scriptName:"agentconcierge-edge-gateway",datetime_geq:$start,datetime_leq:$end}){dimensions{datetime status}sum{requests errors}quantiles{cpuTimeP50 cpuTimeP99}}
    }}}'''
    r=client.post('https://api.cloudflare.com/client/v4/graphql',headers={'Authorization':'Bearer '+read_api_token(root/'gateway-data/cloudflare-analytics.token')},json={'query':query,'variables':{'account':'224f671b6c06e49b2aac6a235410c88d','start':iso(start),'end':iso(time.time()),'day':day}})
    r.raise_for_status();obj=r.json()
    if obj.get('errors'):raise ValueError('Analytics unavailable')
    account=obj['data']['viewer']['accounts'][0];rows=account['worker'];usage=account.get('usage') or []
    record={'at':time.time(),'start':iso(start),'requests':sum(x['sum']['requests'] for x in rows),'runtime_errors':sum(x['sum']['errors'] for x in rows),'cpu_peak_p99_ms':max((x['quantiles']['cpuTimeP99']/1000 for x in rows),default=None),'rows':rows,'account_requests':usage[0]['sum']['requests'] if usage else 0,'possibly_truncated':len(rows)>=1000}
    append(output/'cloudflare-observations.jsonl',record)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True);parser.add_argument('--interval',type=float,default=10)
    parser.add_argument('--host-interval',type=float,default=30);parser.add_argument('--max-probes',type=int)
    parser.add_argument('--max-hours',type=float,default=24)
    parser.add_argument('--observe-only',action='store_true')
    parser.add_argument('--observe-hours',type=float,default=24);parser.add_argument('--poll-seconds',type=float,default=300)
    args=parser.parse_args()
    if args.interval<10 or args.host_interval<30 or args.poll_seconds<60 or not 0<args.max_hours<=168:raise ValueError('Validation rate below safe minimum')
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    root=Path(__file__).resolve().parents[1];output=Path(args.directory).resolve()
    lock_fd=os.open(output/'campaign.lock',os.O_WRONLY|os.O_CREAT,0o600)
    fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    recipe_bytes=(output/'recipes.jsonl').read_bytes();recipe_hash=hashlib.sha256(recipe_bytes).hexdigest()
    recipes=[json.loads(s) for s in recipe_bytes.decode().splitlines() if s]
    summary_path=output/'campaign-summary.json';events=output/'runtime-results.jsonl';intents=output/'runtime-intents.jsonl'
    started=time.time();base=json.loads(summary_path.read_text()) if summary_path.exists() else {}
    if base.get('recipes_sha256',recipe_hash)!=recipe_hash: raise ValueError('Campaign snapshot changed')
    started=base.get('started_at',started);done=set();counts=Counter();host_last={}
    if events.exists():
        for line in events.read_text().splitlines():
            row=json.loads(line);done.add(row['resource_id']);counts[row['classification']]+=1;host_last[row['host']]=row['finished_at']
    if intents.exists():
        for line in intents.read_text().splitlines():
            row=json.loads(line)
            if row['resource_id'] not in done:
                # No blind retry: an unrecorded response may have executed on Origin.
                append(events,{**row,'finished_at':time.time(),'classification':'interrupted_indeterminate'})
                done.add(row['resource_id']);counts['interrupted_indeterminate']+=1
    recipes.sort(key=lambda row: hashlib.sha256(str(row['id']).encode()).digest())
    priority={86984:0,87654:1,158466:2,158419:3,10144:4,145303:5}
    recipes.sort(key=lambda x:priority.get(x['id'],100))
    queue=[(host_last.get(x['host'],0)+args.host_interval,i,x) for i,x in enumerate(recipes) if x['id'] not in done];heapq.heapify(queue)
    storage,front,service=connection(root)
    status={'status':'running','recipes_sha256':recipe_hash,'started_at':started,'pid':os.getpid(),'total_recipes':len(recipes),'interval_seconds':args.interval,'host_interval_seconds':args.host_interval,'hard_deadline':started+args.max_hours*3600,'observation_target_hours':args.observe_hours,'automatic_retries':False,'payment_credentials_sent':False}
    metric_at=0;last_metric=None;probe_at=0;attempts=0;pause_reason=None;pending_receipts={}
    def save():
        write_json(summary_path,{**status,'last_updated':time.time(),'completed_or_classified':sum(counts.values()),'remaining':len(queue),'classification_counts':dict(counts),'last_cloudflare_observation':last_metric,'pause_reason':pause_reason,'active_case':status.get('active_case')})
    try:
        with httpx.Client(timeout=20,follow_redirects=False,trust_env=False,headers={'Accept-Encoding':'identity'}) as client:
            while not STOP and (queue or time.time()-started<args.observe_hours*3600):
                now=time.time()
                if now>=started+args.max_hours*3600:
                    status['status']='paused_deadline';pause_reason='bounded_validation_deadline';save();break
                if now>=metric_at:
                    try:last_metric=metric(client,root,output,max(started,now-600));pause_reason=None
                    except Exception:pause_reason='analytics_unconfirmed'
                    metric_at=now+args.poll_seconds;save()
                policy=service.summary()
                if last_metric is None or now-last_metric['at']>600 or pause_reason=='analytics_unconfirmed':
                    pause_reason='analytics_unconfirmed';save();time.sleep(min(5,args.poll_seconds));continue
                if last_metric['runtime_errors']>0:
                    pause_reason='worker_runtime_error';status['status']='attention_required';save();break
                if policy['preferred_backend']!='worker' or last_metric['account_requests']+policy.get('local_reservations',0)>=min(service.config.soft_limit,80000):
                    pause_reason=policy.get('reason') or 'validation_quota_reserve';save();time.sleep(10);continue
                control_path=output/'campaign-control.json'
                controls=json.loads(control_path.read_text()) if control_path.exists() else {}
                if args.observe_only or not controls.get('allow_probes',True):
                    pause_reason=controls.get('reason') or 'observation_only';save();time.sleep(10);continue
                if last_metric.get('cpu_peak_p99_ms') is not None and last_metric['cpu_peak_p99_ms']>controls.get('cpu_guard_ms',10):
                    pause_reason='cpu_budget_exceeded';save();time.sleep(10);continue
                if not queue:
                    pause_reason='observation_only';save();time.sleep(10);continue
                if args.max_probes is not None and attempts>=args.max_probes:
                    status['status']='paused_tranche';pause_reason='initial_tranche_finished';save();break
                ready,index,item=heapq.heappop(queue)
                permitted=max(ready,host_last.get(item['host'],0)+args.host_interval,probe_at+args.interval)
                if permitted>now:
                    heapq.heappush(queue,(permitted,index,item));time.sleep(min(5,permitted-now));continue
                method,body=wire(item)
                key='pv-'+str(item['id'])+'-'+hashlib.sha256(json.dumps([item['connection_hash'],item['input']],sort_keys=True).encode()).hexdigest()[:20]
                record={'resource_id':item['id'],'protocol':item['protocol'],'host':item['host'],'started_at':time.time(),'idempotency_key':key}
                status['active_case']=item['id'];save();append(intents,record);attempts+=1;probe_at=time.time()
                row={**record};raw=bytearray();parsed={}
                try:
                    with client.stream(method,'https://agentconcierge.biz/api/gateway/'+item['protocol']+'/'+str(item['id']),json=body,headers={'Idempotency-Key':key,'Origin':'https://agentconcierge.biz','Content-Type':'application/json'}) as response:
                        row['http_status']=response.status_code
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>65536:raise ValueError('Response exceeds validation bound')
                    parsed=json.loads(raw);row.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                except Exception as error:
                    row['transport_error_type']=type(error).__name__
                row['response_finished_at']=time.time()
                evidence=None
                for delay in (0,.5,1,2,4,8,10):
                    if delay:time.sleep(delay)
                    evidence=receipt(storage.store,key)
                    if not evidence or evidence['state'] in ('succeeded','failed','outcome_unknown'):break
                row['receipt']=evidence
                row['provider_host_present']=item['host'].encode() in raw if item['host'] else None
                valid_challenge=item['protocol']=='x402' and row.get('http_status')==402 and isinstance(parsed,dict) and type(parsed.get('x402Version')) is int and parsed.get('x402Version') in (1,2) and isinstance(parsed.get('accepts'),list) and bool(parsed['accepts'])
                rpc_success=isinstance(parsed,dict) and parsed.get('jsonrpc')=='2.0' and isinstance(parsed.get('result'),dict) and 'error' not in parsed
                if evidence:
                    row['classification']='edge_execution_pass' if evidence['backend']=='worker' and evidence['state']=='succeeded' and rpc_success else 'valid_unpaid_challenge' if evidence['backend']=='worker' and valid_challenge else 'origin_execution_pass' if evidence['backend']=='origin' and evidence['state']=='succeeded' and rpc_success else 'execution_'+evidence['state']
                    if evidence['state']=='succeeded' and not rpc_success:row['classification']='receipt_output_mismatch'
                    if (evidence['state']=='succeeded' or valid_challenge) and evidence['events'] and evidence['events'][0].get('output_bytes')!=len(raw):
                        row['receipt_bytes_mismatch']=item['protocol']!='a2a'
                        row['receipt_stream_scope_difference']=item['protocol']=='a2a'
                else:row['classification']='success_backend_unconfirmed' if rpc_success else 'challenge_backend_unconfirmed' if valid_challenge else 'unverified_or_policy_blocked'
                row['rpc_success']=rpc_success;row['valid_unpaid_challenge']=valid_challenge
                row['finished_at']=time.time();row['latency_ms']=(row['response_finished_at']-row['started_at'])*1000
                append(events,row);counts[row['classification']]+=1;done.add(item['id']);host_last[item['host']]=time.time();status['active_case']=None;save()
                if evidence and evidence['state']=='dispatch_reserved':
                    pause_reason='receipt_unsettled';write_json(output/'campaign-control.json',{'allow_probes':False,'reason':'receipt_unsettled','cpu_guard_ms':10,'resource_id':item['id']});save()
                if row['classification']=='receipt_output_mismatch' or row.get('receipt_bytes_mismatch'):
                    status['status']='attention_required';pause_reason='receipt_mismatch';save();break
                if row.get('http_status')==429:
                    pause_reason='gateway_rate_limit';save();time.sleep(120)
            if status['status']=='running':status['status']='stopped' if STOP else 'completed';save()
    except Exception as error:
        status['status']='failed';status['error_type']=type(error).__name__;save();raise
    finally:front.courier.http.close();storage.close();os.close(lock_fd)


if __name__=='__main__':main()
