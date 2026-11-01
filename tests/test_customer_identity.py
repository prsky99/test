"""Customer identity fixtures never contact identity providers or project servers."""
import base64
from contextlib import contextmanager
import copy
import json
import logging
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.customer_identity import CustomerIdentity, CustomerActor, google_config, load_google_config, _b64
from agent_market.customer_identity_service import router_for, COOKIE, FLOW_COOKIE
from agent_market.workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid, SessionActor
from tests.test_workspace_access import workspace_world, provision


def customer_world():
    store, access, staff = workspace_world()
    @contextmanager
    def tx():
        with store._lock:
            assert not store._db.in_transaction
            store._db.execute('BEGIN IMMEDIATE')
            try:
                yield store._db
                store._db.commit()
            except BaseException:
                store._db.rollback()
                raise
    store.tx = tx
    raw = 'a' * 64
    from agent_market.gateway.admin_auth import session_reference
    ref = session_reference(raw)
    with store._db:
        store._db.execute('UPDATE admin_sessions SET token=? WHERE user_id=1', (ref,))
    staff[1] = SessionActor(1, ref)
    ws = provision((store, access, staff))['id']
    config = google_config('synthetic-client.apps.googleusercontent.com',
                           'https://agentconcierge.biz/api/customer-auth/callback', 'synthetic-google-server-secret')
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()
    state = {'nonce': None, 'claims': {}, 'header': {}, 'calls': [], 'status': 200, 'keys': None}
    jwk = {'kty': 'RSA', 'kid': 'synthetic-key', 'alg': 'RS256', 'use': 'sig',
           'n': _b64(public.n.to_bytes(256, 'big')), 'e': _b64(public.e.to_bytes(3, 'big'))}
    def handler(request):
        state['calls'].append(str(request.url))
        if request.url == config.token_endpoint:
            form = parse_qs(request.content.decode())
            assert form['client_secret'] == ['synthetic-google-server-secret']
            assert len(form['code_verifier'][0]) >= 43
            claims = {'iss': config.issuer, 'aud': config.client_id, 'sub': 'synthetic-google-subject',
                      'iat': int(time.time()), 'exp': int(time.time()) + 3600, 'nonce': state['nonce'],
                      'email': 'never-copy@example.invalid', 'role': 'superadmin'} | state['claims']
            header = {'alg': 'RS256', 'kid': 'synthetic-key', 'typ': 'JWT'} | state['header']
            first = _b64(json.dumps(header).encode()) + '.' + _b64(json.dumps(claims).encode())
            signature = private.sign(first.encode(), padding.PKCS1v15(), hashes.SHA256())
            return httpx.Response(state['status'], json={'id_token': first + '.' + _b64(signature), 'access_token': 'never-store-access-token'})
        if request.url == config.jwks_uri:
            return httpx.Response(200, json={'keys': state['keys'] if state['keys'] is not None else [jwk]})
        raise AssertionError('No unconfigured outbound destination is allowed.')
    http = httpx.Client(transport=httpx.MockTransport(handler))
    core = CustomerIdentity(store, b'synthetic-customer-key-32bytes!!!', config, http)
    return SimpleNamespace(store=store, access=access, staff=staff, ws=ws, config=config, core=core,
                           http=http, state=state, jwk=jwk, private=private, raw_staff=raw)


@pytest.fixture
def customer():
    w = customer_world()
    try:
        yield w
    finally:
        w.http.close(); w.store._db.close()


def login(w, browser='b' * 64):
    prepared = w.core.begin(browser)
    query = parse_qs(urlsplit(prepared['authorization_url']).query)
    w.state['nonce'] = query['nonce'][0]
    return w.core.complete(query['state'][0], 'synthetic-code', browser)


def linked(w, role='runner'):
    auth = login(w)
    w.core.set_link(w.access, w.ws, {'customer_id': auth['customer_id'], 'role': role, 'active': True, 'revision': 0}, w.staff[1])
    return auth


