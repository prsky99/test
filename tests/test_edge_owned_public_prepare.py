"""Signed public ingress keeps first-party execution local before creating a grant."""
import pytest
from tests.test_edge_gateway import edge,catalog,service_request,ORIGIN
from tests.test_edge_gateway_catalog import enable,mcp_resource,bridge

@pytest.mark.parametrize('marker',['source','key'])
def test_owned_public_prepare_returns_origin_without_http_or_new_grants(edge,catalog,monkeypatch,marker):
    enable(edge,monkeypatch);rid=mcp_resource(edge,catalog)
    with edge.store.tx()as db:
        if marker=='source':db.execute("UPDATE resources SET source='agentconcierge-owned' WHERE id=?",(rid,))
        else:db.execute("UPDATE resources SET key='agentconcierge-owned:technology-news' WHERE id=?",(rid,))
    before=edge.store.query('SELECT COUNT(*) FROM edge_gateway_runs')[0][0]
    monkeypatch.setattr(edge.service,'prepare',lambda *a:pytest.fail('No new authority for local first-party execution.'))
    result=bridge(edge,rid,{'tool':'get_weather','arguments':{'city':'Tokyo'}},testbench=True)
    assert result.status_code==200 and result.json()=={'backend':'origin'}
    assert not edge.calls
    assert edge.store.query('SELECT COUNT(*) FROM edge_gateway_runs')[0][0]==before


def test_owned_routing_does_not_skip_authentication_or_origin_checks(edge,catalog,monkeypatch):
    enable(edge,monkeypatch);rid=mcp_resource(edge,catalog)
    with edge.store.tx()as db:db.execute("UPDATE resources SET source='agentconcierge-owned' WHERE id=?",(rid,))
    payload={'resource_id':rid,'origin':ORIGIN,'input':{},'idempotency_key':'owned-public-auth-check'}
    assert edge.client.post('/api/edge-gateway-internal/v1/public-prepare',json=payload).status_code==401
    result=service_request(edge,'public-prepare',{**payload,'origin':'https://attacker.example'})
    assert result.status_code==400
