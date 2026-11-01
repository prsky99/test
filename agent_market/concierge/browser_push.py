"""Validated Web Push subscriptions with standard encryption and bounded egress."""
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import WebPusher

from .http_security import bounded_client

PUSH_HOSTS = ('fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com')
P256_ORDER = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def unb64(value, size):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',value) or len(value)>128:
        raise ValueError('Invalid subscription key.')
    raw=base64.urlsafe_b64decode(value+'='*(-len(value)%4))
    if len(raw)!=size:
        raise ValueError('Invalid subscription key.')
    return raw


def validate_subscription(value):
    if not isinstance(value,dict) or not isinstance(value.get('keys'),dict):
        raise ValueError('A browser-generated push subscription is required.')
    endpoint=value.get('endpoint')
    if not isinstance(endpoint,str) or not 1<=len(endpoint)<=4096 or re.search(r'[\s\\\x00-\x1f]',endpoint):
        raise ValueError('Invalid push endpoint.')
    parsed=urlsplit(endpoint)
    host=parsed.hostname or ''
    trusted=host in PUSH_HOSTS or host.endswith('.push.services.mozilla.com') or host.endswith('.notify.windows.com')
    if not trusted or parsed.scheme!='https' or parsed.port not in (None,443) or parsed.username is not None or parsed.password is not None or parsed.fragment or not parsed.path.strip('/'):
        raise ValueError('Unsupported push endpoint.')
    point=unb64(value['keys'].get('p256dh'),65)
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),point)
    auth=unb64(value['keys'].get('auth'),16)
    expiry=value.get('expirationTime')
    if expiry is not None and (type(expiry) not in (int,float) or not time.time()*1000<expiry<1e15):
        raise ValueError('Expired subscription.')
    return {'endpoint':endpoint,'keys':{'p256dh':b64(point),'auth':b64(auth)}}


class BrowserPush:
    def __init__(self,key,http=None):
        self.http=http
        scalar=int.from_bytes(hmac.new(key,b'web-push-vapid-v1',hashlib.sha256).digest(),'big')%(P256_ORDER-1)+1
        private=ec.derive_private_key(scalar,ec.SECP256R1())
        der=private.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        self.vapid=Vapid.from_string(b64(der))
        self.public_key=b64(private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))

    def send(self,subscription,payload,ttl=300):
        """Encrypt locally; never allow the library's unbounded network sender."""
        try:
            subscription=validate_subscription(subscription)
            raw=json.dumps(payload,separators=(',',':'),ensure_ascii=True).encode()
            if len(raw)>3000:
                return False,'delivery_failed'
            endpoint=subscription['endpoint'];parsed=urlsplit(endpoint)
            headers=self.vapid.sign({'aud':parsed.scheme+'://'+parsed.netloc,'sub':'mailto:contact@agentconcierge.biz','exp':int(time.time())+3600})
            encoded=WebPusher(subscription).encode(raw,content_encoding='aes128gcm')
            headers.update({'Content-Encoding':'aes128gcm','Content-Type':'application/octet-stream','TTL':str(min(max(int(ttl),0),3600)),'Urgency':'normal','Cookie':''})
            client=bounded_client(self.http,allow_private=False,limit=16384,timeout=httpx.Timeout(10,connect=5))
            try:
                response=client.request('POST',endpoint,headers=headers,content=encoded['body'],auth=None)
            finally:
                client.close()
            return (True,None) if 200<=response.status_code<300 else (False,'gone' if response.status_code in (404,410) else 'delivery_failed')
        except Exception:
            # No endpoint, subscription key, provider body or cryptographic detail reaches callers/logs.
            return False,'delivery_failed'
