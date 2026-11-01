"""Bounded public, stateless connection profiles backed by registered bindings."""
import asyncio
import base64
import json
import math
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..broker.discovery import DiscoveryError
from ..collector.a2a import message_request, _ACTION, _PII
from .connections import KINDS, bindings, gateway_agent_url, project
from .execution_policy import admit, admit_tool, tools_for, resolve_a2a, safe_registered_tool, ExecutionDenied
from .http_security import bounded_client, outbound_operation
from .recommendation_security import public_schema, usable_endpoint
from .security import public_metadata
from .execution_errors import fields, failure_code, reference, record_failure
from ..observability import journal_for, attempt_scope, provider_dispatch, result_state

_workers=ThreadPoolExecutor(max_workers=4,thread_name_prefix='managed-agent')
_slots=threading.BoundedSemaphore(4)


def challenge(response):
    """Accept only recognizable x402 v1/v2 envelopes; a bare 402 is not success."""
    from .payment_wire import challenge_objects
    candidates=challenge_objects(response)
    for obj in candidates:
        if not isinstance(obj,dict) or type(obj.get('x402Version')) is not int or obj['x402Version'] not in (1,2):continue
        version=obj['x402Version']
        if version==2 and (not isinstance(obj.get('resource'),dict) or not usable_endpoint(obj['resource'].get('url'))):continue
        if version==1 and not isinstance(obj.get('error'),str):continue
        accepts=obj.get('accepts')
        if not isinstance(accepts,list) or not 0<len(accepts)<=20:continue
        valid=True
        for item in accepts:
            if not isinstance(item,dict):valid=False;break
            amount=item.get('amount') if obj['x402Version']==2 else item.get('maxAmountRequired')
            seconds=item.get('maxTimeoutSeconds')
            if (not isinstance(amount,str) or not amount.isascii() or not amount.isdecimal() or len(amount)>78
                    or type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0
                    or version==1 and (not usable_endpoint(item.get('resource')) or not isinstance(item.get('description'),str))
                    or not all(isinstance(item.get(k),str) and 0<len(item[k])<=256 for k in ('scheme','network','asset','payTo'))):
                valid=False;break
        if valid:return obj
    return None