def test_google_only_explicit_configuration_and_inert_default(customer):
    w = customer
    disabled = CustomerIdentity(w.store, b'synthetic-other-key-32bytes!!!!!!')
    assert not disabled.options()['configured']
    with pytest.raises(WorkspaceDenied): disabled.begin('b' * 64)
    assert w.state['calls'] == []
    assert load_google_config({}) is None
    assert load_google_config({'GOOGLE_OIDC_CLIENT_ID': w.config.client_id}) is None
    with pytest.raises(WorkspaceInvalid):
        google_config('bad-client', w.config.redirect_uri, 'unused')
    changed = copy.copy(w.config)
    object.__setattr__(changed, 'issuer', 'https://different.example')
    with pytest.raises(WorkspaceInvalid): changed.validate()
    assert 'synthetic-google-server-secret' not in repr(w.config)


def test_invalid_named_provider_configuration_disables_only_that_provider(customer,monkeypatch):
    from agent_market.customer_identity import customer_identity_for
    for name in ('GOOGLE_OIDC_CLIENT_ID','GOOGLE_OIDC_REDIRECT_URI','GOOGLE_OIDC_CLIENT_SECRET',
                 'GITHUB_OAUTH_CLIENT_ID','GITHUB_OAUTH_REDIRECT_URI','GITHUB_OAUTH_CLIENT_SECRET'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('GOOGLE_OIDC_CLIENT_ID','invalid')
    monkeypatch.setenv('GOOGLE_OIDC_REDIRECT_URI','https://agentconcierge.biz/api/customer-auth/callback')
    monkeypatch.setenv('GOOGLE_OIDC_CLIENT_SECRET','synthetic-only')
    disabled=customer_identity_for(customer.store,b'synthetic-customer-key-32bytes!!!')
    assert not disabled.options()['configured']
    monkeypatch.setenv('GITHUB_OAUTH_CLIENT_ID','synthetic-client')
    monkeypatch.setenv('GITHUB_OAUTH_REDIRECT_URI','https://agentconcierge.biz/api/customer-auth/github/callback')
    monkeypatch.setenv('GITHUB_OAUTH_CLIENT_SECRET','synthetic-only')
    mixed=customer_identity_for(customer.store,b'synthetic-customer-key-32bytes!!!')
    assert mixed.config is None and mixed.github_config is not None
    assert mixed.options()['configured'] and customer.state['calls']==[]


def test_code_pkce_nonce_crypto_subject_session_and_no_implicit_membership(customer):
    w = customer; auth = login(w)
    actor = w.core.actor(auth['session_token'])
    assert isinstance(actor, CustomerActor) and not isinstance(actor, SessionActor)
    assert w.core.session(auth['session_token'])['workspaces'] == []
    with w.core.tx() as db:
        with pytest.raises(WorkspaceDenied): w.core.authorize(db, actor, w.ws, 'execute')
    serialized = '\n'.join(str(tuple(row)) for table in ('customer_identities','customer_sessions','customer_oidc_flows')
                           for row in w.store._db.execute('SELECT * FROM ' + table))
    for secret in ('synthetic-google-subject', 'never-copy@example.invalid', 'never-store-access-token',
                   'synthetic-google-server-secret', auth['session_token']):
        assert secret not in serialized
    assert len(w.state['calls']) == 2


@pytest.mark.parametrize('claims', [{'iss':'https://wrong.example'}, {'aud':'wrong'}, {'azp':'wrong'},
    {'aud':['synthetic-client.apps.googleusercontent.com','other']}, {'nonce':'wrong'}, {'exp':0},
    {'exp':True}, {'iat':float('inf')}, {'sub':''}, {'nbf':time.time()+9999}])
def test_signed_invalid_google_identity_is_refused_without_session(customer, claims):
    w=customer;w.state['claims']=claims
    with pytest.raises(WorkspaceDenied): login(w)
    assert w.store._db.execute('SELECT COUNT(*) FROM customer_sessions').fetchone()[0] == 0


@pytest.mark.parametrize('header', [{'alg':'none'}, {'alg':'HS256'}, {'kid':'unknown'}, {'jku':'https://outside.invalid/jwks'}])
def test_algorithm_key_and_untrusted_header_are_failclosed(customer, header):
    w=customer;w.state['header']=header
    with pytest.raises(WorkspaceDenied): login(w)
    assert len(w.state['calls']) <= 2


def test_state_browser_binding_oneuse_and_failed_exchange_not_retried(customer):
    w=customer; prepared=w.core.begin('b'*64);q=parse_qs(urlsplit(prepared['authorization_url']).query)
    w.state['nonce']=q['nonce'][0]
    with pytest.raises(WorkspaceDenied): w.core.complete(q['state'][0],'code','c'*64)
    assert not w.state['calls']
    w.state['status']=500
    with pytest.raises(WorkspaceDenied): w.core.complete(q['state'][0],'code','b'*64)
    w.state['status']=200
    with pytest.raises(WorkspaceDenied): w.core.complete(q['state'][0],'code','b'*64)
    assert len(w.state['calls'])==1


def test_explicit_customer_link_bff_scope_current_revision_and_logout(customer):
    w=customer;auth=linked(w); token=w.core.issue_token(auth['session_token'],w.ws,'execute')
    scope=w.core.validate_token(token['access_token'],w.ws,'execute')
    assert scope['role']=='runner' and scope['token_ref'].startswith('cbr_')
    with pytest.raises(WorkspaceDenied): w.core.validate_token(token['access_token'],w.ws,'read')
    w.core.set_link(w.access,w.ws,{'customer_id':auth['customer_id'],'role':'viewer','active':True,'revision':1},w.staff[1])
    with pytest.raises(WorkspaceDenied): w.core.validate_token(token['access_token'],w.ws,'execute')
    with w.core.tx() as db:
        with pytest.raises(WorkspaceDenied): w.core.authorize(db,w.core.actor_from_scope(scope),w.ws,'execute')
    read=w.core.issue_token(auth['session_token'],w.ws,'read')
    w.core.logout(auth['session_token'])
    with pytest.raises(WorkspaceDenied):w.core.validate_token(read['access_token'],w.ws,'read')
    with pytest.raises(WorkspaceDenied):w.core.actor(auth['session_token'])


def test_google_account_does_not_match_staff_by_email_or_role(customer):
    w=customer;auth=login(w)
    assert auth['customer_id'].startswith('cu_') and w.core.session(auth['session_token'])['workspaces']==[]
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_memberships').fetchone()[0]==1
    assert len(w.core.links(w.access,w.ws,w.staff[1]))==0


def test_customer_real_api_google_fields_cookie_csrf_and_disabled_page(customer):
    w=customer;app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core))
    with TestClient(app,base_url='https://agentconcierge.biz') as client:
        page=client.get('/customer/sign-in')
        assert page.status_code==200 and 'Sign in with Google' in page.text
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        prepared=client.post('/api/customer-auth/begin',json={});assert prepared.status_code==200
        q=parse_qs(urlsplit(prepared.json()['authorization_url']).query);w.state['nonce']=q['nonce'][0]
        result=client.get('/api/customer-auth/callback',headers={'Sec-Fetch-Site':'cross-site'},params={'state':q['state'][0],'code':'code','scope':'openid','authuser':'0','prompt':'consent'})
        assert result.status_code==200,result.text
        assert 'session_token' not in result.json() and COOKIE in client.cookies
        cookies=result.headers.get('set-cookie','').lower();assert 'httponly' in cookies and 'secure' in cookies
        current=client.get('/api/customer-auth/session');assert current.status_code==200
        csrf=current.json()['session']['csrf_token']
        assert client.post('/api/customer-auth/logout',json={}).status_code==403
        assert client.post('/api/customer-auth/logout',headers={'X-Customer-CSRF':csrf},json={}).status_code==200
        assert client.get('/api/customer-auth/session').status_code==401


