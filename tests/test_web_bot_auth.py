"""Pinned RFC 9421 proof, freshness, replay and quota-boundary regressions."""
import base64
import copy

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
import pytest

from agent_market.concierge.web_bot_auth import Verifier,WebBotAuth,VERIFIED_READER,b64url,thumbprint


def signed_fixture():
    now=1793250000;key=Ed25519PrivateKey.generate();raw=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    jwk={'kty':'OKP','crv':'Ed25519','x':b64url(raw)};kid=thumbprint(jwk);agent='"https://verified-reader.example"'
    components='("@authority" "@method" "@path" "@query" "signature-agent")'
    params=f';created={now-1};expires={now+60};keyid="{kid}";alg="ed25519";nonce="fixture-unique-nonce-0123456789";tag="web-bot-auth"'
    text='\n'.join(('"@authority": agentconcierge.biz','"@method": GET','"@path": /api/explore','"@query": ?q=weather','"signature-agent": '+agent,'"@signature-params": '+components+params))
    signature=base64.b64encode(key.sign(text.encode())).decode()
    scope={'type':'http','method':'GET','path':'/api/explore','raw_path':b'/api/explore','query_string':b'q=weather','headers':[(b'signature-agent',agent.encode()),(b'signature-input',('sig1='+components+params).encode()),(b'signature',('sig1=:'+signature+':').encode())]}
    seen=set()
    def replay(value,ttl):
        if value in seen:return False
        seen.add(value);return True
    verifier=Verifier('https://agentconcierge.biz',{'https://verified-reader.example':[jwk]},clock=lambda:now,replay=replay)
    return verifier,scope


def test_valid_pinned_proof_has_only_read_quota_identity_and_replay_is_refused():
    verifier,scope=signed_fixture();result=verifier.verify(scope)
    assert result['multiplier']==2 and set(result)=={'key','multiplier'}
    assert verifier.verify(scope) is None


@pytest.mark.parametrize('change',['path','query','method','signature','unknown_origin','expiry','duplicate_header'])
def test_tampered_untrusted_or_ambiguous_signatures_do_not_gain_quota(change):
    verifier,scope=signed_fixture();scope=copy.deepcopy(scope)
    if change=='path':scope['raw_path']=b'/api/overview'
    if change=='query':scope['query_string']=b'q=other'
    if change=='method':scope['method']='POST'
    if change=='signature':scope['headers'][-1]=(b'signature',b'sig1=:AAAA:')
    if change=='unknown_origin':verifier.keys={}
    if change=='expiry':verifier.clock=lambda:1793250400
    if change=='duplicate_header':scope['headers'].append(scope['headers'][0])
    assert verifier.verify(scope) is None


def test_signature_identity_is_not_workspace_or_mutation_authority():
    verifier,scope=signed_fixture();app=FastAPI()
    @app.get('/api/explore')
    def value(request:Request):return {'quota_identity':bool(VERIFIED_READER.get()),'workspace_authorized':False}
    app.add_middleware(WebBotAuth,origin='https://agentconcierge.biz',verifier=verifier)
    client=TestClient(app);headers={k.decode():v.decode() for k,v in scope['headers']}
    result=client.get('/api/explore?q=weather',headers=headers)
    assert result.json()=={'quota_identity':True,'workspace_authorized':False}
    assert result.headers['web-bot-auth']=='verified' and result.headers['cache-control']=='no-store'
    assert VERIFIED_READER.get() is None
