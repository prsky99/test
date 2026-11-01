"""Bounded operations APIs with individual staff and separate customer sessions."""
from pathlib import Path
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_admin_control import WorkspaceAdminControl, exact, page, request_id, text
from .workspace_admin_events import audit, emit, execute, rows
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object

BASE = '/admin/api/workspace-operations'


def script_response():
    return Response(Path(__file__).with_name('gateway').joinpath('workspace-operations-admin.js').read_text(),
                    media_type='application/javascript', headers={**no_store(),'X-Content-Type-Options':'nosniff',
                    'Cross-Origin-Resource-Policy':'same-origin','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"})


def router_for(identity, access, *, core=None, public=False):
    core = core or WorkspaceAdminControl(identity, access)
    router = APIRouter(route_class=WorkspaceRoute)
    reads, writes = RateLimiter(180), RateLimiter(30)

    def result(value):
        return JSONResponse({'ok': True, **value}, headers=no_store())

    def session(request: Request):
        authorization = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', authorization):
            raise HTTPException(401, 'Use an individual administrator session.')
        with core.identity.read_tx() as db:
            user = admin_auth.get_session_user(db, authorization[7:], upgrade_legacy=False)
        if not user:
            raise HTTPException(401, 'The administrator session is unavailable.')
        if not (reads if request.method=='GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429,'Please wait before another operations request.',headers={'Retry-After':'10'})
        return SessionActor(user['user_id'],admin_auth.session_reference(authorization[7:]))

    def invoke(method,*args,**kwargs):
        try:
            return result(method(*args,**kwargs))
        except WorkspaceDenied:
            raise HTTPException(403,'The current account or operation is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409,'This request changed. Refresh before trying again.' if public else
                                'Review migration readiness, integrity and the current revision before another action.') from None
        except (WorkspaceInvalid,ValueError,TypeError,KeyError):
            raise HTTPException(400,'Provide the exact supported operations fields.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503,'Support is temporarily unavailable. Please try again.' if public else
                                'Workspace operations storage is temporarily unavailable.',headers={'Retry-After':'5'}) from None

    async def body(request):
        try:
            return await read_object(request,16384)
        except (ValueError,TypeError,TimeoutError,UnicodeError,RecursionError):
            raise HTTPException(400,'Provide one bounded JSON request.') from None

    if public:
        from .customer_identity_service import customer_actor

        def customer(request,write=False):
            if request.headers.get('authorization'):
                raise HTTPException(403,'Use the current customer session.')
            current=customer_actor(request,identity,csrf=write)
            if not (writes if write else reads).allow(current.customer_id):
                raise HTTPException(429,'Please wait before another support request.')
            if not core.enabled: raise HTTPException(503,'Customer support is temporarily unavailable.')
            return current

        def public_case(value):
            return {k:value[k] for k in ('id','workspace_id','subject','status','revision','created','updated')}

        def support_options(current):
            with core.identity.read_tx() as db:
                core.identity._session(db,current.session_ref,current.customer_id)
                return {'workspaces':rows(db,'support_workspaces',(current.customer_id,))}

        def sharing_options(current,case_id):
            with core.identity.read_tx() as db:
                core.identity._session(db,current.session_ref,current.customer_id)
                case=core._case(db,case_id,current.customer_id)
                if case['workspace_id'] is None: raise WorkspaceDenied()
                core.identity.authorize(db,current,case['workspace_id'],'manage')
                return {'drafts':rows(db,'draft_metadata',(case['workspace_id'],)),
                    'disclosures':[item for item in rows(db,'disclosure_list',(current.customer_id,)) if item['case_id']==case_id]}

        def listing(current,cursor,limit):
            page(limit); text(cursor,120,0)
            with core.identity.read_tx() as db:
                core.identity._session(db,current.session_ref,current.customer_id)
                return {'cases':[public_case(x) for x in rows(db,'case_customer',(current.customer_id,cursor,limit))]}

        def detail(current,identity):
            with core.identity.read_tx() as db:
                core.identity._session(db,current.session_ref,current.customer_id)
                value=core._case(db,identity,current.customer_id)
                records=rows(db,'case_public_messages',(identity,));messages=records[:200][::-1]
                for item in messages:
                    item['author']='Agent Concierge support' if item['author'].startswith('staff:') else 'You'
                return {'case':public_case(value),'messages':messages,'messages_truncated':len(records)>200}

        def create(current,value):
            with core.identity.tx() as db:
                core.identity._session(db,current.session_ref,current.customer_id)
                if value.get('workspace_id'):
                    core.identity.authorize(db,current,value['workspace_id'],'read')
                return {'case':public_case(core.create_case_db(db,current.customer_id,value,current.customer_id))}

        def message(current,case_id,value):
            exact(value,('message','request_id'))
            message=text(value['message'],4000); request_id(value['request_id'])
            with core.identity.tx() as db:
                core.identity._session(db,current.session_ref,current.customer_id)
                case=core._case(db,case_id,current.customer_id)
                previous=rows(db,'message_replay',(value['request_id'],))
                if previous:
                    import hashlib
                    from .workspace_admin_events import canonical
                    if (previous[0]['author']!=current.customer_id or previous[0]['case_id']!=case_id
                            or previous[0]['request_digest']!=hashlib.sha256(canonical(value).encode()).hexdigest()): raise WorkspaceConflict()
                    return {'case':public_case(case),'replayed':True}
                import secrets,time
                import hashlib
                from .workspace_admin_events import canonical
                execute(db,'message_insert',('wam_'+secrets.token_hex(16),case_id,current.customer_id,'customer',message,time.time(),value['request_id'],hashlib.sha256(canonical(value).encode()).hexdigest()))
                execute(db,'case_update',('in_progress',case['priority'],case['assigned_to'],time.time(),case_id,case['revision']))
                emit(core.store,db,'case.reopened' if case['status'] in ('resolved','closed') else 'case.updated',
                     customer=current.customer_id,workspace=case['workspace_id'],object_id=case_id)
                audit(db,current.customer_id,'case.customer_message',case_id,'Customer service message')
                return {'case':public_case(core._case(db,case_id,current.customer_id))}

        @router.get('/api/customer-support/cases')
        def customer_cases(request:Request,cursor:str='',limit:int=50):
            return invoke(listing,customer(request),cursor,limit)

        @router.get('/api/customer-support/options')
        def customer_options(request:Request): return invoke(support_options,customer(request))

        @router.get('/api/customer-support/cases/{case_id}/sharing-options')
        def customer_sharing(case_id:str,request:Request): return invoke(sharing_options,customer(request),case_id)

        @router.get('/api/customer-support/cases/{case_id}')
        def customer_case(case_id:str,request:Request):
            return invoke(detail,customer(request),case_id)

        @router.post('/api/customer-support/cases')
        async def customer_create(request:Request):
            current=customer(request,True)
            return await run_in_threadpool(invoke,create,current,await body(request))

        @router.post('/api/customer-support/cases/{case_id}/messages')
        async def customer_message(case_id:str,request:Request):
            current=customer(request,True)
            return await run_in_threadpool(invoke,message,current,case_id,await body(request))

        @router.get('/customer/support')
        def support_page():
            from .workspace_support_view import page_for
            return page_for()

        @router.post('/api/customer-support/cases/{case_id}/disclosures')
        async def disclosure(case_id:str,request:Request):
            current=customer(request,True)
            return await run_in_threadpool(invoke,core.disclosure,current,case_id,await body(request))

        @router.post('/api/customer-support/disclosures/{disclosure_id}/revoke')
        async def revoke_disclosure(disclosure_id:str,request:Request):
            current=customer(request,True)
            return await run_in_threadpool(invoke,core.disclosure_revoke,current,disclosure_id,await body(request))
        return router

    @router.get(BASE+'/options')
    def options(actor=Depends(session)): return invoke(core.options,actor)

    @router.get(BASE+'/overview')
    def overview(hours:int=24,actor=Depends(session)): return invoke(core.overview,actor,hours)

    @router.get(BASE+'/customers')
    def customers(cursor:str='',q:str='',limit:int=50,actor=Depends(session)):
        return invoke(core.customers,actor,cursor,q,limit)

    @router.get(BASE+'/customers/{customer_id}')
    def one_customer(customer_id:str,actor=Depends(session)): return invoke(core.customer,actor,customer_id)

    @router.get(BASE+'/customers/{customer_id}/timeline')
    def timeline(customer_id:str,before:float|None=None,cursor:str='~',limit:int=50,actor=Depends(session)):
        return invoke(core.events,actor,customer_id,before,cursor,limit=limit)

    @router.get(BASE+'/events')
    def events(before:float|None=None,cursor:str='~',hours:int=24,limit:int=50,actor=Depends(session)):
        return invoke(core.events,actor,before=before,cursor=cursor,hours=hours,limit=limit)

    @router.get(BASE+'/organizations')
    def organizations(cursor:str='',limit:int=50,actor=Depends(session)):
        return invoke(core.organizations,actor,cursor,limit)

    @router.get(BASE+'/operations/{operation_id}')
    def operation(operation_id:str,actor=Depends(session)): return invoke(core.operation,actor,operation_id)

    @router.get(BASE+'/organizations/{workspace}/operations')
    def operations(workspace:str,actor=Depends(session)): return invoke(core.operations,actor,workspace)

    @router.get(BASE+'/credits/reconciliation')
    def reconciliation(cursor:str='',limit:int=25,actor=Depends(session)):
        return invoke(core.reconciliation,actor,cursor,limit)

    @router.get(BASE+'/cases')
    def cases(customer:str|None=None,cursor:str='',limit:int=50,actor=Depends(session)):
        return invoke(core.cases,actor,customer,cursor,limit)

    @router.get(BASE+'/cases/{case_id}')
    def case(case_id:str,actor=Depends(session)): return invoke(core.case,actor,case_id)

    @router.post(BASE+'/customers/{customer_id}/cases')
    async def create_case(customer_id:str,request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.create_case,actor,customer_id,await body(request))

    @router.post(BASE+'/cases/{case_id}/actions')
    async def update_case(case_id:str,request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.case_action,actor,case_id,await body(request))

    @router.post(BASE+'/cases/{case_id}/links')
    async def link_case(case_id:str,request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.link_case,actor,case_id,await body(request))

    @router.get(BASE+'/commands')
    def commands(actor=Depends(session)): return invoke(core.commands,actor)

    @router.get(BASE+'/commands/{command_id}')
    def command_detail(command_id:str,actor=Depends(session)): return invoke(core.command_detail,actor,command_id)

    @router.post(BASE+'/commands')
    async def command(request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.command,actor,await body(request))

    @router.post(BASE+'/commands/{command_id}/approve')
    async def approve(command_id:str,request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.approve,actor,command_id,await body(request))

    @router.post(BASE+'/commands/{command_id}/cancel')
    async def cancel_command(command_id:str,request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.cancel_command,actor,command_id,await body(request))

    @router.get(BASE+'/incidents')
    def incidents(actor=Depends(session)): return invoke(core.incidents,actor)

    @router.post(BASE+'/incidents')
    async def incident(request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.incident,actor,await body(request))

    @router.post(BASE+'/incidents/{incident_id}/actions')
    async def incident_action(incident_id:str,request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,core.incident,actor,await body(request),incident_id)

    @router.get(BASE+'/audit')
    def audits(actor=Depends(session)): return invoke(core.audits,actor)

    @router.get(BASE+'/customers/{customer_id}/disclosures')
    def disclosures(customer_id:str,actor=Depends(session)): return invoke(core.disclosures,actor,customer_id)

    @router.post(BASE+'/disclosures/{disclosure_id}/read')
    async def read_disclosure(disclosure_id:str,request:Request,actor=Depends(session)):
        if await body(request)!={'confirm':'READ'}: raise HTTPException(400,'Confirm the scoped content inspection.')
        return await run_in_threadpool(invoke,core.disclosure_read,actor,disclosure_id)
    # Both prefixes use the exact same handlers, dependencies and current domain
    # authority. The public customer router returned above never receives aliases.
    for source in list(router.routes):
        if source.path == BASE or source.path.startswith(BASE+'/'):
            router.add_api_route('/admin/api/v2/customers/operations'+source.path[len(BASE):],
                source.endpoint, methods=list(source.methods), dependencies=source.dependencies,
                response_class=source.response_class, response_model=source.response_model,
                route_class_override=WorkspaceRoute)
    return router
