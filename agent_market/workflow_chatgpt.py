"""Private, account-authorized ChatGPT plan inference; never pooled for visitors.

This local evaluation adapter uses the documented public OAuth/Responses route.
It is not activated by website startup. Hosted client approval and per-customer
credential isolation are prerequisites for any public deployment.
"""
import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import hmac
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .customer_identity import _decode, _object
from .workspace_access import WorkspaceDenied, WorkspaceInvalid, _canonical
from .workflow_model_proposer import OllamaGraphProposer, SYSTEM
from .workspace_ai_support import strict_json

AUTH = 'https://auth.openai.com'
API = 'https://api.openai.com/v1'
MODEL = 'gpt-6.1-sol'
SCOPES = frozenset('openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'.split())


class ChatGPTRequestDenied(WorkspaceDenied):
    """Safe local diagnostics without provider messages or credential contents."""
    def __init__(self, stage, status):
        super().__init__()
        self.stage = stage
        self.http_status = status


class ChatGPTStreamRejected(WorkspaceInvalid):
    """Expose a bounded provider error code without its untrusted message."""
    def __init__(self, event):
        super().__init__()
        self.event_type=event['type']
        response=event.get('response')
        error=response.get('error') if type(response) is dict else event.get('error')
        code=error.get('code') if type(error) is dict else event.get('code')
        self.error_code=code if type(code) is str and re.fullmatch(r'[a-zA-Z0-9_]{1,100}',code) else 'provider_error'
        param=error.get('param') if type(error) is dict else event.get('param')
        roots={'model','instructions','input','reasoning','store','stream','tools','service_tier','temperature','max_output_tokens'}
        self.error_param=(param if type(param) is str and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,80}',param)
                          and re.split(r'[.\[]',param,1)[0] in roots else None)


def private_read(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WorkspaceDenied()
        raw = stream.read(131073)
    if len(raw) > 131072:
        raise WorkspaceDenied()
    return _object(raw)


def private_write(path, value):
    path = Path(path); path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise WorkspaceDenied()
    if path.is_symlink():
        raise WorkspaceDenied()
    temp = path.with_name('.' + path.name + '.' + secrets.token_hex(8))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_canonical(value).encode('ascii')); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()


@contextmanager
def credential_lock(path):
    fd = os.open(str(path) + '.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WorkspaceDenied()
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def catalog_object(raw):
    """Project only bounded catalog identity fields, never model prompt metadata."""
    try:
        value = strict_json(raw)
        if type(value) is not dict or type(value.get('models')) is not list or not 1 <= len(value['models']) <= 100:
            raise WorkspaceDenied()
        models=[]; seen=set()
        for item in value['models']:
            if type(item) is not dict:
                raise WorkspaceDenied()
            slug=item.get('slug'); visibility=item.get('visibility')
            if (type(slug) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}',slug)
                    or slug in seen or type(visibility) is not str or len(visibility)>32):
                raise WorkspaceDenied()
            seen.add(slug); models.append({'slug':slug,'visibility':visibility})
        return {'models':models}
    except (ValueError, TypeError, RecursionError, WorkspaceInvalid):
        raise WorkspaceDenied() from None


def bounded_json(client, method, url, *, limit=524288, **kwargs):
    if url not in (AUTH+'/.well-known/jwks.json', AUTH+'/api/accounts/oauth/token', API+'/models'):
        raise WorkspaceDenied()
    catalog = url == API+'/models'
    limit = 2097152 if catalog else limit
    parts=[]; size=0; started=time.monotonic()
    with client.stream(method, url, timeout=10, follow_redirects=False, **kwargs) as response:
        if response.status_code != 200:
            stage = 'catalog' if url == API+'/models' else 'identity'
            raise ChatGPTRequestDenied(stage, response.status_code)
        if response.headers.get('content-type','').split(';')[0] != 'application/json':
            raise WorkspaceDenied()
        for chunk in response.iter_bytes(4096):
            size += len(chunk)
            if size > limit or time.monotonic()-started > 10: raise WorkspaceDenied()
            parts.append(chunk)
    raw=b''.join(parts)
    return catalog_object(raw) if catalog else _object(raw)


