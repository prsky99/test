"""The explicit configured planner uses certificate-verified isolated TLS."""
import json
from types import SimpleNamespace
import httpx
from fastapi import Request
from agent_market.workflow_composer import Composer,MODEL
from tests.test_workflow_fallback import routing
from tests.test_notification_inbox_integration import network


def test_explicit_model_plan_over_real_tls_does_not_invoke_agents(routing,network):
    rt,_,_,calls,*_=routing;app,_,_,_,transport,_=network;observed=[]
    @app.post('/api/chat')
    async def plan(request:Request):
        assert not request.headers.get('authorization') and not request.headers.get('cookie') and not request.headers.get('x-visitor-token')
        body=await request.json();observed.append(body);context=json.loads(body['messages'][1]['content']);candidate=context['candidates'][0]
        assert set(candidate)=={'id','contract'}
        return {'message':{'content':json.dumps({'steps':[{'contract':candidate['contract'],'candidate_id':candidate['id']}]})}}
    with httpx.Client(transport=transport,trust_env=False) as http:
        composer=Composer(rt,SimpleNamespace(http=http,ollama_url='https://inbox.example',generation_model='isolated-model'))
        draft=composer.generate({'prompt':'Python documentation search','planner':'model','model_authority':True,'model_notice':MODEL},1)
    assert draft['llm_used'] and draft['saved'] is False and len(observed)==1 and not calls
