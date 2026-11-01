"""Provider connection auth boundaries with synthetic accounts and HTTP only."""
import json
from urllib.parse import urlsplit, parse_qs
import httpx
import pytest
from agent_market.workspace_provider_connections import profile, NOTICE, ProviderConnections, ConnectionError
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world, routing

ENDPOINT='https://provider.example/mcp'

@pytest.fixture
def connections(customer_flow):
    x=customer_flow;rid=x.w.ids[0]
    with x.w.store.tx() as db:
        db.execute('UPDATE resources SET url=?,auth_method=?,auth_info=?,auth_observed=1 WHERE id=?',
                   (ENDPOINT,'api_key',json.dumps({'api_key':{'header':'X-API-Key'}}),rid))
    x.manager=x.core.provider_connections;x.rid=rid;x.connection_base='/api/customer-organizations/'+x.ws+'/provider-connections'
    yield x


def payload(x,key='synthetic-provider-key-1234',revision=0):
    p=x.manager.inspect(x.ws,x.actor,x.rid)['agent']
    return {'authorized':True,'notice':NOTICE,'fingerprint':p['fingerprint'],'revision':revision,'key':key}

@pytest.mark.parametrize('method,info,kind,expected',[
 ('api_key',{'api_key':{'header':'X-API-Key'}},'mcp','api_key'),
 ('bearer',{},'a2a','api_key'),('oauth2',{},'mcp','oauth'),('none',{},'a2a','none'),
 ('basic',{},'mcp','unsupported'),('unknown',{},'a2a','unsupported'),
 ('api_key',{'api_key':{'query_param':True}},'mcp','unsupported'),
 ('api_key',{'api_key':{'header':'Cookie'}},'mcp','unsupported'),
 ('api_key',{'api_key':{'header':'X-Forwarded-Host'}},'mcp','unsupported'),
 ('api_key',{'api_key':{'header':'Host'}},'mcp','unsupported'),
 ('bearer',{},'x402','payment'),
])
def test_catalog_auth_types(method,info,kind,expected):
    p=profile({'id':1,'url':ENDPOINT,'name':'Agent','kind':kind,'auth_method':method,'auth_info':info,'active':1})
    assert p['mode']==expected

@pytest.mark.parametrize('url',['http://provider.example/mcp','https://127.0.0.1/mcp','https://localhost/mcp','https://provider.example/mcp?key=secret','https://user:pass@provider.example/mcp'])
def test_no_collection_for_unsafe_credential_destination(url):
    assert profile({'id':1,'url':url,'kind':'mcp','auth_method':'bearer'})['mode']=='unsupported'


def test_save_masks_encrypts_binds_and_disconnects(connections):
    x=connections;secret='synthetic-provider-key-1234';p=payload(x,secret)
    saved=x.manager.save_key(x.ws,x.actor,x.rid,p)
    assert saved['status']=='saved_unverified' and saved['revision']==1
    raw=x.w.store.get_meta(x.manager._key(x.ws))
    assert secret not in raw and raw.startswith('enc:v1:')
    listed=x.manager.listing(x.ws,x.actor)
    assert secret not in json.dumps(listed) and 'secret' not in json.dumps(listed)
    with pytest.raises(WorkspaceConflict):x.manager.save_key(x.ws,x.actor,x.rid,p)
    x.manager.disconnect(x.ws,x.actor,x.rid,{'revision':1})
    assert not x.manager.listing(x.ws,x.actor)['connections']
    with x.manager.access._tx(x.actor) as (db,_):
        assert secret not in json.dumps(x.manager._load(db,x.ws))


def test_owner_csrf_tenant_boundaries_and_no_secret_echo(connections):
    x=connections;url=x.connection_base+'/agents/'+str(x.rid)+'/key';p=payload(x)
    assert x.client.post(url,json=p).status_code==403
    assert x.client.post(url,json=p,headers=x.headers|{'Origin':'https://evil.example'}).status_code==403
    response=x.client.post(url,json=p,headers=x.headers)
    assert response.status_code==200 and p['key'] not in response.text
    assert 'no-store' in response.headers['cache-control']
    assert x.client.get(x.connection_base.replace(x.ws,'ws_'+'a'*32)).status_code==403
    with x.w.store.tx() as db:
        db.execute("UPDATE customer_workspace_links SET role='editor',revision=revision+1 WHERE workspace_id=?",(x.ws,))
    assert not x.manager.listing(x.ws,x.actor)['can_manage']
    with pytest.raises(WorkspaceDenied):x.manager.save_key(x.ws,x.actor,x.rid,payload(x,revision=1))


def test_current_endpoint_change_requires_reconnect_before_key_can_leave(connections):
    x=connections;x.manager.save_key(x.ws,x.actor,x.rid,payload(x))
    with x.w.store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=?',('https://changed.example/mcp',x.rid))
    assert x.manager.listing(x.ws,x.actor)['connections'][0]['status']=='reconnect_required'
    with pytest.raises(ConnectionError,match='reconnect_required'):
        x.manager.verify(x.ws,x.actor,x.rid,{'authorized':True,'notice':NOTICE,'revision':1})

