"""Independent personal-session reads for the renewed administrator console."""
from fastapi import Header, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool


def install(router, *, store, authorize, admin_token, front=None):
    if front is not None:
        from .bootstrap import configure
        configure(front)

    def operator(request, authorization, x_dashboard):
        from ..gateway.admin_security import check_origin
        check_origin(request)
        user=authorize(request,authorization,x_dashboard)
        if not user.get('is_authenticated_session') or user.get('role') not in ('admin','superadmin'):
            raise HTTPException(403,'A current administrator session is required.')
        return user

    @router.get('/admin/api/v2/gateway/edge-monitor')
    async def monitor(request:Request,hours:int=Query(24),authorization:str|None=Header(default=None),x_dashboard:str|None=Header(default=None)):
        from .output_monitor import dashboard
        from .config import EdgeError
        user=authorize(request,authorization,x_dashboard)
        if not user.get('is_authenticated_session') or user.get('role') not in ('superadmin','admin','operator'):
            raise HTTPException(403,'Use a current staff session with monitoring permission.')
        if hours not in (1,6,24,168):raise HTTPException(400,'Select a supported monitoring window.')
        current=getattr(store,'_edge_gateway_service',None)
        if current is None:return JSONResponse({'available':False,'reason':'not_configured'},headers={'Cache-Control':'private, no-store'})
        try:value=await run_in_threadpool(dashboard,current,hours=hours)
        except Exception:return JSONResponse({'available':False,'reason':'observation_unavailable'},status_code=503,headers={'Cache-Control':'private, no-store'})
        return JSONResponse(value,headers={'Cache-Control':'private, no-store','Vary':'Authorization, X-Dashboard'})

    @router.post('/admin/api/v2/gateway/edge-test/prepare')
    async def prepare_test(request:Request,authorization:str|None=Header(default=None),x_dashboard:str|None=Header(default=None)):
        from .admin_delivery import prepare
        from .router import body,errors
        from .config import EdgeError
        user=operator(request,authorization,x_dashboard)
        current=getattr(store,'_edge_gateway_service',None)
        if current is None:return JSONResponse({'backend':'origin','reason':'EDGE_UNAVAILABLE'},headers={'Cache-Control':'no-store'})
        _,value=await body(request)
        client_origin=request.headers.get('origin') or str(request.url).split('/admin/',1)[0]
        try:answer=await run_in_threadpool(prepare,current,user,client_origin,value)
        except EdgeError as exc:raise HTTPException(exc.status,'The Edge execution could not be prepared.') from None
        return JSONResponse(answer,headers={'Cache-Control':'private, no-store'})

    @router.post('/admin/api/v2/gateway/edge-test/finish')
    async def finish_test(request:Request,authorization:str|None=Header(default=None),x_dashboard:str|None=Header(default=None)):
        from .admin_delivery import finish
        from .router import body
        from .config import EdgeError
        user=operator(request,authorization,x_dashboard)
        current=getattr(store,'_edge_gateway_service',None)
        if current is None:raise HTTPException(503,'The execution state is unavailable.')
        _,value=await body(request)
        if set(value)-{'run_id','recover'} or type(value.get('recover',False)) is not bool:raise HTTPException(400,'Inspect one execution.')
        try:answer=await finish(current,user,value.get('run_id'),recover=value.get('recover',False))
        except EdgeError as exc:raise HTTPException(exc.status,'The execution state could not be confirmed.') from None
        return JSONResponse(answer,headers={'Cache-Control':'private, no-store'})

    @router.get('/admin/api/v2/gateway/edge-delivery')
    async def summary(request: Request, authorization: str | None = Header(default=None),
                      x_dashboard: str | None = Header(default=None)):
        token = authorization[7:].strip() if (authorization or '').startswith('Bearer ') else ''
        if not token or admin_token and token == admin_token:
            raise HTTPException(401, 'An individual administrator session is required.')
        user = authorize(request, authorization, x_dashboard)
        if not user.get('is_authenticated_session') or user.get('role') not in ('superadmin', 'admin', 'operator'):
            raise HTTPException(403, 'This administrator cannot inspect execution delivery.')
        current = getattr(store, '_edge_gateway_service', None)
        if current is None:
            value = {'available': False, 'configured': False, 'reason': 'configuration_invalid' if getattr(store, '_edge_gateway_config_error', False) else 'not_configured'}
        else:
            try:
                value = await run_in_threadpool(current.summary)
            except Exception:
                return JSONResponse({'available': False, 'configured': True, 'reason': 'state_unavailable'},
                                    status_code=503, headers={'Cache-Control': 'private, no-store'})
        return JSONResponse(value, headers={'Cache-Control': 'private, no-store', 'Vary': 'Authorization, X-Dashboard'})