def verify_identity(client, token, client_id, *, nonce=None):
    if type(token) is not str or len(token)>24000 or token.count('.')!=2:
        raise WorkspaceDenied()
    header_part, claims_part, signature_part = token.split('.')
    header, claims = _object(_decode(header_part)), _object(_decode(claims_part))
    if (header.get('alg')!='RS256' or type(header.get('kid')) is not str
            or set(header)-{'alg','kid','typ'} or header.get('typ','JWT')!='JWT'):
        raise WorkspaceDenied()
    keys = bounded_json(client,'GET',AUTH+'/.well-known/jwks.json').get('keys')
    if type(keys) is not list or not 1 <= len(keys) <= 32: raise WorkspaceDenied()
    matches=[key for key in keys if type(key) is dict and key.get('kid')==header['kid']]
    if len(matches)!=1: raise WorkspaceDenied()
    key=matches[0]
    try:
        if (key.get('kty')!='RSA' or key.get('use','sig')!='sig' or key.get('alg','RS256')!='RS256'
                or 'key_ops' in key and key['key_ops']!=['verify']
                or set(key)&{'d','p','q','dp','dq','qi','oth'}): raise WorkspaceDenied()
        modulus=int.from_bytes(_decode(key['n'],1400),'big'); exponent=int.from_bytes(_decode(key['e'],16),'big')
        if not 2048 <= modulus.bit_length() <= 8192 or exponent!=65537: raise WorkspaceDenied()
        rsa.RSAPublicNumbers(exponent,modulus).public_key().verify(_decode(signature_part,1400),
            (header_part+'.'+claims_part).encode('ascii'),padding.PKCS1v15(),hashes.SHA256())
    except Exception:
        raise WorkspaceDenied() from None
    audience=claims.get('aud'); audience=[audience] if type(audience) is str else audience
    now=time.time()
    if (claims.get('iss')!=AUTH or type(audience) is not list or client_id not in audience
            or len(audience)>10 or any(type(item) is not str for item in audience)
            or len(audience)!=len(set(audience))
            or (len(audience)>1 or 'azp' in claims) and claims.get('azp')!=client_id
            or nonce is not None and claims.get('nonce')!=nonce
            or type(claims.get('sub')) is not str or not 1 <= len(claims['sub']) <= 255):
        raise WorkspaceDenied()
    for name in ('iat','exp'):
        if type(claims.get(name)) not in (int,float) or not math.isfinite(claims[name]): raise WorkspaceDenied()
    if not 0 <= claims['iat'] <= now+5 or not now < claims['exp'] <= claims['iat']+86400:
        raise WorkspaceDenied()
    if 'nbf' in claims and (type(claims['nbf']) not in (int,float) or not math.isfinite(claims['nbf']) or claims['nbf']>now+5):
        raise WorkspaceDenied()
    return claims


def token_record(tokens, claims, client_id, host_id):
    if type(tokens.get('token_type')) is not str or tokens['token_type'].lower()!='bearer': raise WorkspaceDenied()
    scopes=tokens.get('scope','')
    if type(scopes) is not str or not {'openid','resource.invoke','chatgpt.tokens.use.direct'}.issubset(scopes.split()):
        raise WorkspaceDenied()
    for name in ('access_token','refresh_token','id_token'):
        if type(tokens.get(name)) is not str or not 1 <= len(tokens[name]) <= 24000 or any(ord(c)<33 or ord(c)>126 for c in tokens[name]):
            raise WorkspaceDenied()
    ttl=tokens.get('expires_in')
    if type(ttl) not in (int,float) or not math.isfinite(ttl) or not 0 < ttl <= 7200: raise WorkspaceDenied()
    return {'profile':'workflow-chatgpt-local-v1','issuer':AUTH,'subject':claims['sub'],
        'email':claims.get('email'),'client_id':client_id,'ext_agent_host_id':host_id,
        'scopes':sorted(set(scopes.split())),'expires_at':time.time()+ttl,
        **{name:tokens[name] for name in ('access_token','refresh_token','id_token')}}