@pytest.mark.parametrize('baseline,authenticated,expected',[(401,200,'authentication_verified'),(200,200,'verification_unavailable'),(401,401,'key_rejected'),(401,302,'redirect_refused')])
def test_non_task_verification_never_claims_public_metadata_proves_key(connections,baseline,authenticated,expected):
    x=connections;calls=[]
    def handler(r):
        body=json.loads(r.content);assert body['method']=='initialize'
        calls.append(bool(r.headers.get('X-API-Key')))
        code=authenticated if calls[-1] else baseline
        return httpx.Response(code,json={'jsonrpc':'2.0','id':body['id'],'result':{'protocolVersion':'2025-03-26'}})
    x.manager.http=httpx.Client(transport=httpx.MockTransport(handler))
    x.manager.save_key(x.ws,x.actor,x.rid,payload(x))
    request={'authorized':True,'notice':NOTICE,'revision':1}
    if expected=='authentication_verified':assert x.manager.verify(x.ws,x.actor,x.rid,request)['status']==expected
    else:
        with pytest.raises(ConnectionError,match=expected):x.manager.verify(x.ws,x.actor,x.rid,request)
    assert calls==([False] if baseline==200 else [False,True])
    x.manager.http.close()


def oauth(x,*,token_scope='read',iss_required=True):
    with x.w.store.tx() as db:
        db.execute('UPDATE resources SET auth_method=?,auth_info=? WHERE id=?',('oauth2','{}',x.rid))
    calls=[]
    def handle(r):
        calls.append(r)
        if 'oauth-protected-resource' in r.url.path:
            return httpx.Response(200,json={'resource':ENDPOINT,'authorization_servers':['https://auth.example'],'scopes_supported':['read','write']})
        if 'oauth-authorization-server' in r.url.path:
            return httpx.Response(200,json={'issuer':'https://auth.example','authorization_endpoint':'https://auth.example/authorize','token_endpoint':'https://auth.example/token','code_challenge_methods_supported':['S256'],'grant_types_supported':['authorization_code'],'client_id_metadata_document_supported':True,'authorization_response_iss_parameter_supported':iss_required})
        if r.url.path=='/token':
            fields=parse_qs(r.content.decode());assert fields['resource']==[ENDPOINT] and fields['code_verifier']
            return httpx.Response(200,json={'access_token':'synthetic-access-token-1234','token_type':'Bearer','scope':token_scope,'expires_in':3600})
        raise AssertionError('Unexpected endpoint')
    x.manager.http=httpx.Client(transport=httpx.MockTransport(handle))
    metadata=x.manager.oauth_metadata(x.ws,x.actor,x.rid)
    body={'authorized':True,'notice':NOTICE,'fingerprint':metadata['fingerprint'],'revision':0,'metadata_hash':metadata['metadata_hash'],'scopes':['read'],'client_id':''}
    started=x.manager.begin_oauth(x.ws,x.actor,x.rid,body,'https://agentconcierge.biz')
    params=parse_qs(urlsplit(started['authorization_url']).query)
    assert params['code_challenge_method']==['S256'] and params['resource']==[ENDPOINT]
    return params['state'][0],calls


def test_oauth_pkce_audience_single_use_and_no_token_exposure(connections):
    x=connections;state,calls=oauth(x)
    result=x.manager.complete_oauth(x.ws,x.actor,x.rid,{'state':state,'code':'synthetic-code','iss':'https://auth.example'})
    assert result['status']=='oauth_authorized' and 'synthetic-access-token' not in json.dumps(result)
    with pytest.raises(ConnectionError,match='oauth_invalid'):
        x.manager.complete_oauth(x.ws,x.actor,x.rid,{'state':state,'code':'synthetic-code','iss':'https://auth.example'})
    assert len([r for r in calls if r.url.path=='/token'])==1
    x.manager.http.close()

@pytest.mark.parametrize('failure',['issuer','cancel','scope','disconnect'])
def test_oauth_rejects_mismatch_cancel_scope_expansion_and_disconnect(connections,failure):
    x=connections;state,calls=oauth(x,token_scope='write' if failure=='scope' else 'read')
    query={'state':state,'code':'synthetic-code','iss':'https://wrong.example' if failure=='issuer' else 'https://auth.example'}
    if failure=='cancel':query={'state':state,'error':'access_denied','iss':'https://auth.example'}
    if failure=='disconnect':
        with x.manager.access._tx(x.actor,write=True) as (db,_):
            data=x.manager._load(db,x.ws);data['flows']={};x.manager._save(db,x.ws,data)
    with pytest.raises(ConnectionError):x.manager.complete_oauth(x.ws,x.actor,x.rid,query)
    assert not x.manager.listing(x.ws,x.actor)['connections']
    if failure!='scope':assert not any(r.url.path=='/token' for r in calls)
    x.manager.http.close()


