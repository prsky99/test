"""Verification jobs must not turn remote schema examples into sensitive inputs."""
import pytest
from scripts.audit_edge_provider_inventory import safe_probe_input, classify, PROMPT
from scripts.verify_edge_provider_campaign import wire

@pytest.mark.parametrize('value,allowed',[
 ({'query':'weather','limit':1},True),({'date':'2026-10-23'},True),
 ({'url':'https://example.com'},True),({'api_key':'example'},False),
 ({'query':'owner@example.com'},False),({'query':'Bearer privatevalue'},False),
 ({'url':'http://127.0.0.1/admin'},False),({'url':'https://external.example/'},False),
 ({'query':'vt_'+'x'*24},False),({'account':{'token':'private'}},False),
 ({'limit':float('inf')},False),({'amount':99999999999},False),
])
def test_safe_probe_examples(value,allowed):
 assert safe_probe_input(value) is allowed


def test_probe_never_turns_x402_into_a_payment():
 assert wire({'id':1,'protocol':'x402','input':{'action':'probe'}})==('GET',None)


def test_inventory_matches_unpaid_x402_gateway_admission():
 row,recipe=classify({'id':1,'kind':'x402','active':1,'health_status':'healthy',
                      'price_usdc':100,'auth_observed':1,'url':'https://provider.example/paid'})
 assert row['status']=='static_candidate'
 assert recipe['input']=={'action':'probe'}
 assert wire(recipe)==('GET',None)
 paid_a2a,_=classify({'id':2,'kind':'a2a','active':1,'health_status':'healthy',
                      'price_usdc':100,'auth_observed':0,'url':'https://provider.example/a2a'})
 assert paid_a2a['status']=='excluded'


def test_campaign_cannot_replace_benign_intro_with_an_action():
 with pytest.raises(ValueError):wire({'id':1,'protocol':'a2a','input':{'message':'send a message'}})
 assert wire({'id':1,'protocol':'a2a','input':{'message':PROMPT}})[0]=='POST'


def test_connection_credentials_are_not_executed():
 row,recipe=classify({'id':1,'kind':'mcp','active':1,'health_status':'healthy','price_usdc':0,
                     'auth_observed':0,'url':'https://provider.example/mcp?api_key=private'})
 assert recipe is None and row['status']=='excluded'
 assert 'private' not in str(row)