@dataclass(repr=False)
class LoginAttempt:
    redirect_uri: str
    host_id: str
    client_id: str = 'dynamic_agent_client'
    expected_email: str | None = field(default=None,repr=False)
    expected_subject: str | None = field(default=None,repr=False)
    state: str = field(default_factory=lambda:secrets.token_urlsafe(32),repr=False)
    nonce: str = field(default_factory=lambda:secrets.token_urlsafe(32),repr=False)
    verifier: str = field(default_factory=lambda:secrets.token_urlsafe(48),repr=False)
    created: float = field(default_factory=time.time)
    consumed: bool = False

    def authorization_url(self):
        if (not re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}/auth/callback',self.redirect_uri)
                or int(self.redirect_uri.split(':')[2].split('/')[0])>65535
                or not re.fullmatch(r'urn:uuid:[0-9a-f-]{36}',self.host_id)
                or type(self.client_id) is not str
                or self.client_id != 'dynamic_agent_client'
                    and not re.fullmatch(r'oaiapp_[A-Za-z0-9_-]{1,200}',self.client_id)):
            raise WorkspaceDenied()
        args={'client_id':self.client_id,'ext_agent_host_id':self.host_id,'response_type':'code',
            'redirect_uri':self.redirect_uri,'scope':' '.join(sorted(SCOPES)),'resource':API,
            'state':self.state,'nonce':self.nonce,'code_challenge_method':'S256',
            'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')}
        if self.client_id=='dynamic_agent_client':args['agent_name_hint']='Agent Concierge'
        return AUTH+'/api/accounts/authorize?'+urlencode(args)

    def complete(self, client, query):
        if self.consumed or time.time()-self.created>300 or type(query.get('state')) is not str or not hmac.compare_digest(query['state'],self.state):
            raise WorkspaceDenied()
        self.consumed=True
        if query.get('error') or type(query.get('code')) is not str or not 1 <= len(query['code']) <= 4096: raise WorkspaceDenied()
        issued=query.get('client_id',self.client_id)
        if (type(issued) is not str or not re.fullmatch(r'oaiapp_[A-Za-z0-9_-]{1,200}',issued)
                or self.client_id!='dynamic_agent_client' and issued!=self.client_id): raise WorkspaceDenied()
        tokens=bounded_json(client,'POST',AUTH+'/api/accounts/oauth/token',data={
            'grant_type':'authorization_code','client_id':issued,'code':query['code'],
            'code_verifier':self.verifier,'redirect_uri':self.redirect_uri,'resource':API})
        claims=verify_identity(client,tokens.get('id_token'),issued,nonce=self.nonce)
        if self.expected_email is not None and (type(claims.get('email')) is not str or claims['email'].casefold()!=self.expected_email.casefold()):
            raise WorkspaceDenied()
        if self.expected_subject is not None and claims['sub'] != self.expected_subject:
            raise WorkspaceDenied()
        return token_record(tokens,claims,issued,self.host_id)


def credentials(client,path):
    with credential_lock(path):
        value=private_read(path)
        if (value.get('profile')!='workflow-chatgpt-local-v1' or value.get('issuer')!=AUTH
                or type(value.get('scopes')) is not list
                or any(type(scope) is not str for scope in value['scopes'])
                or not {'openid','resource.invoke','chatgpt.tokens.use.direct'}.issubset(value['scopes'])
                or type(value.get('expires_at')) not in (int,float)
                or not math.isfinite(value['expires_at'])
                or type(value.get('client_id')) is not str
                or not re.fullmatch(r'oaiapp_[A-Za-z0-9_-]{1,200}',value['client_id'])
                or type(value.get('subject')) is not str or not 1 <= len(value['subject']) <= 255
                or type(value.get('ext_agent_host_id')) is not str
                or not re.fullmatch(r'urn:uuid:[0-9a-f-]{36}',value['ext_agent_host_id'])):
            raise WorkspaceDenied()
        for name in ('access_token','refresh_token','id_token'):
            secret=value.get(name)
            if type(secret) is not str or not 1 <= len(secret) <= 24000 or any(ord(c)<33 or ord(c)>126 for c in secret):
                raise WorkspaceDenied()
        if value['expires_at']<=time.time()+60:
            tokens=bounded_json(client,'POST',AUTH+'/api/accounts/oauth/token',data={
                'grant_type':'refresh_token','client_id':value['client_id'],'refresh_token':value['refresh_token'],'resource':API})
            claims=verify_identity(client,tokens.get('id_token'),value['client_id'])
            if claims['sub']!=value['subject']:raise WorkspaceDenied()
            value=token_record(tokens,claims,value['client_id'],value['ext_agent_host_id'])
            private_write(path,value)
        return value


