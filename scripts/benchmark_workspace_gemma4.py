"""Bounded synthetic workflow sampling comparison; no application data writes."""
import argparse
import json
from pathlib import Path
import statistics
import time
import httpx
from scripts.agentcon_config import read_local_model_settings
from scripts.benchmark_macmini_model import envelope
from agent_market.workflow_model_proposer import OllamaGraphProposer
from tests.workflow_generation_cases import CASES, assess

PROFILES={'deterministic-256':{'temperature':0,'max_tokens':256},
          'deterministic-128':{'temperature':0,'max_tokens':128},
          'gemma-general':{'temperature':1,'top_p':.95,'top_k':64,'max_tokens':256}}


class SamplingTransport(httpx.BaseTransport):
    def __init__(self, options):
        self.options=options;self.remote=httpx.HTTPTransport(retries=0,trust_env=False);self.usage=[]
    def handle_request(self, request):
        body=json.loads(request.content);body.update(self.options)
        forwarded=httpx.Request(request.method,request.url,json=body,headers={k:v for k,v in request.headers.items() if k!='content-length'},extensions=request.extensions)
        response=self.remote.handle_request(forwarded);response.read()
        try:self.usage.append(response.json().get('usage',{}))
        except ValueError:self.usage.append({})
        return response
    def close(self):self.remote.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    config=read_local_model_settings('gateway-data/local-model.env');dest=Path(args.output);dest.mkdir(parents=True,exist_ok=True)
    rows=[];summary={}
    cases=[c for c in CASES if c['expected']=='review_required']
    for profile,options in PROFILES.items():
        transport=SamplingTransport(options)
        with httpx.Client(transport=transport,trust_env=False) as client:
            proposer=OllamaGraphProposer(config['WORKSPACE_MODEL_URL'],config['WORKSPACE_MODEL_NAME'],client,provider='openai',allow_http=True)
            for case in cases:
                start=time.monotonic();error=None;checks={};output=None
                try:
                    output=proposer.propose(envelope(case['prompt']))
                    review={'state':'review_required','definition':output}
                    checks=assess(case,review,200)
                except Exception as exc:error=type(exc).__name__
                rows.append(dict(profile=profile,case=case['id'],seconds=round(time.monotonic()-start,4),passed=bool(checks) and all(checks.values()) and error is None,checks=checks,error=error,usage=transport.usage[-1] if transport.usage else {},output=output))
                (dest/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
        group=[r for r in rows if r['profile']==profile]
        ordered=sorted(r['seconds'] for r in group)
        summary[profile]={'cases':len(group),'passed':sum(r['passed'] for r in group),'median_seconds':statistics.median(ordered),'p95_seconds':ordered[min(len(ordered)-1,int(len(ordered)*.95))],'failed':[r['case'] for r in group if not r['passed']]}
        print(json.dumps({profile:summary[profile]}),flush=True)
    (dest/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':main()
