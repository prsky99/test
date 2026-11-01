"""Verified public registration with an atomic private consent receipt."""
import hashlib
import json
import time

from .registration_policy import fields, legal_consent, public_endpoint, PublicRequestError


def register(store, data, client_ip, *, public_origin='https://agentconcierge.biz'):
    from .front import inspect_register_url, find_existing_agent, clear_front_caches
    receipt = legal_consent(data)
    data = fields(data)
    raw_url = public_endpoint(data.get('url'), public_origin=public_origin)
    kind = data['kind']
    if find_existing_agent(store, raw_url, kind=kind):
        raise PublicRequestError('url', 'This endpoint is already registered.', status=409, code='ALREADY_REGISTERED')
    observed = inspect_register_url(raw_url, store, public_origin=public_origin)
    if not observed.get('protocol_verified'):
        raise PublicRequestError('url', 'The endpoint did not provide a valid public protocol response. Check its address and access requirements.', status=422, code='PROTOCOL_NOT_CONFIRMED')
    if observed['kind']!=kind:
        raise PublicRequestError('kind', 'The selected protocol does not match the endpoint response.', status=422, allowed=(observed['kind'],), code='PROTOCOL_MISMATCH')
    details = observed.get('details') or {}
    price, pay_to, networks = data['price_usdc'], data['pay_to'], data['networks']
    if kind=='x402':
        from .registration_policy import network, wallet
        networks = [network(v) for v in observed['networks']]
        price = observed['price_usdc']
        pay_to = wallet(observed.get('pay_to'), networks)
        if pay_to is None:
            raise PublicRequestError('pay_to', 'The payment requirement must include a valid recipient address.', status=422)
        if data['pay_to'] and data['pay_to']!=pay_to:
            raise PublicRequestError('pay_to', 'The recipient address does not match the endpoint payment requirement.', status=422)
        if data['price_usdc'] and data['price_usdc']!=price:
            raise PublicRequestError('price_usdc', 'The amount does not match the endpoint payment requirement.', status=422)
        if set(data['networks'])!=set(networks):
            raise PublicRequestError('networks', 'The network does not match the endpoint payment requirement.', status=422, allowed=networks)
    now = time.time()
    record = {'key':kind+':'+raw_url, 'source':'manual','kind':kind,'url':raw_url,
        'name':data['name'],'description':data['description'],'category':data['category'],
        'networks':networks,'price_usdc':price,'pay_to':pay_to,
        'method':observed.get('method') or data['method'],'details':details,
        'calls_30d':0,'payers_30d':0,'last_called':None}
    with store.tx() as db:
        if getattr(store,'backend',None)=='postgresql':
            key = int.from_bytes(hashlib.sha256(raw_url.rstrip('/').encode()).digest()[:8], 'big', signed=True)
            store._execute('SELECT pg_advisory_xact_lock(%s::bigint)', (key,))
        if find_existing_agent(store, raw_url, kind=kind):
            raise PublicRequestError('url', 'This endpoint is already registered.', status=409, code='ALREADY_REGISTERED')
        # Use the shared upsert inside this transaction, without nested commits.
        status, rid = store._upsert(db, record, now)
        if status!='new':
            raise PublicRequestError('url', 'This endpoint is already registered.', status=409, code='ALREADY_REGISTERED')
        db.execute('''UPDATE resources SET health_status='healthy',last_check_at=?,last_ok_at=?,next_check_at=?,
            last_status_code=?,last_error=NULL,health_ok_24h=1,health_n_24h=1,probe_latency_ms=?,
            consecutive_failures=0,auth_observed=0,cap_tool_count=? WHERE id=?''',
            (now,now,now+3600,observed.get('status_code',200),observed.get('latency_ms'),
             len(details.get('tools') or details.get('skills') or []),rid))
        db.execute('''INSERT INTO health_checks (resource_id,at,outcome,status_code,latency_ms,error)
            VALUES (?,?,'healthy',?,?,NULL)''',(rid,now,observed.get('status_code',200),observed.get('latency_ms')))
        # Do not publish consent, network identifiers or browser privacy signals in resource metadata.
        db.execute('''INSERT INTO security_events (at,ip,event_type,path,method,user_agent,detail)
            VALUES (?,?,'registration_consent','/api/register','POST',NULL,?)''',
            (now,client_ip,json.dumps({**receipt,'resource_id':rid,'verification_scope':'protocol'},sort_keys=True)))
    clear_front_caches()
    return {'ok':True,'id':rid,'kind':kind,'name':data['name'],'status':'healthy',
        'tool_count':len(details.get('tools') or details.get('skills') or []),
        'verification_scope':'protocol','message':'Your endpoint protocol was confirmed and the listing was registered. Execution quality is checked separately.'}
