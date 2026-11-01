"""Queue roles consume receipts without depending on public HTTP route code."""
from dataclasses import replace
import hashlib
import json

import httpx
import pytest

from agent_market.concierge.execution_policy import ExecutionDenied
from agent_market.edge_gateway import native, result_transport as results
from agent_market.workflow_persistence import dispatch_scope
from tests.test_edge_gateway import edge, catalog, ORIGIN


@pytest.mark.parametrize('ack_lost',[False,True])
def test_native_receipt_and_lost_ack_use_one_dispatch_and_the_same_saved_result(edge,ack_lost):
    edge.service.config=replace(edge.service.config,native_node_delivery=True,direct_result_delivery=True)
    packets=[];fences=[];text='A'*40000
    def worker(request):
        packets.append(request)
        assert request.headers['x-edge-result-format']=='receipt'
        run=request.url.path.split('/')[-2]
        bound=edge.service.claim(request.headers['authorization'][7:],ORIGIN,run,json.loads(request.content),'worker')
        wire=json.dumps({'parts':[{'kind':'text','text':text}]},separators=(',',':'))
        digest=hashlib.sha256(wire.encode()).hexdigest()
        results.store_result(edge.service,run,bound['attempt_id'],wire,digest)
        if ack_lost:raise httpx.ReadTimeout('Synthetic ACK loss',request=request)
        return httpx.Response(200,json={'run_id':run,'state':'succeeded','wire_hash':digest,'backend':'worker'})
    with httpx.Client(transport=httpx.MockTransport(worker)) as client,dispatch_scope(lambda:fences.append(True)),results.parent_scope('wr_'+'a'*32,'node-1'):
        output=native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='receipt-parent-node',http=client)
        assert output['ok'] and output['result']['parts'][0]['text']==text
        with pytest.raises(ExecutionDenied):
            native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='receipt-parent-node',http=client)
    assert len(packets)==len(fences)==1 and not edge.calls
    assert len(results.parent_results(edge.service,'wr_'+'a'*32))==1
