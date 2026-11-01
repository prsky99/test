"""Edge-first IO for explicitly authorized managed gateway operations."""
from ..execution_authority import require_enabled
from ..workflow_persistence import dispatch_scope
from . import native


def execute(front, resource, *, tool='', arguments=None, message=''):
    service=getattr(front.store,'_edge_gateway_service',None)
    if service is None or not service.config.direct_result_delivery:return None
    payload=({'message':message} if resource['kind']=='a2a' else
             {'action':'probe'} if resource['kind']=='x402' else {'tool':tool,'arguments':arguments or {}})
    with dispatch_scope(lambda:require_enabled(front.store,'invoke')):
        return native.execute(front.store,resource,payload,courier=getattr(front,'courier',None))


def project(gateway, resource, value):
    if value.get('ok'):
        output=value['result']
        if resource['kind']=='x402':
            return {**output['managed'],'delivery_backend':value.get('delivery_backend')}
        return {**gateway.result(resource,True,True,'completed',output),
                'delivery_backend':value.get('delivery_backend')}
    return {**gateway.result(resource,False,False,'timeout',None,
        'The execution outcome is unconfirmed. Inspect this run before retrying.',504,error_code='UPSTREAM_PROTOCOL'),
        'retry_safe':False,'delivery_backend':'unconfirmed'}
