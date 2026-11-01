"""Opt-in pinned Ed25519 Web Bot Auth for read-quota identity, never workspace access.

This deliberately supports a bounded RFC 9421 profile, not arbitrary signature
algorithms or remote key URLs. Anonymous access retains its ordinary limits.
"""
import base64
from contextvars import ContextVar
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.datastructures import Headers, MutableHeaders

VERIFIED_READER=ContextVar('verified_public_reader',default=None)
LABEL=r'[a-z][a-z0-9_-]{0,30}'
INPUT=re.compile(r'('+LABEL+r')=(\((?:"[@a-z][@a-z0-9_-]*" ?){1,12}\))((?:;[a-z]+=(?:"[A-Za-z0-9_./:+ =-]{1,200}"|[0-9]{1,12})){3,8})\Z')
PARAM=re.compile(r';([a-z]+)=("[^"]*"|[0-9]+)')
AGENT=re.compile(r'(?:(?:'+LABEL+r')=)?"(https://[A-Za-z0-9.:-]+)"\Z')


def b64url(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')


def thumbprint(jwk):
    value={key:jwk[key] for key in ('crv','kty','x')}
    return b64url(hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).digest())


def trusted_keys_from_environment():
    path=os.environ.get('WEB_BOT_TRUST_FILE')
    if not path:return {}
    from ..application_runtime import _private_bytes
    value=json.loads(_private_bytes(path,65536))
    if not isinstance(value,dict) or len(value)>32:raise ValueError('Invalid Web Bot Auth trust profile')
    for origin,keys in value.items():
        parsed=urlsplit(origin)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('Trust entries must use explicit HTTPS origins')
        if not isinstance(keys,list) or not 1<=len(keys)<=8:raise ValueError('Invalid pinned key list')
        for key in keys:
            if key.get('kty')!='OKP' or key.get('crv')!='Ed25519' or 'd' in key:raise ValueError('Pin only public Ed25519 keys')
            if len(base64.urlsafe_b64decode(key['x']+'='*((-len(key['x']))%4)))!=32:raise ValueError('Invalid Ed25519 key')
    return value


def reserve_nonce(key,ttl):
    from ..infra.redis_hub import RedisHub
    hub=RedisHub.get_instance()
    try:
        client,_,_=hub._operation()
        return bool(client and client.set('a2a:webbot:'+key,'1',ex=max(1,int(ttl)),nx=True))
    except Exception:return False


class Verifier:
    def __init__(self,origin,keys,*,clock=time.time,replay=reserve_nonce):
        self.origin,self.keys,self.clock,self.replay=origin.rstrip('/'),keys,clock,replay

    def verify(self,scope):
        headers=Headers(scope=scope)
        if any(len(headers.getlist(name))!=1 for name in ('signature-agent','signature-input','signature')):return None
        agent=headers['signature-agent'];value=headers['signature-input'];signature=headers['signature']
        if max(map(len,(agent,value,signature)))>4096:return None
        found=AGENT.fullmatch(agent);parsed=INPUT.fullmatch(value)
        if not found or not parsed:return None
        origin=found[1];keys=self.keys.get(origin,[])
        if not keys:return None
        label,components,parameters=parsed.groups();names=re.findall(r'"([^"]+)"',components)
        if len(set(names))!=len(names) or not {'@authority','signature-agent'}<=set(names):return None
        params={}
        for match in PARAM.finditer(parameters):
            key,raw=match.groups()
            if key in params:return None
            params[key]=raw[1:-1] if raw.startswith('"') else int(raw)
        if set(params)-{'created','expires','keyid','alg','nonce','tag'}:return None
        now=self.clock();created=params.get('created');expires=params.get('expires')
        if type(created)is not int or type(expires)is not int or not now-300<=created<=now+30 or not now<expires<=created+300:return None
        if params.get('tag')!='web-bot-auth' or params.get('alg','ed25519')!='ed25519':return None
        nonce=params.get('nonce');kid=params.get('keyid')
        if not isinstance(nonce,str) or not 16<=len(nonce)<=128 or not isinstance(kid,str):return None
        matched=re.fullmatch(re.escape(label)+r'=:([A-Za-z0-9+/]+={0,2}):',signature)
        if not matched:return None
        try:
            proof=base64.b64decode(matched[1],validate=True)
            if len(proof)!=64:return None
            key=next((key for key in keys if thumbprint(key)==kid),None)
            if key is None:return None
            raw=base64.urlsafe_b64decode(key['x']+'='*((-len(key['x']))%4));public=Ed25519PublicKey.from_public_bytes(raw)
            path=scope.get('raw_path',scope['path'].encode()).decode('ascii');query=scope.get('query_string',b'').decode('ascii')
            authority=urlsplit(self.origin).netloc
            derived={'@authority':authority,'@method':scope['method'],'@path':path,'@query':'?'+query,
                     '@target-uri':self.origin+path+('?' +query if query else '')}
            lines=[]
            for name in names:
                if name in derived:content=derived[name]
                elif name in ('signature-agent','user-agent') and len(headers.getlist(name))==1:content=headers[name].strip()
                else:return None
                if not content.isascii() or '\n' in content or '\r' in content:return None
                lines.append('"'+name+'": '+content)
            lines.append('"@signature-params": '+components+parameters)
            public.verify(proof,'\n'.join(lines).encode('ascii'))
        except Exception:return None
        replay_key=hashlib.sha256((origin+'\n'+kid+'\n'+nonce).encode()).hexdigest()
        if not self.replay(replay_key,expires-now+30):return None
        return {'key':hashlib.sha256((origin+'\n'+kid).encode()).hexdigest()[:32],'multiplier':2}


class WebBotAuth:
    def __init__(self,app,*,origin,keys=None,verifier=None):
        self.app=app;self.verifier=verifier or Verifier(origin,trusted_keys_from_environment() if keys is None else keys)
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        identity=self.verifier.verify(scope) if scope['method'] in ('GET','HEAD') and self.verifier.keys else None
        token=VERIFIED_READER.set(identity)
        async def deliver(message):
            if identity and message['type']=='http.response.start':
                headers=MutableHeaders(scope=message);headers['Web-Bot-Auth']='verified';headers['Cache-Control']='no-store'
            await send(message)
        try:await self.app(scope,receive,deliver)
        finally:VERIFIED_READER.reset(token)