def test_search_classifies_every_protocol_without_exposing_raw_metadata(connections):
    x=connections
    result=x.client.get(x.connection_base+'/agents',params={'q':str(x.rid)})
    assert result.status_code==200 and result.json()['agents'][0]['mode']=='api_key'
    assert 'auth_info' not in result.text
    assert x.client.get(x.connection_base+'/agents',params={'q':'provider.example'}).status_code==200
    assert x.client.get(x.connection_base+'/agents',params={'q':'%'}).json()['agents']==[]


def test_cross_site_oauth_callback_is_session_bound_scrubbed_and_single_use(connections):
    from fastapi.testclient import TestClient
    from agent_market.customer_identity_service import COOKIE
    x=connections;state,calls=oauth(x);observed=[]
    app=x.client.app
    async def audited(scope,receive,send):
        async def sent(message):
            if message['type']=='http.response.start':observed.append(scope.get('query_string'))
            await send(message)
        await app(scope,receive,sent)
    with TestClient(audited,base_url='https://customer.test') as client:
        client.cookies.set(COOKIE,x.s.raw)
        result=client.get('/api/customer-provider-oauth/'+str(x.rid)+'/callback',
                          params={'code':'synthetic-code','state':state,'iss':'https://auth.example'},
                          headers={'Sec-Fetch-Site':'cross-site'})
        assert result.status_code==200 and 'authorization saved' in result.text
        assert 'synthetic-code' not in result.text and state not in result.text
        assert observed[-1]==b'' and 'no-store' in result.headers['cache-control']
        replay=client.get('/api/customer-provider-oauth/'+str(x.rid)+'/callback',params={'code':'synthetic-code','state':state,'iss':'https://auth.example'})
        assert 'was not saved' in replay.text
    x.manager.http.close()


def test_oauth_cannot_complete_from_other_browser_session(connections):
    from dataclasses import replace
    x=connections;state,calls=oauth(x)
    # The existing signed-in owner is required; no other session is inferred.
    bad=replace(x.actor,session_ref='0'*64)
    with pytest.raises(WorkspaceDenied):
        x.manager.complete_oauth(x.ws,bad,x.rid,{'code':'synthetic-code','state':state,'iss':'https://auth.example'})
    assert not any(r.url.path=='/token' for r in calls)
    x.manager.http.close()


def test_manual_candidates_explain_current_provider_execution_limit(connections):
    x=connections
    result=x.client.get(x.base+'/typed/options')
    assert result.status_code==200
    candidate=next(c for c in result.json()['options']['candidates'] if c['resource_id']==x.rid)
    assert candidate['executable'] is False and candidate['name']
    assert 'Provider authorization' in candidate['connection_reason']


def test_disconnect_tombstone_rejects_late_save_after_reconnect(connections):
    x=connections
    first=payload(x);x.manager.save_key(x.ws,x.actor,x.rid,first)
    x.manager.disconnect(x.ws,x.actor,x.rid,{'revision':1})
    inspected=x.manager.inspect(x.ws,x.actor,x.rid)
    assert inspected['connection'] is None and inspected['revision']==2
    with pytest.raises(WorkspaceConflict):x.manager.save_key(x.ws,x.actor,x.rid,first)
    x.manager.save_key(x.ws,x.actor,x.rid,payload(x,revision=2))
    with pytest.raises(WorkspaceConflict):x.manager.save_key(x.ws,x.actor,x.rid,payload(x,revision=1))


def test_credential_ciphertext_cannot_be_moved_to_another_workspace(connections):
    x=connections;x.manager.save_key(x.ws,x.actor,x.rid,payload(x))
    other=x.core.organizations.create({'name':'Other synthetic workspace'},x.s.customer)['id']
    other_actor=x.core.actor(other,x.s.customer)
    x.w.store.set_meta(x.manager._key(other),x.w.store.get_meta(x.manager._key(x.ws)))
    with pytest.raises(ConnectionError,match='storage_unavailable'):x.manager.listing(other,other_actor)


def test_failed_recheck_clears_previous_authentication_verified_status(connections):
    x=connections;reject={'value':False}
    def handler(request):
        body=json.loads(request.content)
        status=200 if request.headers.get('x-api-key') and not reject['value'] else 401
        return httpx.Response(status,json={'jsonrpc':'2.0','id':body['id'],'result':{'protocolVersion':'2025-03-26'}})
    x.manager.http=httpx.Client(transport=httpx.MockTransport(handler))
    x.manager.save_key(x.ws,x.actor,x.rid,payload(x))
    x.manager.verify(x.ws,x.actor,x.rid,{'authorized':True,'notice':NOTICE,'revision':1})
    reject['value']=True
    with pytest.raises(ConnectionError,match='key_rejected'):
        x.manager.verify(x.ws,x.actor,x.rid,{'authorized':True,'notice':NOTICE,'revision':2})
    assert x.manager.listing(x.ws,x.actor)['connections'][0]['status']=='authentication_rejected'
    x.manager.http.close()
