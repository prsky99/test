"""Bounded, non-executing inspection of observed public protocol responses."""
import html
import re
import time
from urllib.parse import urlsplit

from ..collector.health import parse_payment_required
from ..collector.capabilities import parse_jsonrpc
from .http_security import bounded_client
from .registration_policy import public_endpoint, network, wallet, PublicRequestError

USDC = {'base':'0x833589fcd6edb6e08f4c7c32d4f71b54bda02913',
    'ethereum':'0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
    'solana':'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'}
CLIENT = {'name':'agent-concierge-registration','version':'1'}
VERSIONS = ('2025-11-25','2025-06-18','2025-03-26','2024-11-05','2026-07-28')


def clean(value, maximum):
    if type(value) is not str:
        return ''
    value = html.unescape(re.sub(r'<[^>]*>', '', value))
    from .registration_policy import contains_controls
    return ''.join(c for c in value if not contains_controls(c))[:maximum].strip()


def payment(resp, parsed=None, method='GET'):
    if resp.status_code!=402:
        return None
    accepts = parse_payment_required(resp, resp.content) or []
    valid = []
    for item in accepts[:20]:
        if type(item) is not dict or item.get('scheme')!='exact':
            continue
        try:
            net = network(item.get('network'))
            asset = item.get('asset')
            if type(asset) is not str or (asset if net=='solana' else asset.lower())!=USDC[net]:
                continue
            amount = item.get('amount', item.get('maxAmountRequired'))
            if type(amount) is int:
                price = amount
            elif type(amount) is str and re.fullmatch(r'[0-9]{1,16}', amount):
                price = int(amount)
            else:
                continue
            if not 0 <= price <= 2**53-1:
                continue
            recipient = wallet(item.get('payTo'), [net])
            if not recipient:
                continue
        except PublicRequestError:
            continue
        valid.append((price, net, recipient, item))
    if not valid:
        return None
    price, net, recipient, selected = min(valid, key=lambda v:v[0])
    public_accepts = [{k:v for k,v in item.items() if k in ('scheme','network','asset','amount','maxAmountRequired','payTo','maxTimeoutSeconds')}
        for _,_,_,item in valid[:4]]
    return {'kind':'x402','name':'','description':clean(selected.get('description'),1000),
        'price_usdc':price,'pay_to':recipient,'networks':[net],'method':method,
        'status_code':402,'details':{'accepts':public_accepts,'method':method}}


def a2a_card(resp, card_url, *, public_origin='https://agentconcierge.biz'):
    if resp.status_code!=200:
        return None
    try:
        value = resp.json()
    except (ValueError, RecursionError):
        return None
    if type(value) is not dict or type(value.get('name')) is not str or not value['name'].strip():
        return None
    raw_skills = value.get('skills')
    if type(raw_skills) is not list or not raw_skills or not all(type(v) is dict and type(v.get('id')) is str and v['id'].strip() for v in raw_skills[:100]):
        return None
    endpoint = value.get('url')
    if not endpoint and type(value.get('supportedInterfaces')) is list:
        endpoint = next((v.get('url') for v in value['supportedInterfaces'][:10] if type(v) is dict and
            v.get('protocolBinding', v.get('transport','JSONRPC')) in ('JSONRPC','JSON_RPC')), None)
    try:
        public_endpoint(endpoint, public_origin=public_origin)
    except PublicRequestError:
        return None
    return {'kind':'a2a','name':clean(value['name'],100),'description':clean(value.get('description'),1000),
        'method':'POST','status_code':200,
        'details':{'agent_card':card_url,'card_url':card_url,'skills':[clean(v['id'],100) for v in raw_skills[:100]]}}


