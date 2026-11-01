"""Private Admin authority; the browser receives Provider output on public Edge.

Admin session tokens stay on the private transport. Only one short-lived,
input-bound execution ticket crosses to the public data plane. Origin recovery
claims that same run, so an uncertain Edge result never creates a second IO.
"""
import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

from .auth import RUN, derived
from .config import EdgeError
from .result_transport import read, write_once, sql
from .state import rows, transaction

CONTEXT='edge-admin-delivery-v1'
AUDIT='edge-admin-audit-v1'


def origin(value):
    try:
        u=urlsplit(value)
        if (type(value) is not str or len(value)>512 or u.scheme not in ('http','https') or not u.hostname
                or u.username is not None or u.password is not None or u.path or u.query or u.fragment
                or value!=u.scheme+'://'+u.netloc or any(ord(c)<33 for c in value)):
            raise ValueError()
        return value
    except (ValueError,TypeError):raise EdgeError('AUTH_REQUIRED',403) from None


def principal(service,user):
    value=str(user.get('user_id',user.get('id')))+':'+str(user.get('username'))
    return hmac.new(derived(service.config.key,'edge-admin-principal-v1'),value.encode(),hashlib.sha256).hexdigest()


def approved(service,row):
    context=read(service,row['id'],CONTEXT)
    if (not context or context.get('principal')!=row['principal'] or context.get('origin')!=row['origin']
            or context.get('resource_id')!=row['resource_id'] or context.get('version_id')!=row['version_id']):
        raise EdgeError('AUTH_REQUIRED',403)
    origin(row['origin'])
    return context


def prepare(service,user,client_origin,body):
    if (type(body) is not dict or set(body)-{'resource_id','tool','arguments','message','timeout_seconds','action'}
            or type(body.get('resource_id')) is not int):raise EdgeError('INVALID_INPUT',400)
    client_origin=origin(client_origin)
    if not service.config.direct_result_delivery or service.summary()['preferred_backend']!='worker':
        return {'backend':'origin','reason':'EDGE_UNAVAILABLE'}
    resource=service.store.resource(body['resource_id'])
    from ..owned_data_agents.dispatch import is_owned
    from .native import credential_input
    payload=({'message':body.get('message') or 'Hello! What can you help with?'} if resource and resource['kind']=='a2a' else
             {'action':'probe'} if resource and resource['kind']=='x402' else {'tool':body.get('tool',''),'arguments':body.get('arguments',{})})
    if not resource or is_owned(resource) or credential_input(payload):
        return {'backend':'origin','reason':'PROFILE_UNAVAILABLE'}
    try:
        from ..concierge.execution_policy import ExecutionDenied
        from .catalog import payload_for
        provider,fresh=service.admitted(resource['id'])
        payload=payload_for(provider,payload,fresh)
        owner=principal(service,user)
        grant=service.prepare(owner,client_origin,{'resource_id':resource['id'],'input':payload,
            'idempotency_key':secrets.token_hex(24),'run_authority':True,'sharing_authority':True})
        row=service.authorized(grant['access_token'],client_origin,grant['run_id'])
        write_once(service,row['id'],CONTEXT,{'principal':owner,'origin':client_origin,'resource_id':resource['id'],
            'version_id':row['version_id'],'input':payload})
    except ExecutionDenied:
        raise EdgeError('POLICY_DENIED',403) from None
    except EdgeError as exc:
        if exc.code in ('PROFILE_UNAVAILABLE','POLICY_DENIED','SCHEMA_CHANGED','INVALID_INPUT'):
            return {'backend':'origin','reason':'PROFILE_UNAVAILABLE'}
        raise
    return {'backend':'worker','base':service.config.origin,**grant,'input':payload,'protocol':resource['kind']}


async def finish(service,user,run_id,*,recover=False):
    if type(run_id) is not str or not RUN.fullmatch(run_id):raise EdgeError('INVALID_INPUT',400)
    owner=principal(service,user)
    state=service.status(owner,run_id)
    with transaction(service.store,readonly=True) as db:row=rows(db,'run',(run_id,))[0]
    context=approved(service,row)
    result=None
    if state['state']=='prepared' and recover and state.get('access_token'):
        try:
            result=await service.origin(state['access_token'],context['origin'],run_id,context['input'])
            state=service.status(owner,run_id)
        except EdgeError as exc:
            if exc.code not in ('ALREADY_CLAIMED','ATTEMPT_CHANGED'):raise
            state=service.status(owner,run_id)
        with transaction(service.store,readonly=True) as db:row=rows(db,'run',(run_id,))[0]
    terminal=state['state'] in ('succeeded','failed','outcome_unknown')
    if terminal:
        # A unique metadata marker makes browser polling audit-safe.
        with transaction(service.store) as db:
            changed=sql(db,'INSERT INTO workflow_checkpoints (run_id,node_id,payload,signature) VALUES (?,?,?,?) ON CONFLICT(run_id,node_id) DO NOTHING',
                (run_id,AUDIT,'{}','metadata-only')).rowcount
            if changed:
                from ..gateway import admin_auth
                admin_auth.record_audit(db,username=user['username'],role=user['role'],action='AGENT_TEST',
                    action_name='Edge agent test',target='agent:'+str(row['resource_id']),
                    status='SUCCESS' if state['state']=='succeeded' else 'FAILED',
                    details={'agent_id':row['resource_id'],'delivery_backend':row['backend'],
                        'state':state['state'],'error':state.get('error_code')})
    answer={'run_id':run_id,'state':state['state'],'backend':row['backend'],'error_code':state.get('error_code')}
    if result is not None:
        from .output_monitor import note
        note(service,'origin','admin','edge_unavailable')
        answer['origin_result']=result
    return answer


async def server_test(front,resource,body,user):
    """Compatibility callers also prefer Edge before their original transport."""
    service=getattr(front,'edge_gateway',None) if front else None
    if service is None or not service.config.direct_result_delivery:return None
    from ..owned_data_agents.dispatch import is_owned
    from .native import credential_input
    from ..concierge.execution_policy import ExecutionDenied
    if is_owned(resource) or credential_input(body.get('arguments',{})):return None
    try:
        from .catalog import payload_for
        provider,fresh=service.admitted(resource['id'])
        payload=({'message':body.get('message') or 'Hello! What can you help with?'} if resource['kind']=='a2a' else
            {'action':'probe'} if resource['kind']=='x402' else {'tool':body.get('tool',''),'arguments':body.get('arguments',{})})
        payload_for(provider,payload,fresh)
    except (EdgeError,ExecutionDenied):return None
    result=await front.managed_gateway.execute(resource['id'],kind=resource['kind'],tool=body.get('tool',''),
        arguments=body.get('arguments',{}),message=body.get('message') or 'Hello! What can you help with?',source='testbench')
    from ..gateway import admin_auth
    with service.store.tx() as db:
        admin_auth.record_audit(db,username=user['username'],role=user['role'],action='AGENT_TEST',action_name='Edge-first agent test',
            target='agent:'+str(resource['id']),status='SUCCESS' if result.get('execution_succeeded') else 'FAILED',
            details={'agent_id':resource['id'],'delivery_backend':result.get('delivery_backend','origin')})
    import json,time
    return {**result,'output_text':json.dumps(result.get('output'),ensure_ascii=False,indent=2),
        'target_url':resource['url'],'tested_at':time.time(),'latency_ms':result.get('latency_ms',0),
        'request_wire':{'scope':'client-to-gateway','method':'POST'},'response_wire':result.get('output')}