class ManagedGateway:
    def __init__(self, front):
        self.front=front
        self.journal=journal_for(front.store)

    def resource(self,rid,kind=None):
        if type(rid) is not int or not 0<rid<2**31 or kind is not None and kind not in KINDS:
            raise ExecutionDenied('Choose a registered agent and supported protocol.')
        resource=self.front.store.resource(rid)
        from ..capability_registry import known_schema_failure
        if known_schema_failure(self.front.store,resource):
            raise ExecutionDenied('The registered capability schema needs review before execution.',
                                  error_code='SCHEMA_CHANGED')
        admit(resource,kind,public=True,authorize_charge=resource is not None and resource.get('kind')=='x402')
        if resource['kind'] not in KINDS:raise ExecutionDenied('This protocol is not supported.')
        return resource

    async def execute(self,rid,*,kind=None,tool='',arguments=None,message='',timeout=8,source='managed',expected_version=None,edge_first=True):
        correlation_id=reference()
        operation=self.journal.begin('execution',source,identity=correlation_id,resource_id=rid,proto=kind)
        from ..capability_registry import Registry
        registry=Registry(self.front.store);version=registry.current(rid);started=time.time()
        try:
            from ..execution_authority import require_enabled
            require_enabled(self.front.store,'invoke')
            if expected_version is not None and (not version or version['id']!=expected_version):
                raise ExecutionDenied('The approved connection version changed.',error_code='SCHEMA_CHANGED')
            result=await self._execute_bounded(rid,kind=kind,tool=tool,arguments=arguments,message=message,timeout=timeout,operation=operation,edge_first=edge_first)
        except (ExecutionDenied,HTTPException) as exc:
            code=exc.error_code if isinstance(exc,ExecutionDenied) else 'CAPACITY_EXCEEDED' if exc.status_code==503 else 'EXECUTION_FAILED'
            exc.error_code=code
            exc.correlation_id=correlation_id
            record_failure(correlation_id,rid,kind,code,stage='admission',exception=exc)
            operation.finish('denied',code)
            operation.detach_attempts()
            raise
        except asyncio.CancelledError:
            operation.finish('cancelled')
            operation.detach_attempts()
            raise
        except Exception:
            operation.finish('failed','EXECUTION_FAILED')
            operation.detach_attempts()
            raise
        result['correlation_id']=correlation_id
        if not result.get('execution_succeeded'):
            code=failure_code(result.get('error_code'))
            result['error_code']=code
            record_failure(correlation_id,rid,result.get('protocol'),code)
        operation.finish(result_state(result),result.get('error_code'))
        operation.detach_attempts()
        if version and result.get('protocol') in ('a2a','x402'):
            registry.record(version,scope='transport' if result['protocol']=='x402' else 'execution',
                outcome='succeeded' if result.get('execution_succeeded') else 'unknown' if result.get('task_status')=='timeout' else 'failed',
                started=started,finished=time.time(),operation_ref=correlation_id,code=result.get('error_code'))
        elif version and result.get('task_status')=='timeout':
            registry.record(version,scope='execution',outcome='unknown',started=started,finished=time.time(),operation_ref=correlation_id,code='UPSTREAM_TIMEOUT')
        return result

    async def _execute_bounded(self,rid,*,kind=None,tool='',arguments=None,message='',timeout=8,operation=None,edge_first=True):
        resource=self.resource(rid,kind)
        if operation:operation.selected(rid,resource['kind'])
        arguments={} if arguments is None else arguments
        if resource['kind']=='mcp':
            admit_tool(resource,tool,arguments)
            if not resource.get('usage_tools_hash'):raise ExecutionDenied('The registered capability schema is not verified.')
        if not _slots.acquire(blocking=False):raise HTTPException(503,'Agent execution is busy.',headers={'Retry-After':'5'})
        attempt=operation.attempt(rid,resource['kind']) if operation else None
        def work():
            if attempt is None:
                with outbound_operation(timeout):return self._execute(resource,tool,arguments,message)
            with attempt_scope(attempt,finish_errors=False),outbound_operation(timeout):
                if edge_first:
                    from ..edge_gateway.managed import execute,project
                    value=execute(self.front,resource,tool=tool,arguments=arguments,message=message)
                    if value is not None:return project(self,resource,value)
                return self._execute(resource,tool,arguments,message)
        try:future=_workers.submit(work)
        except Exception:
            _slots.release();raise
        future.add_done_callback(lambda done:_slots.release())
        try:
            result=await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)),timeout=timeout)
        except (asyncio.TimeoutError,httpx.TimeoutException):
            result=self.result(resource,False,False,'timeout',None,'The agent did not finish within the time limit.',504,error_code='UPSTREAM_TIMEOUT')
        except ExecutionDenied as exc:
            if attempt:attempt.finish('failed',exc.error_code)
            raise
        except (httpx.HTTPError,DiscoveryError,ValueError,TypeError,KeyError) as exc:
            code='UPSTREAM_NETWORK' if isinstance(exc,httpx.HTTPError) else 'POLICY_DENIED' if isinstance(exc,DiscoveryError) else 'UPSTREAM_PROTOCOL'
            result=self.result(resource,False,False,'failed',None,fields(code)['error_message'],502,error_code=code)
        if attempt and result.get('task_status')!='timeout':
            attempt.finish(result_state(result),result.get('error_code'),result.get('transport_ok'),result.get('protocol_valid'))
        return result

    def result(self,resource,transport,valid,state,output,error=None,status=200,*,error_code=None):
        success=bool(valid and state=='completed')
        gateway=gateway_agent_url(resource['id'],resource['kind'])
        bound=bindings(resource)
        fault={} if success else fields(error_code or ('AUTH_REQUIRED' if state=='authorization-required' else
            'PENDING_RESULT' if valid and state in ('submitted','working','input-required') else 'UPSTREAM_PROTOCOL' if not valid else 'UPSTREAM_TOOL_ERROR'))
        return {'ok':success,'execution_succeeded':success,'transport_ok':transport,'protocol_valid':valid,
                'task_status':state,'status_code':status,'protocol':resource['kind'],
                'output':project(public_metadata(output),gateway,bound),
                'error_message':project(public_metadata(error),gateway,bound) if error else None,
                'is_error':not success,'simulated':False,**({'error_code':fault['error_code']} if fault else {})}

    def _execute(self,resource,tool,args,message):
        current=self.resource(resource['id'],resource['kind'])
        from ..capability_registry import version_parts
        if any(current.get(key)!=resource.get(key) for key in ('url','usage_tools_hash','details')) or version_parts(current)!=version_parts(resource):
            raise ExecutionDenied('The agent connection changed. Review it before retrying.')
        kind=resource['kind']
        if kind=='mcp':
            result=self.front.proxy.execute(resource['id'],tool,args,public=True)
            ok=result.get('ok') is True
            fault=fields(result.get('error_code'))
            return self.result(resource,result.get('transport_ok',False),result.get('protocol_valid',False),'completed' if ok else 'failed',
                               result.get('result') if ok else None,None if ok else fault['error_message'],200 if ok else 502,error_code=fault['error_code'])
        if kind=='a2a':
            if not isinstance(message,str) or not message.strip() or len(message)>2000:
                raise ExecutionDenied('Provide a message of 1 to 2000 characters.')
            if _ACTION.search(message) or _PII.search(message):
                raise ExecutionDenied('This connection accepts informational requests without personal data only.')
            target=resolve_a2a(resource,self.front.courier,public=True)
            resource={**resource,'gateway_bound_urls':[target['url']]}
            mid=secrets.token_hex(16)
            provider_dispatch()
            status,raw=self.front.courier._request('POST',target['url'],65536,public_only=True,
                json=message_request({'spec_version':'1.0' if target.get('v1') else '0.3'},message,request_id=mid),
                headers={'Content-Type':'application/json',**({'A2A-Version':'1.0'} if target.get('v1') else {})})
            data=json.loads(raw)
            if not 200<=status<300 or not isinstance(data,dict) or data.get('jsonrpc')!='2.0' or data.get('id')!=mid or data.get('error'):
                return self.result(resource,200<=status<300,False,'failed',None,'The agent returned an invalid protocol response.',502)
            result=data.get('result')
            obj=(result.get('message') or result.get('task') or result) if isinstance(result,dict) else {}
            if not isinstance(obj,dict):obj={}
            status_value=obj.get('status') or {}
            if not isinstance(status_value,dict):
                return self.result(resource,True,False,'invalid',None,'The agent returned an invalid task status.',502)
            state=str(status_value.get('state','')).lower().replace('task_state_','')
            parts=obj.get('parts') if not state else None
            if state=='completed':
                parts=[p for a in obj.get('artifacts',[]) if isinstance(a,dict) for p in a.get('parts',[]) if isinstance(p,dict)]
            known=state in ('submitted','working','input-required','auth-required','failed','canceled','cancelled','rejected','completed')
            from .result_quality import usable_a2a_parts
            if parts and isinstance(parts,list):
                if not usable_a2a_parts(parts,message):
                    return self.result(resource,True,True,'failed',None,'The agent returned no usable task result.',502,error_code='UPSTREAM_TOOL_ERROR')
                return self.result(resource,True,True,'completed',{'parts':parts})
            if state=='completed':
                return self.result(resource,True,True,'failed',None,'The agent returned no usable task result.',502,error_code='UPSTREAM_TOOL_ERROR')
            return self.result(resource,True,known,state or 'invalid',None,
                'The agent has no completed output. This connection does not support task polling.',200 if known else 502)
        # Probe only: never forward browser headers, credentials, cookies or automatic payments.
        client=bounded_client(allow_private=False,limit=65536,timeout=httpx.Timeout(10,connect=5))
        try:
            provider_dispatch()
            response=client.get(resource['url'],headers={'Accept':'application/json','Accept-Encoding':'identity'})
            status=response.status_code
            obj=challenge(response) if status==402 else None
            if status==402:
                return self.result(resource,True,obj is not None,'authorization-required' if obj else 'invalid',obj,
                                   'Provider authorization is required.' if obj else 'No valid x402 challenge was returned.',402)
            try:output=response.json()
            except ValueError:output=response.text[:16384]
            return self.result(resource,200<=status<300,200<=status<300,'completed' if 200<=status<300 else 'failed',
                               output,None if 200<=status<300 else 'The agent rejected the probe.',status)
        finally:client.close()