@dataclass(frozen=True,repr=False)
class ChatGPTGraphProposer:
    credential_path: str
    http: object = field(default=None,repr=False)
    model: str = MODEL
    reasoning_effort: str = 'medium'
    expected_email: str | None = field(default=None,repr=False)

    def __post_init__(self):
        if (self.model not in ('gpt-6.1-sol','gpt-6-astra','gpt-6-sol','gpt-6-luna',
                              'gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna')
                or self.reasoning_effort not in ('low','medium','high','xhigh','max')
                or self.expected_email is not None and (type(self.expected_email) is not str
                    or not 3 <= len(self.expected_email) <= 254 or '@' not in self.expected_email)):
            raise WorkspaceInvalid()

    def __call__(self,envelope):return self.propose(envelope)

    def propose(self,envelope,*,_guard=None):
        context=OllamaGraphProposer._public_context(envelope)
        owned=self.http is None
        client=self.http if not owned else httpx.Client(trust_env=False,follow_redirects=False)
        try:
            if _guard:_guard()
            stage='credentials'
            account=credentials(client,self.credential_path)
            if self.expected_email is not None and (type(account.get('email')) is not str
                    or account['email'].casefold()!=self.expected_email.casefold()):
                raise WorkspaceDenied()
            headers={'Authorization':'Bearer '+account['access_token'],'Accept-Encoding':'identity'}
            stage='catalog'
            catalog=bounded_json(client,'GET',API+'/models',headers=headers)
            stage='model_access'
            models=catalog.get('models')
            if type(models) is not list or not any(item.get('slug')==self.model and item.get('visibility')=='list' for item in models if type(item) is dict):
                raise WorkspaceDenied()
            if _guard:_guard()
            request={'model':self.model,'instructions':SYSTEM,'input':[{'role':'user','content':_canonical(context)}],
                     'reasoning':{'effort':self.reasoning_effort},'store':False,'stream':True}
            started=time.monotonic(); size=0; buffer=b''; deltas=''; completed=None; finished_items={}
            stage='inference'
            with client.stream('POST',API+'/responses',json=request,headers=headers,timeout=45,follow_redirects=False) as response:
                if response.status_code!=200:
                    raise ChatGPTRequestDenied('inference', response.status_code)
                media=response.headers.get('content-type','').split(';')[0].strip().lower()
                if media and media!='text/event-stream':raise WorkspaceDenied()
                stage='response_stream'
                for chunk in response.iter_bytes(4096):
                    size+=len(chunk);buffer+=chunk
                    if size>262144 or len(buffer)>65536 or time.monotonic()-started>50:raise WorkspaceInvalid()
                    if _guard:_guard()
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        line=line.rstrip(b'\r')
                        if not line or line.startswith((b':',b'event:',b'id:',b'retry:')):continue
                        if not line.startswith(b'data:'):raise WorkspaceInvalid()
                        data=line[5:].strip()
                        if data==b'[DONE]':continue
                        event=strict_json(data)
                        if type(event) is not dict:raise WorkspaceInvalid()
                        if event.get('type') in ('error','response.failed','response.incomplete'):raise ChatGPTStreamRejected(event)
                        if event.get('type')=='response.output_item.done':
                            index=event.get('output_index');item=event.get('item')
                            if (completed is not None or type(index) is not int or not 0<=index<16
                                    or index in finished_items or type(item) is not dict
                                    or item.get('type') not in ('message','reasoning')):raise WorkspaceInvalid()
                            if item.get('type')=='message' and (item.get('status')!='completed'
                                    or item.get('role')!='assistant'):raise WorkspaceInvalid()
                            finished_items[index]=item
                        if event.get('type')=='response.output_text.delta':
                            delta=event.get('delta')
                            if completed is not None or type(delta) is not str:raise WorkspaceInvalid()
                            deltas+=delta
                            if len(deltas.encode())>16384:raise WorkspaceInvalid()
                        if event.get('type')=='response.completed':
                            if completed is not None:raise WorkspaceInvalid()
                            completed=event.get('response')
            if (buffer.strip() or type(completed) is not dict or completed.get('status')!='completed' or completed.get('model')!=self.model):
                raise WorkspaceInvalid()
            def output_text(items):
                if type(items) is not list or len(items)>16:raise WorkspaceInvalid()
                text='';messages=0
                for item in items:
                    if type(item) is not dict:raise WorkspaceInvalid()
                    if item.get('type')=='reasoning':continue
                    if (item.get('type')!='message' or item.get('role','assistant')!='assistant'
                            or item.get('status','completed')!='completed'):raise WorkspaceInvalid()
                    messages+=1
                    if type(item.get('content')) is not list:raise WorkspaceInvalid()
                    for content in item['content']:
                        if (type(content) is not dict or content.get('type')!='output_text'
                                or type(content.get('text')) is not str):raise WorkspaceInvalid()
                        text+=content['text']
                if messages!=1:raise WorkspaceInvalid()
                return text
            output=completed.get('output',[])
            if type(output) is not list:raise WorkspaceInvalid()
            # Some plan streams retain output only in completed item events.
            # Require final response success and exact text agreement, never a
            # delta-only recovery from an interrupted or failed response.
            finished=[finished_items[index] for index in sorted(finished_items)]
            text=output_text(output if output else finished)
            if output and finished and output_text(finished)!=text:raise WorkspaceInvalid()
            if not text or len(text.encode())>16384 or deltas and text!=deltas:raise WorkspaceInvalid()
            from .workspace_typed_flows import TypedFlows
            result=TypedFlows._definition(None,strict_json(text))
            if not 2 <= len(result['nodes']) <= 10:raise WorkspaceInvalid()
            if any(type(node['resource_id']) is not int or {'resource_id':node['resource_id'],'contract_id':node['contract_id']} not in context['candidates'] for node in result['nodes']):
                raise WorkspaceInvalid()
            if _guard:_guard()
            return result
        except ChatGPTRequestDenied:raise
        except WorkspaceDenied:raise ChatGPTRequestDenied(stage,None) from None
        except WorkspaceInvalid:raise
        except Exception:raise WorkspaceInvalid() from None
        finally:
            if owned:client.close()
