"""Opt-in six-request comparison of proposal formats and candidate order."""
import copy,json,time
from pathlib import Path
import httpx
from scripts.benchmark_macmini_model import envelope,quality
from scripts.agentcon_config import read_local_model_settings
from agent_market.workflow_model_proposer import OllamaGraphProposer,compile_proposal
from agent_market.local_generation import completion
def main():
    s=read_local_model_settings('gateway-data/local-model.env');rows=[]
    with httpx.Client(timeout=45,trust_env=False,follow_redirects=False) as client:
     for order in ('docs_first','news_first'):
      ctx=envelope('Find public Python documentation using exactly two steps. Every step must search documentation only. Do not search news.')
      if order=='news_first':ctx['candidates'].reverse()
      calls=[]
      with httpx.Client(transport=httpx.MockTransport(lambda r:calls.append(json.loads(r.content)) or httpx.Response(503))) as capture:
       try:OllamaGraphProposer(s['WORKSPACE_MODEL_URL'],s['WORKSPACE_MODEL_NAME'],capture,provider='openai',allow_http=True).propose(ctx)
       except Exception:pass
      for mode in ('json_schema','json_object','unconstrained'):
       payload=copy.deepcopy(calls[0])
       if mode=='json_object':payload['response_format']={'type':'json_object'}
       elif mode=='unconstrained':payload.pop('response_format')
       start=time.monotonic();r=client.post(s['WORKSPACE_MODEL_URL']+'/chat/completions',json=payload)
       row={'order':order,'mode':mode,'status':r.status_code,'seconds':round(time.monotonic()-start,3)}
       try:
        text=completion(r.json(),'openai',s['WORKSPACE_MODEL_NAME'])['message']['content'];row['raw_content']=text
        value=compile_proposal(ctx,json.loads(text));row['contracts']=[n['contract_id'] for n in value['nodes']];row['documentation_only']=row['contracts']==['docs.search.v1']*2
       except Exception as e:row.update(documentation_only=False,error=type(e).__name__,error_body=r.text[:700] if r.status_code!=200 else None)
       rows.append(row);print(json.dumps(row),flush=True)
    Path('reports/model-performance-2026-10-23/format-diagnostic.json').write_text(json.dumps(rows,indent=2)+'\n')


if __name__ == "__main__":
    main()