def test_google_cancel_consumes_state_and_never_echoes_provider_error(customer):
    w=customer;app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core))
    with TestClient(app,base_url='https://agentconcierge.biz') as client:
        q=parse_qs(urlsplit(client.post('/api/customer-auth/begin',json={}).json()['authorization_url']).query)
        result=client.get('/api/customer-auth/callback',params={'state':q['state'][0],'error':'access_denied','error_description':'private-untrusted-diagnostic'})
        assert result.status_code==200 and result.json()['cancelled']
        assert 'private-untrusted' not in result.text and not w.state['calls']


@pytest.mark.parametrize('raw',['{"purpose":"read","purpose":"execute"}','{"purpose":NaN}','{"purpose":1e999}','[]'])
def test_customer_raw_request_security(customer,raw):
    w=customer;app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core))
    with TestClient(app,base_url='https://agentconcierge.biz') as client:
        result=client.post('/api/customer-auth/begin',content=raw)
        assert result.status_code==400 and result.headers['cache-control']=='no-store'
        assert not w.state['calls']


def github_world(w, google=True):
    from agent_market.customer_identity import GitHubConfig
    config=GitHubConfig('synthetic-github-client','https://agentconcierge.biz/api/customer-auth/github/callback','synthetic-github-server-secret')
    w.github={'id':1234567,'login':'never-link-by-login','email':'never-copy@example.invalid'}
    w.github_token={'access_token':'gho_synthetic_token_never_persist','token_type':'bearer'}
    original=w.http
    def handler(request):
        if request.url==config.token_endpoint:
            w.state['calls'].append(str(request.url));form=parse_qs(request.content.decode())
            assert form['client_secret']==['synthetic-github-server-secret'] and len(form['code_verifier'][0])>=43
            return httpx.Response(200,json=w.github_token)
        if request.url==config.user_endpoint:
            w.state['calls'].append(str(request.url));assert request.headers['authorization']=='Bearer gho_synthetic_token_never_persist'
            return httpx.Response(200,json=w.github)
        return original._transport.handle_request(request)
    w.github_http=httpx.Client(transport=httpx.MockTransport(handler))
    w.core=CustomerIdentity(w.store,b'synthetic-customer-key-32bytes!!!',w.config if google else None,w.github_http,github_config=config)
    return config


