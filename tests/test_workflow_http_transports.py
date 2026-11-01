"""The shared runtime uses actual REST/x402 HTTP transports without automatic charges."""
import httpx
import pytest

from agent_market.collector import usage
from agent_market.concierge.proxy import McpProxy
from tests.test_workflow_runtime import runtime, save, node, wait  # noqa: F401


@pytest.mark.parametrize('kind',['rest','x402'])
def test_registered_http_execution_and_provider_authorization_guard(runtime,kind):
    rt,_,_=runtime;requests=[]
    def remote(request):
        requests.append(request)
        assert request.url.params['city']=='Tokyo'
        return httpx.Response(200,json={'weather':'Tokyo live HTTP result'})
    transport=httpx.Client(transport=httpx.MockTransport(remote))
    rt.proxy=McpProxy(rt.store,allow_private=True,http=transport)
    spec={'openapi':'3.0.0','info':{'title':'Weather','version':'1'},'servers':[{'url':'https://weather.example/v1'}],
          'paths':{'/weather':{'get':{'operationId':'get_weather','parameters':[{'name':'city','in':'query','required':True,'schema':{'type':'string'}}]}}}}
    rid=rt.store.upsert_resource({'key':kind+':https://weather.example/v1','kind':kind,'source':'test','name':'HTTP Weather','description':'Weather','category':'data_utility','url':'https://weather.example/v1','price_usdc':0,'method':'GET','details':{'openapi_spec':spec} if kind=='rest' else {}})
    tools=usage.compact_tools([{'name':'get_weather','inputSchema':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}])
    rt.store.record_usage(rid,tools=tools,digest=usage.tools_hash(tools),guide={},changes=None,trial={'ok':True})
    wf=save(rt.store,[{**node(resource_id=rid,action='get_weather',input={'city':'Tokyo'}),'kind':kind}])
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded' and 'Tokyo live HTTP result' in result['node_results'][0]['output']
    assert len(requests)==1
    with rt.store.tx() as db:db.execute('UPDATE resources SET price_usdc=100 WHERE id=?',(rid,))
    rejected=wait(rt,rt.submit(wf))
    assert rejected['status']=='failed' and 'authorization' in rejected['node_results'][0]['error']
    assert len(requests)==1
    transport.close()
