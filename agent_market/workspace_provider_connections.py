"""Workspace-scoped provider credentials and conservative catalog auth profiles.

Catalog metadata is descriptive, never permission to dispatch a tool or pay a
provider. Credentials are bound to the selected endpoint and auth fingerprint.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

from .credential_vault import CredentialVault
from .workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid, _rows, _canonical
from .concierge.http_security import bounded_client, outbound_operation

NOTICE = 'workspace-provider-connection-v1'
MAX_CONNECTIONS = 50


class ConnectionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def obj(value):
    try:
        result = json.loads(value) if type(value) is str and len(value) <= 65536 else value
        return result if type(result) is dict else {}
    except (ValueError, TypeError):
        return {}


def public_https(value):
    """Syntax gate; the outbound transport independently pins public DNS answers."""
    if type(value) is not str or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None
                or p.fragment or p.query or p.port not in (None, 443) or not p.hostname.isascii()
                or p.hostname in ('localhost',) or p.hostname.endswith(('.localhost', '.local', '.internal'))):
            return None
        import ipaddress
        try:
            if not ipaddress.ip_address(p.hostname).is_global:
                return None
        except ValueError:
            if '.' not in p.hostname:
                return None
        return value
    except ValueError:
        return None


def origin(url):
    p = urlsplit(url)
    return p.scheme + '://' + p.netloc


def safe_header(value):
    return (type(value) is str and bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,63}', value))
            and (value.lower() in ('authorization', 'api-key', 'apikey', 'x-api-key', 'x-auth-token', 'ocp-apim-subscription-key')
                 or bool(re.fullmatch(r'x-[a-z0-9-]*(?:api-key|apikey|access-token|auth-token|subscription-key)',value.lower()))))


def profile(resource):
    info = obj(resource.get('auth_info'))
    method = resource.get('auth_method') or 'unknown'
    endpoint = public_https(resource.get('url'))
    declared = resource.get('auth_observed')
    if declared is None:
        declared = resource.get('auth_required', resource.get('auth_declared'))
    if method == 'unknown' and declared == 0:
        method = 'none'
    api = obj(info.get('api_key'))
    header = api.get('header') or ('Authorization' if method == 'bearer' else None)
    mode, reason = 'unsupported', 'This provider needs a documented authentication method before credentials can be collected.'
    if not endpoint:
        reason = 'This connection needs a public HTTPS endpoint without credentials or query parameters.'
    elif resource.get('kind') == 'x402':
        mode, reason = 'payment', 'This agent uses a payment protocol. An API key is not a payment authorization. Wallet secrets are never requested here.'
    elif method == 'none' and declared != 1:
        mode, reason = 'none', 'No provider sign-in is currently declared. Provider usage terms may still apply.'
    elif method in ('api_key', 'bearer') and safe_header(header):
        mode, reason = 'api_key', 'Get a limited API key from this provider, then paste it here. Do not paste it into workflow inputs or AI prompts.'
    elif method == 'oauth2':
        mode, reason = 'oauth', 'Authorize this agent in the provider’s own window. Your provider password is never collected here.'
    elif method == 'basic':
        reason = 'This provider uses username/password authentication. Use a provider-issued API credential or ask the provider for OAuth support; account passwords are not collected here.'
    elif api.get('query_param'):
        reason = 'This provider requires a key in the URL. URL credentials are not supported because they can appear in logs and browser history.'
    fingerprint = hashlib.sha256(_canonical({k: resource.get(k) for k in (
        'id', 'url', 'kind', 'auth_method', 'auth_info', 'auth_observed', 'auth_required', 'auth_declared')}).encode()).hexdigest()
    docs = []
    for url in (api.get('where_to_get', [])[:3] if isinstance(api.get('where_to_get'), list) else []):
        if public_https(url):
            docs.append(url)
    for url in (info.get('website'), obj(info.get('oauth')).get('documentation')):
        if public_https(url) and url not in docs:
            docs.append(url)
    return {'resource_id': resource['id'], 'name': str(resource.get('name') or 'Registered agent')[:160],
            'protocol': str(resource.get('kind') or 'unknown')[:20], 'endpoint': endpoint,
            'provider_host': urlsplit(endpoint).hostname if endpoint else 'Unavailable',
            'method': method, 'mode': mode, 'header': header if mode == 'api_key' else None,
            'reason': reason, 'fingerprint': fingerprint, 'documentation': docs[:3],
            'active': bool(resource.get('active')), 'auth_checked_at': resource.get('auth_checked_at'),
            'workflow_execution': 'Separate workflow capability and execution approval are required. Saving a connection does not enable paid execution.'}


class ProviderConnections:
    def __init__(self, access, http=None):
        self.access, self.store, self.http = access, access.store, http
        key = access.key.encode() if type(access.key) is str else access.key
        self.vault = CredentialVault.from_key(hmac.new(key, b'customer-provider-connections:v1', hashlib.sha256).digest())

    def _key(self, ws):
        return 'private:provider-connections:v1:' + ws

    def _load(self, db, ws):
        rows = _rows(db, 'SELECT value FROM meta WHERE key=?', (self._key(ws),))
        if not rows:
            return {'records': {}, 'flows': {}, 'versions': {}, 'revision': 0}
        try:
            data = json.loads(self.vault.open(self._key(ws), json.loads(rows[0]['value'])))
            data.setdefault('versions', {rid: record['revision'] for rid, record in data['records'].items()})
            return data
        except (ValueError, TypeError):
            raise ConnectionError('storage_unavailable') from None

    def _save(self, db, ws, data):
        data['revision'] += 1
        sealed = self.vault.seal(self._key(ws), _canonical(data))
        db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (self._key(ws), json.dumps(sealed)))

    def _authorize(self, ws, actor, manage=False):
        self.access._access(ws, actor, owner=manage, write=manage)
        if actor.token_ref is not None:
            raise WorkspaceDenied()

    def _resource(self, rid):
        if type(rid) is not int or not 0 < rid < 2**31:
            raise WorkspaceInvalid()
        result = self.store.resource(rid)
        if not result:
            raise ConnectionError('agent_unavailable')
        return result

    def _dto(self, record, resource):
        p = profile(resource)
        status = record['status']
        now = time.time()
        if not resource.get('active'):
            status = 'agent_unavailable'
        elif record['fingerprint'] != p['fingerprint']:
            status = 'reconnect_required'
        elif record.get('expires') and record['expires'] <= now:
            status = 'expired'
        reconnect = status in ('expired', 'reconnect_required', 'authentication_rejected')
        readiness = {'requires_reconnect': reconnect, 'authentication_checked': status == 'authentication_verified',
                     'expires_soon': bool(record.get('expires') and now < record['expires'] <= now + 300),
                     'automatic_refresh_supported': False, 'execution_authorized': False,
                     'next_action': 'agent_unavailable' if status == 'agent_unavailable' else
                         'reconnect' if reconnect else 'check_authentication' if status == 'saved_unverified' else 'review_execution'}
        return {'resource_id': record['resource_id'], 'name': p['name'], 'provider_host': p['provider_host'],
                'method': record['method'], 'status': status, 'updated': record['updated'],
                'expires': record.get('expires'), 'revision': record['revision'], 'has_credential': True,
                'workflow_execution': p['workflow_execution'], 'readiness': readiness}

    def listing(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self._authorize(ws, actor)
            data = self._load(db, ws)
            records = []
            for record in data['records'].values():
                resource = self.store.resource(record['resource_id'])
                if resource:
                    records.append(self._dto(record, resource))
                else:
                    records.append({k: record[k] for k in ('resource_id','method','updated','revision')} |
                                   {'name':'Unavailable agent', 'status':'agent_unavailable','provider_host':'Unavailable','has_credential':True})
            role = self.access._authorize(actor)['role']
            return {'connections': records, 'can_manage': role == 'owner', 'limit': MAX_CONNECTIONS}

    def search(self, ws, actor, query, after=0):
        if type(query) is not str or len(query) > 160 or type(after) is not int or after < 0:
            raise WorkspaceInvalid()
        query = query.strip()
        with self.access._tx(actor) as (db, _):
            self._authorize(ws, actor)
            if query.isdigit():
                resource = self.store.resource(int(query))
                rows = [resource] if resource else []
            else:
                needle = '%' + query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
                rows = _rows(db, "SELECT * FROM resources WHERE id>? AND (LOWER(name) LIKE LOWER(?) ESCAPE '\\' OR LOWER(url) LIKE LOWER(?) ESCAPE '\\') ORDER BY id LIMIT 21", (after, needle, needle))
            return {'agents': [profile(dict(r)) for r in rows[:20]], 'next_after': rows[19]['id'] if len(rows)>20 else None}

    def inspect(self, ws, actor, rid):
        with self.access._tx(actor) as (db, _):
            self._authorize(ws, actor)
            if type(rid) is not int or not 0 < rid < 2**31:
                raise WorkspaceInvalid()
            data = self._load(db,ws)
            record = data['records'].get(str(rid))
            resource = self.store.resource(rid)
            if resource is None and record is None:
                raise ConnectionError('agent_unavailable')
            resource = resource or {'id':rid,'name':'Unavailable agent','active':0}
            p = profile(resource)
            return {'agent':p,'revision':data['versions'].get(str(rid),0),'connection':self._dto(record,resource) if record else None,
                    'can_manage':self.access._authorize(actor)['role']=='owner'}

    def _consent(self, p, body):
        if body.get('authorized') is not True or body.get('notice') != NOTICE or body.get('fingerprint') != p['fingerprint']:
            raise ConnectionError('review_changed')
        if not p['active'] or not p['endpoint']:
            raise ConnectionError('agent_unavailable')

    def _request(self, method, url, **kwargs):
        if not public_https(url):
            raise ConnectionError('unsafe_endpoint')
        with outbound_operation(12):
            client = bounded_client(self.http, timeout=10, limit=262144)
            try:
                result = client.request(method,url,**kwargs)
                if 300 <= result.status_code < 400:
                    raise ConnectionError('redirect_refused')
                return result
            finally:
                client.close()

    @staticmethod
    def _secret(value):
        if type(value) is not str or not 8 <= len(value) <= 4096 or any(ord(c)<33 or ord(c)>126 for c in value):
            raise ConnectionError('invalid_key')
        return value

    def _persist(self, ws, actor, p, method, secret, status, expected, expires=None):
        with self.access._tx(actor, write=True) as (db, _):
            self._authorize(ws, actor, True)
            if profile(self._resource(p['resource_id']))['fingerprint'] != p['fingerprint']:
                raise ConnectionError('review_changed')
            data=self._load(db,ws);rid=str(p['resource_id']);old=data['records'].get(rid)
            if data['versions'].get(rid,0) != expected:
                raise WorkspaceConflict()
            if not old and len(data['records']) >= MAX_CONNECTIONS:
                raise ConnectionError('connection_limit')
            record={'resource_id':p['resource_id'],'fingerprint':p['fingerprint'],'method':method,
                    'secret':secret,'status':status,'expires':expires,'revision':expected+1,'updated':time.time()}
            data['records'][rid]=record
            data['versions'][rid]=record['revision']
            self._save(db,ws,data)
            self.access._audit(db,actor,ws,'provider_connection.save',revision=record['revision'])
            return self._dto(record,self._resource(p['resource_id']))

    def save_key(self,ws,actor,rid,body):
        if type(body) is not dict or set(body)!={'authorized','notice','fingerprint','revision','key'} or type(body['revision']) is not int or body['revision']<0:
            raise WorkspaceInvalid()
        with self.access._tx(actor) as (db,_):
            self._authorize(ws,actor,True);p=profile(self._resource(rid));self._consent(p,body)
        if p['mode']!='api_key':
            raise ConnectionError('unsupported_method')
        secret=self._secret(body['key'])
        return self._persist(ws,actor,p,'api_key',secret,'saved_unverified',body['revision'])

    def verify(self,ws,actor,rid,body):
        if type(body) is not dict or set(body)!={'authorized','notice','revision'} or body['authorized'] is not True or body['notice']!=NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor) as (db,_):
            self._authorize(ws,actor,True);resource=self._resource(rid);p=profile(resource)
            data=self._load(db,ws);record=data['records'].get(str(rid))
            if not record or record['revision']!=body['revision']:
                raise WorkspaceConflict()
            state=self._dto(record,resource)['status']
            if state in ('expired','reconnect_required'):
                raise ConnectionError(state)
            if p['protocol']!='mcp':
                raise ConnectionError('verification_unavailable')
            secret=record['secret'];header=p['header'] if record['method']=='api_key' else 'Authorization'
        from .collector.capabilities import HEADERS, INIT, parse_jsonrpc
        value=('Bearer '+secret) if header.lower()=='authorization' else secret
        try:
            baseline=self._request('POST',p['endpoint'],json=INIT,headers=HEADERS)
            if baseline.status_code not in (401,403):
                raise ConnectionError('verification_unavailable')
            response=self._request('POST',p['endpoint'],json=INIT,headers={**HEADERS,header:value})
            if response.status_code in (401,403):
                raise ConnectionError('key_rejected')
            data=parse_jsonrpc(response) or {}
            if (response.status_code!=200 or data.get('jsonrpc')!='2.0'
                    or type(data.get('id')) is not type(INIT['id']) or data.get('id')!=INIT['id']
                    or 'error' in data or not isinstance(data.get('result'),dict)
                    or not isinstance(data['result'].get('protocolVersion'),str)):
                raise ConnectionError('verification_failed')
        except ConnectionError as error:
            if error.code in ('key_rejected','verification_unavailable'):
                self._persist(ws,actor,p,record['method'],secret,
                              'authentication_rejected' if error.code=='key_rejected' else 'saved_unverified',
                              record['revision'],record.get('expires'))
            raise
        except Exception:
            raise ConnectionError('provider_unavailable') from None
        return self._persist(ws,actor,p,record['method'],secret,'authentication_verified',record['revision'],record.get('expires'))

    def disconnect(self,ws,actor,rid,body):
        if type(body) is not dict or set(body)!={'revision'} or type(body['revision']) is not int:
            raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            self._authorize(ws,actor,True);data=self._load(db,ws);record=data['records'].get(str(rid))
            if not record or record['revision']!=body['revision']:
                raise WorkspaceConflict()
            data['versions'][str(rid)]=record['revision']+1
            del data['records'][str(rid)]
            data['flows']={k:v for k,v in data['flows'].items() if v['resource_id']!=rid}
            self._save(db,ws,data);self.access._audit(db,actor,ws,'provider_connection.disconnect')
            return {'disconnected':True,'provider_revocation_required':True}

    def oauth_metadata(self,ws,actor,rid):
        with self.access._tx(actor) as (db,_):
            self._authorize(ws,actor,True);resource=self._resource(rid);p=profile(resource)
            if p['mode']!='oauth' or not p['active']:
                raise ConnectionError('unsupported_method')
            hint=obj(obj(resource.get('auth_info')).get('oauth'))
        from .collector.auth_discovery import well_known
        endpoint=p['endpoint'];prm=None
        urls=well_known(endpoint,'oauth-protected-resource')
        if public_https(hint.get('protected_resource_metadata')) and origin(hint['protected_resource_metadata'])==origin(endpoint):
            urls.insert(0,hint['protected_resource_metadata'])
        try:
            with outbound_operation(20):
                for url in list(dict.fromkeys(urls))[:3]:
                    response=self._request('GET',url,headers={'Accept':'application/json'})
                    candidate=obj(response.json()) if response.status_code==200 else {}
                    if candidate.get('resource')==endpoint and isinstance(candidate.get('authorization_servers'),list):
                        prm=candidate;break
                if prm is None:
                    raise ConnectionError('oauth_setup_required')
                issuers=[u for u in prm['authorization_servers'][:3] if public_https(u)]
                if not issuers:
                    raise ConnectionError('oauth_setup_required')
                issuer=issuers[0];metadata=None
                for url in (well_known(issuer,'oauth-authorization-server')+well_known(issuer,'openid-configuration'))[:4]:
                    response=self._request('GET',url,headers={'Accept':'application/json'})
                    candidate=obj(response.json()) if response.status_code==200 else {}
                    if candidate.get('issuer')==issuer:
                        metadata=candidate;break
                if (not metadata or 'S256' not in metadata.get('code_challenge_methods_supported',[])
                        or 'authorization_code' not in metadata.get('grant_types_supported',['authorization_code'])
                        or not all(public_https(metadata.get(k)) for k in ('authorization_endpoint','token_endpoint'))):
                    raise ConnectionError('oauth_setup_required')
                scopes=prm.get('scopes_supported',[])
                if type(scopes) is not list or len(scopes)>50 or any(type(s) is not str or not re.fullmatch(r'[!#-\[\]-~]{1,120}',s) for s in scopes):
                    raise ConnectionError('oauth_setup_required')
                result={'issuer':issuer,'authorization_endpoint':metadata['authorization_endpoint'],'token_endpoint':metadata['token_endpoint'],
                        'registration_endpoint':public_https(metadata.get('registration_endpoint')),
                        'client_id_metadata_document_supported':metadata.get('client_id_metadata_document_supported') is True,
                        'issuer_parameter_supported':metadata.get('authorization_response_iss_parameter_supported') is True,
                        'resource':endpoint,'scopes':scopes,'fingerprint':p['fingerprint']}
                result['metadata_hash']=hashlib.sha256(_canonical(result).encode()).hexdigest()
                return result
        except ConnectionError:
            raise
        except Exception:
            raise ConnectionError('provider_unavailable') from None

    def begin_oauth(self,ws,actor,rid,body,public_origin):
        if type(body) is not dict or set(body)!={'authorized','notice','fingerprint','revision','metadata_hash','scopes','client_id'}:
            raise WorkspaceInvalid()
        if (type(body['revision']) is not int or body['revision']<0 or type(body['client_id']) is not str
                or len(body['client_id'])>256 or any(ord(c)<33 or ord(c)>126 for c in body['client_id'])
                or type(body['scopes']) is not list):
            raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            self._authorize(ws,actor,True);p=profile(self._resource(rid));self._consent(p,body)
            data=self._load(db,ws);now=time.time()
            data['flows']={k:v for k,v in data['flows'].items() if v['expires']>now}
            if len(data['flows'])>=3:
                raise ConnectionError('oauth_pending_limit')
            state=ws+'.'+secrets.token_urlsafe(32);state_key=hashlib.sha256(state.encode()).hexdigest()
            flow={'resource_id':rid,'expires':now+600,'session':actor.session_ref,'customer':actor.customer_id,
                  'fingerprint':p['fingerprint'],'revision':body['revision'],'ready':False}
            data['flows'][state_key]=flow;self._save(db,ws,data)
        try:
            metadata=self.oauth_metadata(ws,actor,rid)
            if metadata['metadata_hash']!=body['metadata_hash'] or not set(body['scopes'])<=set(metadata['scopes']):
                raise ConnectionError('review_changed')
            callback=public_origin+'/api/customer-provider-oauth/'+str(rid)+'/callback'
            client_id=body['client_id']
            if not client_id and metadata['client_id_metadata_document_supported']:
                client_id=public_origin+'/api/customer-provider-oauth/clients/'+str(rid)+'.json'
            if not client_id and metadata['registration_endpoint']:
                response=self._request('POST',metadata['registration_endpoint'],json={
                    'client_name':'Agent Concierge','redirect_uris':[callback],
                    'grant_types':['authorization_code'],'response_types':['code'],'token_endpoint_auth_method':'none'})
                registration=obj(response.json())
                client_id=registration.get('client_id')
                if (response.status_code not in (200,201) or registration.get('client_secret')
                        or registration.get('token_endpoint_auth_method','none')!='none'
                        or registration.get('redirect_uris')!=[callback]):
                    raise ConnectionError('oauth_setup_required')
            if not client_id:
                raise ConnectionError('oauth_client_required')
            if type(client_id) is not str or not 1<=len(client_id)<=2048 or any(ord(c)<33 or ord(c)>126 for c in client_id):
                raise ConnectionError('oauth_setup_required')
            verifier=secrets.token_urlsafe(48)
            flow.update(ready=True,metadata=metadata,client_id=client_id,callback=callback,verifier=verifier,scopes=body['scopes'])
            with self.access._tx(actor,write=True) as (db,_):
                self._authorize(ws,actor,True);data=self._load(db,ws)
                if state_key not in data['flows'] or profile(self._resource(rid))['fingerprint']!=p['fingerprint']:
                    raise ConnectionError('review_changed')
                data['flows'][state_key]=flow;self._save(db,ws,data)
            params={'response_type':'code','client_id':client_id,'redirect_uri':callback,'state':state,
                    'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),
                    'code_challenge_method':'S256','resource':metadata['resource']}
            if body['scopes']:
                params['scope']=' '.join(body['scopes'])
            return {'authorization_url':metadata['authorization_endpoint']+'?'+urlencode(params),'expires':flow['expires']}
        except Exception as error:
            with self.access._tx(actor,write=True) as (db,_):
                data=self._load(db,ws);data['flows'].pop(state_key,None);self._save(db,ws,data)
            if isinstance(error,(ConnectionError,WorkspaceDenied,WorkspaceConflict,WorkspaceInvalid)):
                raise
            raise ConnectionError('provider_unavailable') from None

    def complete_oauth(self,ws,actor,rid,query):
        state=query.get('state','')
        if not re.fullmatch(r'ws_[0-9a-f]{32}\.[A-Za-z0-9_-]{43}',state) or not state.startswith(ws+'.'):
            raise ConnectionError('oauth_invalid')
        key=hashlib.sha256(state.encode()).hexdigest()
        with self.access._tx(actor,write=True) as (db,_):
            self._authorize(ws,actor,True);data=self._load(db,ws);flow=data['flows'].get(key)
            if (not flow or not flow['ready'] or flow['session']!=actor.session_ref or flow['customer']!=actor.customer_id
                    or flow['resource_id']!=rid or flow['expires']<=time.time()):
                raise ConnectionError('oauth_invalid')
            del data['flows'][key];self._save(db,ws,data)
        metadata=flow['metadata']
        if query.get('iss')!=metadata['issuer'] and ('iss' in query or metadata['issuer_parameter_supported']):
            raise ConnectionError('oauth_invalid')
        if 'error' in query:
            raise ConnectionError('oauth_cancelled')
        code=query.get('code')
        if type(code) is not str or not 1<=len(code)<=2048 or any(ord(c)<33 or ord(c)>126 for c in code):
            raise ConnectionError('oauth_invalid')
        with self.access._tx(actor) as (db,_):
            self._authorize(ws,actor,True);p=profile(self._resource(rid))
            if p['fingerprint']!=flow['fingerprint']:
                raise ConnectionError('review_changed')
        try:
            response=self._request('POST',metadata['token_endpoint'],data={
                'grant_type':'authorization_code','code':code,'client_id':flow['client_id'],
                'redirect_uri':flow['callback'],'code_verifier':flow['verifier'],'resource':metadata['resource']})
            token=obj(response.json())
            if response.status_code!=200 or str(token.get('token_type','')).lower()!='bearer':
                raise ConnectionError('oauth_failed')
            access_token=self._secret(token.get('access_token'))
            expiry=token.get('expires_in',3600)
            if type(expiry) is not int or not 0<expiry<=2592000:
                raise ConnectionError('oauth_failed')
            if 'scope' in token and (type(token['scope']) is not str or not set(token['scope'].split())<=set(flow['scopes'])):
                raise ConnectionError('oauth_scope_changed')
            return self._persist(ws,actor,p,'oauth',''+access_token,'oauth_authorized',flow['revision'],time.time()+expiry)
        except (ConnectionError,WorkspaceDenied,WorkspaceConflict):
            raise
        except Exception:
            raise ConnectionError('oauth_failed') from None