def github_login(w):
    prepared=w.core.begin('d'*64,'github');query=parse_qs(urlsplit(prepared['authorization_url']).query)
    assert query['code_challenge_method']==['S256'] and 'nonce' not in query
    return w.core.complete(query['state'][0],'github-code','d'*64,'github')


def test_github_code_pkce_user_identity_is_not_google_or_staff(customer):
    w=customer;config=github_world(w)
    try:
        google=login(w);github=github_login(w)
        assert google['customer_id']!=github['customer_id']
        assert w.core.session(google['session_token'])['workspaces']==w.core.session(github['session_token'])['workspaces']==[]
        raw='\n'.join(str(tuple(row)) for table in ('customer_identities','customer_sessions','customer_oidc_flows') for row in w.store._db.execute('SELECT * FROM '+table))
        assert all(value not in raw for value in ('1234567','never-link-by-login','never-copy@example.invalid','gho_synthetic_token_never_persist','synthetic-github-server-secret'))
        assert 'synthetic-github-server-secret' not in repr(config)
    finally:w.github_http.close()


@pytest.mark.parametrize('identity',[True,0,-1,'1234567',None])
def test_github_id_is_strict_trusted_numeric_identity(customer,identity):
    w=customer;github_world(w);w.github['id']=identity
    try:
        with pytest.raises(WorkspaceDenied):github_login(w)
        assert w.store._db.execute('SELECT COUNT(*) FROM customer_sessions').fetchone()[0]==0
    finally:w.github_http.close()


def test_github_only_configuration_session_and_provider_mixup_refusal(customer):
    w=customer;github_world(w,google=False)
    try:
        assert w.core.options()['configured'] and w.core.config_hash
        prepared=w.core.begin('d'*64,'github');q=parse_qs(urlsplit(prepared['authorization_url']).query)
        with pytest.raises(WorkspaceDenied):w.core.complete(q['state'][0],'code','d'*64,'google')
        assert not w.state['calls']
        auth=w.core.complete(q['state'][0],'code','d'*64,'github')
        assert w.core.session(auth['session_token'])['customer_id']==auth['customer_id']
    finally:w.github_http.close()


