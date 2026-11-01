"""Protocol completion and useful output are separate; all execution evidence stays isolated."""
import json
import pytest
from unittest.mock import Mock
from tests.test_managed_agent_gateway import managed,catalog,rpc

@pytest.mark.parametrize('parts,state',[
    ([{'kind':'text','text':'[MCP \uc751\ub2f5 \uc5c6\uc74c]'}],''),
    ([{'kind':'text','text':'No response'}],''),
    ([], 'completed'),
    ([{'kind':'text','text':'   '}], 'completed')])
def test_non_answer_never_records_success_for_human_or_machine(managed,parts,state):
    store,front,client,add,*_=managed
    rid=add('Empty A2A',kind='a2a')
    def request(method,url,limit,**kwargs):
        mid=kwargs['json']['id'];obj={'parts':parts}
        if state:obj={'status':{'state':state},'artifacts':[{'parts':parts}]}
        return 200,json.dumps({'jsonrpc':'2.0','id':mid,'result':obj}).encode()
    front.courier=Mock();front.courier.resolve.return_value={'url':store.resource(rid)['url'],'v1':False};front.courier._request.side_effect=request
    human=client.post('/api/test/execute',json={'resource_id':rid,'message':'Explain current weather.'}).json()
    assert not human['ok']and not human['execution_succeeded']
    assert human['error_code']=='UPSTREAM_TOOL_ERROR'
    machine=rpc(client,f'/api/gateway/a2a/{rid}','message/send',{'message':{'parts':[{'kind':'text','text':'Explain current weather.'}]}}).json()
    assert machine['error']['data']['error_code']=='UPSTREAM_TOOL_ERROR'
    evidence=store.query("SELECT outcome FROM capability_evidence WHERE version_id IN (SELECT id FROM connection_versions WHERE resource_id=?) AND scope='execution'",(rid,))
    assert evidence and all(r['outcome']!='succeeded'for r in evidence)
