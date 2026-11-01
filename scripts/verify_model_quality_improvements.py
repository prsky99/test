"""Opt-in real-model regression of goal constraints, public help and bounded bursts."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time

import httpx

from scripts import benchmark_macmini_model as b
from scripts.agentcon_config import read_local_model_settings
from agent_market.workflow_model_proposer import OllamaGraphProposer
from agent_market.workspace_ai_support import WorkspaceAISupport, NOTICE


def save(path,value):path.write_text(json.dumps(value,indent=2,default=list)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('--live explicitly authorizes synthetic requests to the configured model')
    out=Path('reports/model-improvements-2026-10-23');out.mkdir(parents=True,exist_ok=True)
    s=read_local_model_settings('gateway-data/local-model.env');model=s['WORKSPACE_MODEL_NAME']
    cases=b.cases(model);workflows=[c for c in cases if c['feature']=='workflow']
    for c in workflows:
        if set(c['expected_contracts'])=={'docs.search.v1'}:
            c['context']['objective']+=' Every step must search documentation only. Do not search news.'
    rows=[];prepared=[]
    for repeat in range(2):
        for case in workflows:
            probe=b.Probe();start=time.monotonic();result=None;error=None;checks={}
            try:
                result=OllamaGraphProposer(s['WORKSPACE_MODEL_URL'],model,probe.client,provider='openai',allow_http=True).propose(case['context'])
                checks=b.quality(case,result)
            except Exception as exc:error=type(exc).__name__
            response=probe.responses[-1] if probe.responses else {}
            row={'feature':'workflow','case':case['id'],'repeat':repeat,'seconds':round(time.monotonic()-start,4),
                'transport_ok':response.get('status')==200,'native_ok':result is not None,'quality_pass':bool(checks) and all(checks.values()),
                'checks':checks,'error':error,'output':result,'raw_response':response}
            rows.append(row);save(out/'workflow-functional.json',rows)
            if repeat==0 and probe.requests:prepared.append((case,probe.requests[-1]))
            probe.client.close();print(json.dumps({k:v for k,v in row.items() if k not in ('output','raw_response')}),flush=True)
    direct=out/'direct-load';direct.mkdir(exist_ok=True)
    waves=asyncio.run(b.load(s,prepared,direct,plan=[('workflow',1,(1,4,8,16),prepared)]))
    from tests.test_advancement_tools import tools
    guidance=[]
    with tempfile.TemporaryDirectory(prefix='improved-model-help-') as temp:
        fixture=tools.__wrapped__(Path(temp));t=next(fixture)
        try:
            def help_one(case):
                probe=b.Probe();start=time.monotonic();engine=b.engine(s,probe.client);result=None;error=None;checks={}
                try:
                    result=WorkspaceAISupport(t['access'],engine).suggest(t['ws'],t['draft']['id'],t['snapshot']['id'],{'objective':case['objective'],'authorized':True,'notice':NOTICE},t['actors'][1]);checks=b.quality(case,result)
                except Exception as exc:error=type(exc).__name__
                record={'case':case['id'],'seconds':round(time.monotonic()-start,4),'native_ok':result is not None,
                    'model_calls':len(probe.requests),'quality_pass':bool(checks) and all(checks.values()),'checks':checks,'error':error,'output':result,'responses':probe.responses}
                probe.client.close();return record
            help_cases=[c for c in cases if c['feature']=='guidance']
            for _ in range(2):guidance.extend(help_one(c) for c in help_cases)
            save(out/'guidance-functional.json',guidance)
            with ThreadPoolExecutor(max_workers=16) as pool:burst=list(pool.map(help_one,[help_cases[i%4] for i in range(16)]))
            save(out/'guidance-burst.json',burst)
            generic=[]
            for text in ('Explain a public news research workflow','Rename the draft for a public documentation research workflow'):
                case={'feature':'guidance','id':'generated_custom_help','objective':text,'allowed_docs':help_cases[0]['allowed_docs'],'expected_docs':['safe-change-review','typed-workflow-review']}
                generic.append(help_one(case))
            save(out/'guidance-generated.json',generic)
        finally:
            try:next(fixture)
            except StopIteration:pass
    report={'model':model,'workflow_functional':b.summary(rows),'workflow_load':[{k:v for k,v in w.items() if k!='rows'} for w in waves],
        'guidance_functional':{'n':len(guidance),'quality_pass':sum(r['quality_pass'] for r in guidance),'model_calls':sum(r['model_calls'] for r in guidance)},
        'guidance_burst':{'n':len(burst),'quality_pass':sum(r['quality_pass'] for r in burst),'model_calls':sum(r['model_calls'] for r in burst),'p95_s':b.percentile([r['seconds'] for r in burst],.95)},
        'generated_guidance':{'n':len(generic),'native_ok':sum(r['native_ok'] for r in generic),'model_calls':sum(r['model_calls'] for r in generic)}}
    save(out/'live-summary.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':main()