def test_github_callback_api_and_public_admin_route_separation(customer):
    w=customer;github_world(w)
    try:
        app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core,admin=False))
        with TestClient(app,base_url='https://agentconcierge.biz') as client:
            assert client.get('/admin/api/workflow-workspaces/'+w.ws+'/customers').status_code==404
            start=client.post('/api/customer-auth/begin',json={'provider':'github'});assert start.status_code==200
            q=parse_qs(urlsplit(start.json()['authorization_url']).query)
            response=client.get('/api/customer-auth/github/callback',headers={'Sec-Fetch-Site':'cross-site'},params={'code':'code','state':q['state'][0]})
            assert response.status_code==200,response.text
            assert client.get('/api/customer-auth/session').status_code==200
            assert 'Sign in with GitHub' in client.get('/customer/sign-in').text
            assert client.get('/customer/workspaces').status_code==200
        admin_app=FastAPI();admin_app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core,public=False))
        with TestClient(admin_app,base_url='https://agentconcierge.biz') as client:
            assert client.get('/api/customer-auth/options').status_code==404
    finally:w.github_http.close()


@pytest.mark.parametrize('provider', ['google', 'github'])
def test_expired_session_relogin_cross_site_document_redirect(customer, provider):
    w = customer
    github_world(w)
    app = FastAPI()
    app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    navigation = {'Accept': 'text/html', 'Sec-Fetch-Site': 'cross-site',
                  'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
    try:
        with TestClient(app, base_url='https://agentconcierge.biz') as client:
            old = login(w)
            client.cookies.set(COOKIE, old['session_token'])
            with w.core.tx() as db:
                db.execute('UPDATE customer_sessions SET expires=0')
            expired = client.get('/customer/workspaces', headers=navigation, follow_redirects=False)
            assert expired.status_code == 303 and expired.headers['location'] == '/customer/sign-in'
            start = client.post('/api/customer-auth/begin', json={'provider': provider})
            query = parse_qs(urlsplit(start.json()['authorization_url']).query)
            if provider == 'google':
                w.state['nonce'] = query['nonce'][0]
            path = '/api/customer-auth/' + ('callback' if provider == 'google' else 'github/callback')
            result = client.get(path, params={'state': query['state'][0], 'code': 'synthetic-code'},
                                headers=navigation, follow_redirects=True)
            assert result.status_code == 200, result.text
            assert result.url.path == '/customer/workspaces' and 'Your workspaces' in result.text
            assert result.headers['cache-control'] == 'no-store'
            assert client.get('/api/customer-auth/session').status_code == 200
            assert client.get('/customer/organizations', headers=navigation).status_code == 200
            # Navigating into HTML never grants cross-site API access, even
            # when an attacker sends forged navigation metadata to an API.
            assert client.get('/api/customer-auth/session', headers=navigation).status_code == 403
            assert client.get('/api/customer-organizations', headers=navigation).status_code == 403
            csrf = client.get('/api/customer-auth/session').json()['session']['csrf_token']
            assert client.post('/api/customer-auth/logout', json={},
                               headers={**navigation, 'X-Customer-CSRF': csrf}).status_code == 403
            assert client.get('/api/customer-auth/session').status_code == 200
    finally:
        w.github_http.close()


@pytest.mark.parametrize('metadata', [
    {'Sec-Fetch-Site': 'cross-site'},
    {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty'},
    {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'iframe'},
    {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document',
     'Origin': 'https://untrusted.invalid'},
])
def test_workspace_document_exception_rejects_non_document_requests(customer, metadata):
    w = customer
    app = FastAPI()
    app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    with TestClient(app, base_url='https://agentconcierge.biz') as client:
        client.cookies.set(COOKIE, login(w)['session_token'])
        for path in ('/customer/workspaces', '/customer/organizations'):
            assert client.get(path, headers=metadata).status_code == 403


@pytest.mark.parametrize('provider', ['google', 'github'])
@pytest.mark.parametrize('outcome', ['success', 'cancel', 'duplicate', 'invalid_state', 'oversized', 'rate_limited'])
def test_callback_response_time_uvicorn_access_scope_omits_oneuse_query(customer, monkeypatch, provider, outcome):
    """Use Uvicorn's real path/formatter without patching a shared logger.

    This observes the response-start ASGI scope used by Uvicorn. Earlier ingress
    proxy logs, browser history and provider logs are deliberately outside scope.
    """
    from uvicorn.logging import AccessFormatter
    from uvicorn.protocols.utils import get_client_addr, get_path_with_query_string
    from agent_market import customer_identity_service as service

    w = customer
    if provider == 'github':
        github_world(w)
    if outcome == 'rate_limited':
        original_limiter = service.RateLimiter
        monkeypatch.setattr(service, 'RateLimiter', lambda amount: original_limiter(0 if amount == 30 else amount))
    app = FastAPI()
    app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    observed = []
    formatter = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)

    async def audit_scope(scope, receive, send):
        async def observe(message):
            if message['type'] == 'http.response.start' and scope['path'].endswith('/callback'):
                # Same five arguments and formatter as Uvicorn's HTTP cycle.
                args = (get_client_addr(scope), scope['method'], get_path_with_query_string(scope),
                        scope['http_version'], message['status'])
                record = logging.LogRecord('isolated.uvicorn.access', logging.INFO, '', 0,
                                           '%s - "%s %s HTTP/%s" %d', args, None)
                observed.append((scope['query_string'], formatter.format(record)))
            await send(message)
        await app(scope, receive, observe)

    try:
        with TestClient(audit_scope, base_url='https://customer.test') as client:
            prepared = client.post('/api/customer-auth/begin', json={'provider': provider})
            assert prepared.status_code == 200
            query = parse_qs(urlsplit(prepared.json()['authorization_url']).query)
            if provider == 'google':
                w.state['nonce'] = query['nonce'][0]
            state = query['state'][0]
            code = 'synthetic-oneuse-secret-code'
            path = '/api/customer-auth/' + ('github/' if provider == 'github' else '') + 'callback'
            params = [('state', state), ('code', code)]
            expected_status = 200
            if outcome == 'cancel':
                params = [('state', state), ('error', 'access_denied'), ('error_description', 'synthetic-private-error')]
            elif outcome == 'duplicate':
                params += [('state', state)]
                expected_status = 400
            elif outcome == 'invalid_state':
                params[0] = ('state', 'wrong-state')
                expected_status = 401
            elif outcome == 'oversized':
                params += [('scope', 'x' * 9000)]
                expected_status = 400
            elif outcome == 'rate_limited':
                expected_status = 429
            result = client.get(path, params=params, headers={'Sec-Fetch-Site': 'cross-site'})
            assert result.status_code == expected_status, result.text
            assert len(observed) == 1
            raw_query, line = observed[0]
            assert raw_query == b''
            assert path + ' HTTP/1.1' in line and '?' not in line
            assert all(value not in line for value in (state, code, 'wrong-state', 'synthetic-private-error'))
            assert all(value not in result.text for value in (state, code, 'synthetic-private-error'))
            if outcome == 'success':
                assert result.json()['authenticated'] and COOKIE in client.cookies
            else:
                assert not w.state['calls']
    finally:
        if provider == 'github':
            w.github_http.close()


def test_session_check_retries_a_transient_storage_error_and_never_reports_sign_out(customer, monkeypatch):
    """QA 17: one storage error on /session sent a signed-in customer to the sign-in prompt."""
    import sqlite3
    w=customer;auth=login(w);app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core))
    original=w.core.session;calls=[]
    def flaky(token,failures=1):
        calls.append(token)
        if len(calls)<=failures:raise sqlite3.DatabaseError('statement_failed')
        return original(token)
    monkeypatch.setattr(w.core,'session',flaky)
    with TestClient(app,base_url='https://agentconcierge.biz') as client:
        client.cookies.set(COOKIE,auth['session_token'])
        assert client.get('/api/customer-auth/session').status_code==200 and len(calls)==2
        calls.clear();monkeypatch.setattr(w.core,'session',lambda token:flaky(token,failures=5))
        failed=client.get('/api/customer-auth/session')
        assert failed.status_code==503 and failed.headers['retry-after']=='2' and len(calls)==2