def gateway_router(front,read_json_object):
    router=APIRouter()
    gateway=ManagedGateway(front)
    front.managed_gateway=gateway

    def rate(request):
        ip=front.security.resolve_ip(request)
        allowed=front.security.allow_probe(ip,base_limit=10)
        from .security import quota_headers
        quota=quota_headers();request.scope['agent_adoption_quota']=quota
        if not allowed:
            raise HTTPException(429,'Too many agent requests.',headers={'Retry-After':'60',**quota})

    def submitted_payment(request,kind,row=None):
        if kind=='x402' and any(name in request.headers for name in
                ('payment-signature','x-payment','x-payment-tx','x-payment-signature')):
            from .payment_validator import validate_payment_submission, inspection_notice
            # Inspect the proof only to explain it; it is never settled, stored or forwarded.
            try:
                well_formed, code, _, _ = validate_payment_submission(request.headers, row)
            except Exception:
                well_formed, code = False, 'invalid_payload'
            provider_url = str(row.get('url') or '') if isinstance(row, dict) else ''
            headers = {
                'Cache-Control': 'no-store',
                'X-AgentConcierge-Payment-Mode': 'inspection-only',
                'X-Provider-Url': provider_url,
            }
            if provider_url:
                headers['Location'] = provider_url
                headers['Link'] = f'<{provider_url}>; rel="payment-provider"'
            return JSONResponse(inspection_notice({'ok':False,'error_code':'PAYMENT_EXECUTION_DISABLED','payment_processed':False,
                'gateway_mode':'inspection_only','provider_url':provider_url,
                'reason':'not_processed' if well_formed else code,
                'error':("This public gateway inspects x402 listings but does not accept or forward payments. Review the provider's own endpoint and terms separately. "
                         + ('The proof is well formed but was not processed.' if well_formed
                            else 'The proof would also be rejected: ' + code + '.'))}),
                status_code=501,headers=headers)
        return None

    def resource(rid,kind):
        try:return gateway.resource(rid,kind)
        except ExecutionDenied as exc:
            if exc.error_code=='POLICY_DENIED':
                raise HTTPException(403,fields(exc.error_code)['error_message'],
                                    headers={'X-Execution-Error':exc.error_code}) from exc
            raise HTTPException(400,str(exc)) from exc

    async def execute(rid,**kwargs):
        try:return await gateway.execute(rid,**kwargs)
        except ExecutionDenied as exc:
            return_error=HTTPException(403 if exc.error_code=='POLICY_DENIED' else 400,
                                       fields(exc.error_code)['error_message'] if exc.error_code=='POLICY_DENIED' else str(exc))
            return_error.headers={'X-Execution-Reference':getattr(exc,'correlation_id',None) or reference(),'X-Execution-Error':exc.error_code}
            raise return_error from exc

    @router.get('/api/gateway/{kind}/{rid}')
    async def get_connection(kind:str,rid:int,request:Request):
        rate(request);row=resource(rid,kind)
        refused=submitted_payment(request,kind,row)
        if refused is not None:return refused
        url=gateway_agent_url(rid,kind)
        if kind=='mcp':
            return JSONResponse({'profile':'stateless-jsonrpc','endpoint':url,'methods':['initialize','ping','tools/list','tools/call'],
                                 'streaming':False,'sessions':False},status_code=405,headers={'Allow':'POST'})
        if kind=='a2a':
            return {'name':public_metadata(row.get('name') or 'Agent'),'description':'Informational requests with synchronous results.',
                    'protocolVersion':'0.3.0','url':url,'preferredTransport':'JSONRPC',
                    'capabilities':{'streaming':False,'pushNotifications':False},'defaultInputModes':['text/plain'],
                    'defaultOutputModes':['text/plain'],'skills':[],
                    'connectionProfile':{'taskPolling':False,'methods':['message/send','SendMessage']}}
        result=await execute(rid,kind=kind)
        if result['status_code']==402:
            from .payment_validator import payment_requirements_for, inspection_notice
            provider_url = str(row.get('url') or '') if isinstance(row, dict) else ''
            raw_body = result['output'] if result.get('protocol_valid') and isinstance(result.get('output'),dict) else payment_requirements_for(row)
            body = inspection_notice(raw_body)
            body['gateway_mode'] = 'inspection_only'
            body['provider_url'] = provider_url
            headers = {
                'Cache-Control': 'no-store',
                'X-AgentConcierge-Payment-Mode': 'inspection-only',
                'X-Provider-Url': provider_url,
            }
            if provider_url:
                headers['Link'] = f'<{provider_url}>; rel="payment-provider"'
            if body.get('x402Version')==2:
                headers['PAYMENT-REQUIRED']=base64.b64encode(json.dumps(body).encode()).decode()
            return JSONResponse(body,status_code=402,headers=headers)
        return JSONResponse(result,status_code=result['status_code'])

    @router.post('/api/gateway/{kind}/{rid}')
    async def post_connection(kind:str,rid:int,request:Request):
        rate(request);row=resource(rid,kind)
        refused=submitted_payment(request,kind,row)
        if refused is not None:return refused
        body=await read_json_object(request)
        if kind=='x402':
            if body!={'action':'probe'}:raise HTTPException(400,'Only the explicit probe action is supported.')
            result=await execute(rid,kind=kind)
            if result.get('status_code')==402:
                from .payment_validator import payment_requirements_for, inspection_notice
                provider_url = str(row.get('url') or '') if isinstance(row, dict) else ''
                raw_body = result['output'] if result.get('protocol_valid') and isinstance(result.get('output'),dict) else payment_requirements_for(row)
                resp_body = inspection_notice(raw_body)
                resp_body['gateway_mode'] = 'inspection_only'
                resp_body['provider_url'] = provider_url
                headers = {
                    'Cache-Control': 'no-store',
                    'X-AgentConcierge-Payment-Mode': 'inspection-only',
                    'X-Provider-Url': provider_url,
                }
                if provider_url:
                    headers['Link'] = f'<{provider_url}>; rel="payment-provider"'
                if resp_body.get('x402Version')==2:
                    headers['PAYMENT-REQUIRED']=base64.b64encode(json.dumps(resp_body).encode()).decode()
                return JSONResponse(resp_body,status_code=402,headers=headers)
            return JSONResponse(result,status_code=result.get('status_code', 200))
        request_id=body.get('id');method=body.get('method');params=body.get('params',{})
        def error(code,message,diagnostic=None):
            body={'jsonrpc':'2.0','id':request_id,'error':{'code':code,'message':message}}
            if diagnostic:body['error']['data']={k:diagnostic[k] for k in ('error_code','correlation_id') if k in diagnostic}
            return body
        if (body.get('jsonrpc')!='2.0' or not isinstance(params,dict) or not isinstance(method,str)
                or type(request_id) not in (str,int,type(None)) or isinstance(request_id,str) and len(request_id)>128):
            request_id=None;return error(-32600,'Invalid JSON-RPC request.')
        if kind=='mcp':
            if method=='initialize':
                return {'jsonrpc':'2.0','id':request_id,'result':{'protocolVersion':'2025-06-18',
                        'serverInfo':{'name':'agent-concierge-connection','version':'1.0'},'capabilities':{'tools':{'listChanged':False}},
                        'instructions':'Stateless JSON only. No streaming or upstream sessions. Registered informational tools only.'}}
            if method=='notifications/initialized':return Response(status_code=202)
            if method=='ping':return {'jsonrpc':'2.0','id':request_id,'result':{}}
            if method=='tools/list':
                tools=[]
                for spec in tools_for(row):
                    if not safe_registered_tool(spec):continue
                    tools.append(public_schema({'name':spec['name'],'description':spec.get('description',''),
                        'inputSchema':spec.get('inputSchema') or {'type':'object','properties':spec.get('params',{}),
                                                               'required':spec.get('required',[])}}))
                tools=project(tools,gateway_agent_url(rid,kind),bindings(row))
                return {'jsonrpc':'2.0','id':request_id,'result':{'tools':tools}}
            if method!='tools/call':return error(-32601,'Method not supported by this connection profile.')
            try:result=await gateway.execute(rid,kind=kind,tool=params.get('name'),arguments=params.get('arguments',{}))
            except ExecutionDenied as exc:
                if exc.error_code=='POLICY_DENIED':
                    raise HTTPException(403,fields(exc.error_code)['error_message'],
                                        headers={'X-Execution-Error':exc.error_code}) from exc
                return error(-32602,fields(exc.error_code)['error_message'],
                             fields(exc.error_code,getattr(exc,'correlation_id',None)))
            if not result['ok']:return error(-32000,result['error_message'],result)
            return {'jsonrpc':'2.0','id':request_id,'result':result['output']}
        if method not in ('message/send','SendMessage'):return error(-32601,'This connection supports synchronous messages only.')
        msg=params.get('message') or {}
        if not isinstance(msg,dict) or set(params)-{'message','configuration'} or any(k in msg for k in ('contextId','taskId')):
            return error(-32602,'Task and context continuation are not supported.')
        config=params.get('configuration',{})
        if not isinstance(config,dict) or set(config)-{'blocking'} or config.get('blocking',True) is not True:
            return error(-32602,'Only blocking informational messages are supported.')
        parts=msg.get('parts')
        if not isinstance(parts,list) or not parts or any(not isinstance(p,dict) or not isinstance(p.get('text'),str) for p in parts):
            return error(-32602,'Text message parts are required.')
        try:result=await gateway.execute(rid,kind=kind,message='\n'.join(p['text'] for p in parts))
        except ExecutionDenied as exc:
            if exc.error_code=='POLICY_DENIED':
                raise HTTPException(403,fields(exc.error_code)['error_message'],
                                    headers={'X-Execution-Error':exc.error_code}) from exc
            return error(-32602,fields(exc.error_code)['error_message'],
                         fields(exc.error_code,getattr(exc,'correlation_id',None)))
        if not result['ok']:return error(-32000,result['error_message'],result)
        parts=[]
        for part in result['output']['parts']:
            if not isinstance(part,dict):continue
            if isinstance(part.get('text'),str):
                parts.append({'text':part['text']} if method=='SendMessage' else {'kind':'text','text':part['text']})
            elif isinstance(part.get('data'),dict):
                parts.append({'data':part['data']} if method=='SendMessage' else {'kind':'data','data':part['data']})
        if not parts:return error(-32000,'The agent returned no supported message output.')
        response={'role':'agent','kind':'message','messageId':secrets.token_hex(16),'parts':parts}
        if method=='SendMessage':response={'message':{'messageId':response['messageId'],'parts':parts,'role':'ROLE_AGENT'}}
        return {'jsonrpc':'2.0','id':request_id,'result':response}

    return router