def mcp_or_payment(client, raw_url, parsed=None):
    headers = {'accept':'application/json, text/event-stream','content-type':'application/json'}
    initialized = False
    meta = {'io.modelcontextprotocol/protocolVersion':'2026-07-28',
        'io.modelcontextprotocol/clientInfo':CLIENT,'io.modelcontextprotocol/clientCapabilities':{}}
    result = None
    session = None
    for modern in (False, True):
        request = {'jsonrpc':'2.0','id':1,'method':'server/discover' if modern else 'initialize',
            'params':{'_meta':meta} if modern else {'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':CLIENT}}
        try:
            response = client.post(raw_url, json=request, headers={**headers, **({'Mcp-Protocol-Version':'2026-07-28','Mcp-Method':'server/discover'} if modern else {})})
        except Exception:
            continue
        if found := payment(response, parsed, method='POST'):
            return found
        rpc = parse_jsonrpc(response) if response.status_code==200 else None
        value = rpc.get('result') if type(rpc) is dict and rpc.get('jsonrpc')=='2.0' and rpc.get('id')==1 and 'error' not in rpc else None
        if type(value) is not dict or type(value.get('serverInfo')) is not dict or type(value.get('capabilities')) is not dict:
            continue
        info = value['serverInfo']
        if value.get('protocolVersion') not in VERSIONS or not clean(info.get('name'),100) or not clean(info.get('version'),100):
            continue
        if modern and value['protocolVersion']!='2026-07-28' or not modern and value['protocolVersion']=='2026-07-28':
            continue
        result = value
        session = response.headers.get('mcp-session-id') if not modern else None
        initialized = not modern
        break
    if result is None:
        return None
    info = result['serverInfo']
    tools = []
    try:
        wire_headers = {**headers,'Mcp-Protocol-Version':result['protocolVersion']}
        if session:
            wire_headers['Mcp-Session-Id'] = session
        if initialized:
            client.post(raw_url, json={'jsonrpc':'2.0','method':'notifications/initialized'}, headers=wire_headers)
        if 'tools' in result['capabilities']:
            response = client.post(raw_url, json={'jsonrpc':'2.0','id':2,'method':'tools/list',
                'params':{} if initialized else {'_meta':meta}}, headers={**wire_headers,'Mcp-Method':'tools/list'})
            payload = parse_jsonrpc(response) if response.status_code==200 else None
            raw = (payload.get('result') or {}).get('tools') if type(payload) is dict and type(payload.get('result')) is dict else None
            if type(raw) is list:
                tools = [clean(t.get('name'),100) for t in raw[:100] if type(t) is dict and clean(t.get('name'),100)]
    except Exception:
        pass
    finally:
        if session:
            try:
                client.delete(raw_url, headers={'Mcp-Session-Id':session})
            except Exception:
                pass
    return {'kind':'mcp','name':clean(info.get('title') or info['name'],100),
        'description':clean(result.get('instructions') or info.get('description'),1000),
        'method':'POST','status_code':200,'details':{'protocol_version':result['protocolVersion'],
            'server_info':{k:clean(info.get(k),100) for k in ('name','title','version') if info.get(k)},'tools':tools}}


def inspect(raw_url, store=None, *, public_origin='https://agentconcierge.biz'):
    from .front import find_existing_agent
    raw_url = public_endpoint(raw_url, public_origin=public_origin)
    started = time.monotonic()
    parsed = urlsplit(raw_url)
    found = None
    client = bounded_client(allow_private=False, timeout=5.0)
    try:
        if parsed.path.endswith('.json'):
            try:
                found = a2a_card(client.get(raw_url), raw_url, public_origin=public_origin)
            except Exception:
                pass
        if not found:
            found = mcp_or_payment(client, raw_url, parsed)
        if not found:
            try:
                response = client.get(raw_url)
                found = payment(response, parsed) or a2a_card(response, raw_url, public_origin=public_origin)
            except Exception:
                pass
        if not found:
            base = parsed.scheme+'://'+parsed.netloc
            urls = list(dict.fromkeys([raw_url.rstrip('/')+'/.well-known/agent-card.json',
                raw_url.rstrip('/')+'/.well-known/agent.json',base+'/.well-known/agent-card.json']))
            for url in urls:
                try:
                    if hasattr(client, 'budget'):
                        client.budget.remaining()
                    public_endpoint(url, public_origin=public_origin)
                    found = a2a_card(client.get(url), url, public_origin=public_origin)
                    if found:
                        break
                except Exception:
                    continue
    finally:
        client.close()
    existing = find_existing_agent(store, raw_url, kind=found['kind'] if found else None,
        card_url=(found or {}).get('details',{}).get('agent_card'))
    return {'ok':True,'url':raw_url,'protocol_verified':bool(found),
        'verification_scope':'protocol' if found else 'unconfirmed','kind':found['kind'] if found else None,
        'name':(found or {}).get('name',''),'description':(found or {}).get('description',''),
        'category':existing.get('category') if existing else None,
        'price_usdc':(found or {}).get('price_usdc'), 'pay_to':(found or {}).get('pay_to'),
        'networks':(found or {}).get('networks',[]),'method':(found or {}).get('method'),
        'details':(found or {}).get('details',{}),'status_code':(found or {}).get('status_code'),
        'latency_ms':round((time.monotonic()-started)*1000),'already_registered':bool(existing),
        'existing':{'id':existing['id'],'kind':existing['kind'],'name':existing['name'],'source':existing['source']}
            if existing else None}