def test_session_slides_with_activity_and_stops_at_twelve_hours(customer, monkeypatch):
    """QA 18/19: sessions ended one hour after sign-in even while the customer kept working."""
    from agent_market import customer_identity as module
    w = customer; auth = login(w); start = time.time()
    token = auth['session_token']; other = login(w, 'c' * 64)['session_token']
    assert auth['expires'] - start <= module.SESSION_IDLE + 1 and auth['absolute_expires'] - start >= module.SESSION_MAX - 1
    clock = {'now': start}
    monkeypatch.setattr(module, '_time', lambda: clock['now'])
    for minutes in (50, 100, 150):  # active every 50 minutes: still signed in after 2.5 hours
        clock['now'] = start + minutes * 60
        w.core.actor(token)
    assert w.core.session(token)['expires'] == pytest.approx(clock['now'] + module.SESSION_IDLE)
    clock['now'] += module.SESSION_IDLE + 1  # an idle hour ends it
    with pytest.raises(WorkspaceDenied): w.core.actor(token)
    for step in range(1, 15):  # active every 50 minutes, yet never extended past 12 hours after sign-in
        clock['now'] = start + step * 3000
        w.core.actor(other)
    assert w.core.session(other)['expires'] <= start + module.SESSION_MAX + 5
    clock['now'] = start + module.SESSION_MAX + 10
    with pytest.raises(WorkspaceDenied): w.core.actor(other)


