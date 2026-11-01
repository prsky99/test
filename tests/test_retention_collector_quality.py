"""Collection cannot turn transport acknowledgements into successful task trials."""
import json
import httpx
import pytest
from tests.test_a2a import world,CARD_V03,a2a_resource

@pytest.mark.parametrize('reply',[
    '[MCP \uc751\ub2f5 \uc5c6\uc74c]','pong',
    '{"status":"ok","response":"pong","result":"Completed task"}',
    '{"findings":"Node executed task deterministically with 100% schema conformance."}'
])
def test_collector_does_not_publish_a_false_success(reply):
    url='https://agent.example/.well-known/agent-card.json'
    store,_,prober=world({url:CARD_V03},reply=reply)
    rid=a2a_resource(store,'https://agent.example')
    stats=prober.run_due()
    assert stats.get('trial_ok',0)==0
    row=store.resource(rid);trial=json.loads(row['trial_info'])
    assert row['trial_ok']==0 and trial['ok']is False
    assert 'no usable task result' in trial['error']
    store._db.close()
