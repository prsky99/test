"""Loopback-only HTTPS webhook/A2A receiver for controlled notification tests."""
import argparse
import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import tempfile
import threading
import time
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect
import uvicorn

MAX_BODY = 65536
MAX_RECORDS = 100


class Inbox:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.registrations = {}
        self.events = OrderedDict()
        self.lock = threading.RLock()

    def receive(self, path, payload, raw, headers):
        if not isinstance(payload, dict):
            raise HTTPException(400, 'Invalid notification.')
        now = time.time()
        with self.lock:
            self.registrations = {k:v for k,v in self.registrations.items() if v['created'] > now-86400}
            if payload.get('type') == 'task_verification':
                data = payload.get('data')
                if not isinstance(data, dict):
                    raise HTTPException(400, 'Invalid challenge.')
                wid, code, key = (data.get(k) for k in ('watch_id','verification_code','signing_secret'))
                if not isinstance(wid,str) or not re.fullmatch(r'tw_[0-9a-f]{32}',wid) or not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code) or not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',key):
                    raise HTTPException(400, 'Invalid challenge.')
                kid = hashlib.sha256(key.encode()).hexdigest()[:16]
                if data.get('key_id') != kid or type(data.get('expires_in')) is not int or not 1 <= data['expires_in'] <= 3600:
                    raise HTTPException(400, 'Invalid challenge.')
                prior = self.registrations.get(kid)
                if prior:
                    if prior['watch_id'] != wid or prior['path'] != path or prior['code'] != code:
                        raise HTTPException(409, 'Challenge conflict.')
                    return {'accepted':True,'duplicate':True}
                if len(self.registrations) >= MAX_RECORDS or any(v['watch_id']==wid for v in self.registrations.values()):
                    raise HTTPException(409, 'Challenge conflict or capacity reached.')
                self.registrations[kid] = {'watch_id':wid,'path':path,'code':code,'secret':key,'created':now,'code_expires':now+data['expires_in']}
                return {'accepted':True,'duplicate':False}
            if payload.get('type') != 'task_update' or payload.get('purpose') != 'task_updates':
                raise HTTPException(400, 'Unsupported notification purpose.')
            registration = self.registrations.get(headers.get('x-agent-key-id'))
            stamp, event_id = headers.get('x-agent-timestamp',''), headers.get('x-agent-event-id','')
            if not registration or registration['path'] != path or not re.fullmatch(r'\d{10}',stamp) or abs(now-int(stamp)) > 300 or not re.fullmatch(r'te_[0-9a-f]{32}',event_id):
                raise HTTPException(401, 'Invalid notification signature.')
            expected = 'sha256='+hmac.new(registration['secret'].encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected.encode(),headers.get('x-agent-signature','').encode()) or payload.get('event_id') != event_id or payload.get('timestamp') != int(stamp):
                raise HTTPException(401, 'Invalid notification signature.')
            canonical = json.dumps({k:v for k,v in payload.items() if k!='timestamp'},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            if event_id in self.events:
                if self.events[event_id]['digest'] != digest or self.events[event_id]['watch_id'] != registration['watch_id']:
                    raise HTTPException(409, 'Event conflict.')
                return {'accepted':True,'duplicate':True}
            if len(self.events) >= MAX_RECORDS:
                # Never evict replay evidence to make room for an unbounded sender.
                raise HTTPException(429, 'Test inbox capacity reached.')
            item = payload.get('recommendation')
            self.events[event_id] = {'event_id':event_id,'watch_id':registration['watch_id'],'path':path,'received':now,'signature_valid':True,'digest':digest,
                                     'recommendation_id':item.get('id') if isinstance(item,dict) else None}
            return {'accepted':True,'duplicate':False}

    def receipts(self):
        with self.lock:
            now = time.time()
            challenges = [{'watch_id':r['watch_id'],'path':r['path'],'verification_code':r['code'] if r['code_expires']>now else None}
                          for r in self.registrations.values() if r['created']>now-86400]
            return {'challenges':challenges,'events':[{k:v for k,v in r.items() if k!='digest'} for r in self.events.values()]}


async def bounded_json(request):
    if request.headers.get('content-type','').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'JSON is required.')
    if request.headers.get('content-encoding','identity').lower() != 'identity':
        raise HTTPException(415, 'Encoded requests are not accepted.')
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for part in request.stream():
                if len(raw)+len(part) > MAX_BODY:
                    raise HTTPException(413, 'Request too large.')
                raw.extend(part)
        return bytes(raw), json.loads(raw)
    except (ValueError, RecursionError, TimeoutError, ClientDisconnect):
        raise HTTPException(400, 'Invalid JSON request.')