def test_extending_a_session_keeps_issued_app_tokens_valid(customer, monkeypatch):
    from agent_market import customer_identity as module
    w = customer; token = linked(w)['session_token']
    issued = w.core.issue_token(token, w.ws, 'read')
    start = time.time(); monkeypatch.setattr(module, '_time', lambda: start + 120)
    w.core.actor(token)  # moves the session expiry
    assert w.core.validate_token(issued['access_token'], w.ws, 'read')


def test_sliding_expiry_update_is_registered_for_postgresql():
    from agent_market import application_store_postgres as postgres
    assert postgres._normalized('UPDATE customer_sessions SET expires=? WHERE id=? AND revoked IS NULL') in postgres._STATEMENTS


def test_session_check_reads_without_the_writer_lock(customer, monkeypatch):
    """11-01: support pages failed with a lock timeout because every session check took the writer lock."""
    from contextlib import contextmanager
    from agent_market import customer_identity as module
    w = customer; token = login(w)['session_token']
    calls = []
    write_tx = w.core.tx

    @contextmanager
    def store_tx(readonly=False):
        calls.append('read' if readonly else 'store-write')
        with write_tx() as db:
            yield db

    @contextmanager
    def tracked_write():
        calls.append('write')
        with write_tx() as db:
            yield db
    monkeypatch.setattr(w.core.store, 'backend', 'postgresql', raising=False)
    monkeypatch.setattr(w.core.store, 'tx', store_tx, raising=False)
    monkeypatch.setattr(w.core, 'tx', tracked_write)
    start = time.time(); monkeypatch.setattr(module, '_time', lambda: start)
    w.core.actor(token)
    assert calls == ['read']  # fresh session: nothing to extend, no writer lock
    calls.clear(); monkeypatch.setattr(module, '_time', lambda: start + 120)
    w.core.actor(token)
    assert calls == ['read', 'write']  # the once-a-minute extension is the only write
    assert w.core.session(token)['expires'] == pytest.approx(start + 120 + module.SESSION_IDLE)


def test_customer_support_reads_use_read_only_transactions():
    import inspect
    from agent_market import workspace_admin_service
    source = inspect.getsource(workspace_admin_service)
    for name in ('support_options', 'sharing_options', 'listing', 'detail'):
        body = source.split('def ' + name + '(', 1)[1].split('\n        def ', 1)[0]
        assert 'core.identity.read_tx()' in body and 'core.identity.tx()' not in body, name