def create_inbox(origin):
    """This is a development receiver, never a public product endpoint."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.inbox = inbox = Inbox()

    @app.middleware('http')
    async def local_only(request, call_next):
        try:
            local = request.client and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if not local or request.headers.get('origin'):
            return JSONResponse({'detail':'Local clients only.'},status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"})
        return response

    @app.get('/receipts')
    def receipts(request: Request):
        if not hmac.compare_digest(request.headers.get('authorization','').encode(),('Bearer '+inbox.token).encode()):
            raise HTTPException(401,'A local read token is required.')
        return inbox.receipts()

    @app.get('/.well-known/{card_name}')
    def card(card_name: str):
        if card_name not in ('agent-card.json','agent-card-v1.json'):
            raise HTTPException(404)
        v1 = card_name == 'agent-card-v1.json'
        data = {'name':'Controlled notification test inbox','version':'1.0.0','description':'Test receiver for requested task updates.',
                'capabilities':{'streaming':False,'pushNotifications':False},'defaultInputModes':['application/json'],'defaultOutputModes':['application/json'],
                'skills':[{'id':'receive_task_updates','name':'Receive task updates','description':'Acknowledge controlled notification test messages.','tags':['notifications']}]}
        if v1:
            data['supportedInterfaces'] = [{'url':origin+'/a2a-v1','protocolBinding':'JSONRPC','protocolVersion':'1.0'}]
        else:
            data.update(protocolVersion='0.3.0',url=origin+'/a2a',preferredTransport='JSONRPC')
        return data

    @app.post('/{route}')
    async def receive(route: str, request: Request):
        if route not in ('webhook','a2a','a2a-v1'):
            raise HTTPException(404)
        raw, body = await bounded_json(request)
        payload, rpc_id = body, None
        if route != 'webhook':
            v1 = route == 'a2a-v1'
            if not isinstance(body,dict) or body.get('jsonrpc')!='2.0' or body.get('method')!=('SendMessage' if v1 else 'message/send') or not isinstance(body.get('id'),(int,str)):
                raise HTTPException(400,'Invalid A2A envelope.')
            if v1 and request.headers.get('a2a-version')!='1.0':
                raise HTTPException(400,'A2A version is required.')
            rpc_id = body['id']
            params = body.get('params')
            message = params.get('message') if isinstance(params,dict) else None
            if not isinstance(message,dict) or message.get('role')!=('ROLE_USER' if v1 else 'user') or not isinstance(message.get('messageId'),str) or (not v1 and message.get('kind')!='message'):
                raise HTTPException(400,'Invalid A2A message.')
            parts = message.get('parts')
            data_parts = [p for p in parts if isinstance(p,dict) and 'data' in p] if isinstance(parts,list) else []
            if len(data_parts)!=1 or (not v1 and data_parts[0].get('kind')!='data') or (v1 and 'kind' in data_parts[0]):
                raise HTTPException(400,'One structured data part is required.')
            payload = data_parts[0]['data']
            if isinstance(payload,dict) and payload.get('event_id') and (rpc_id!=payload['event_id'] or message['messageId']!=payload['event_id']):
                raise HTTPException(400,'A2A event identifiers do not match.')
        result = inbox.receive('/'+route,payload,raw,request.headers)
        if route == 'webhook':
            return result
        response = {'messageId':str(uuid.uuid4()),'role':'ROLE_AGENT' if route=='a2a-v1' else 'agent',
                    'parts':[{'text':'Notification acknowledged.'} if route=='a2a-v1' else {'kind':'text','text':'Notification acknowledged.'}]}
        if route=='a2a-v1':
            response = {'message':response}
        else:
            response['kind']='message'
        return {'jsonrpc':'2.0','id':rpc_id,'result':response}

    return app


def test_certificate(directory):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Controlled local test inbox')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1')),x509.DNSName('localhost'),x509.DNSName('inbox.example')]),critical=False)
            .sign(key,hashes.SHA256()))
    cert_path, key_path = Path(directory)/'certificate.pem',Path(directory)/'private-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    fd = os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    return cert_path,key_path


class _ProcessLoggingUntouched(uvicorn.Config):
    """A disposable test listener must not reconfigure the process loggers: uvicorn's
    configure_logging (access_log=False, log_level) empties uvicorn.access, stops its
    propagation and raises its level, so later 4xx/5xx access records left the managed log."""

    def configure_logging(self):
        pass


@contextmanager
def running_inbox(port=0, advertised_origin=None):
    """Ephemeral HTTPS listener; shutdown and certificate cleanup are automatic."""
    with tempfile.TemporaryDirectory(prefix='notification-inbox-') as directory:
        cert, key = test_certificate(directory)
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1',port))
            origin = 'https://127.0.0.1:'+str(sock.getsockname()[1])
            app = create_inbox(advertised_origin or origin)
            config = _ProcessLoggingUntouched(app,host='127.0.0.1',log_level='error',access_log=False,lifespan='off',ssl_certfile=str(cert),ssl_keyfile=str(key),ssl_version=ssl.PROTOCOL_TLS_SERVER,timeout_keep_alive=2,limit_concurrency=32)
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
            thread.start()
            try:
                deadline = time.monotonic()+5
                while not server.started:
                    if not thread.is_alive() or time.monotonic()>deadline:
                        raise RuntimeError('Test inbox could not start.')
                    time.sleep(0.02)
                yield app,origin,cert
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                if thread.is_alive():
                    server.force_exit = True
                    thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=0,help='Loopback port; 0 chooses an unused temporary port.')
    args = parser.parse_args()
    with running_inbox(args.port) as (app,origin,cert):
        print('Local test inbox only; do not expose it publicly.',flush=True)
        print('Webhook: '+origin+'/webhook',flush=True)
        print('A2A 0.3 card: '+origin+'/.well-known/agent-card.json',flush=True)
        print('A2A 1.0 card: '+origin+'/.well-known/agent-card-v1.json',flush=True)
        print('TLS certificate: '+str(cert),flush=True)
        print('Receipt read token: '+app.state.inbox.token,flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
