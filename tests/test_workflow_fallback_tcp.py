"""Actual loopback HTTP failover, not public-provider independence evidence."""
import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from agent_market.collector import usage
from agent_market.gateway.store import Store
from agent_market.concierge.proxy import McpProxy
from agent_market.capability_contracts import run_test
from agent_market.capability_registry import Registry
from agent_market.workflows import WorkflowRuntime
from tests.test_workflow_fallback import tool, output, config, NOTICE
from tests.test_workflow_runtime import node, save, wait


class Provider:
    def __init__(self, label, *, tools=None, result_factory=None):
        self.label, self.calls, self.requests = label, [], []
        self.tools = tools if tools is not None else [tool()]
        self.result_factory = result_factory
        provider = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method = body['method']; provider.requests.append(method)
                if method.startswith('notifications/'):
                    self.send_response(204); self.end_headers(); return
                if method == 'initialize':
                    value = {'protocolVersion':body['params']['protocolVersion'],'capabilities':{'tools':{}},'serverInfo':{'name':provider.label,'version':'1'}}
                elif method == 'tools/list': value = {'tools':provider.tools}
                elif method == 'tools/call':
                    provider.calls.append(body['params']['arguments'])
                    if provider.result_factory:value=provider.result_factory(body['params']['arguments'])
                    else:
                        value = output()
                        value['structuredContent']['items'][0]['title'] = provider.label + ': ' + body['params']['arguments']['query']
                else: value = {}
                raw = json.dumps({'jsonrpc':'2.0','id':body['id'],'result':value}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()
        self.stopped = False
    def close(self):
        if not self.stopped:
            self.server.shutdown();self.server.server_close();self.thread.join(3);self.stopped=True


class LoopbackRoutes(httpx.BaseTransport):
    """Test-only routing; no production resolver or SSRF policy is modified."""
    def __init__(self, providers):
        self.providers = providers;self.network = httpx.HTTPTransport(retries=0)
    def handle_request(self, request):
        provider = self.providers[request.url.host]
        url = request.url.copy_with(scheme='http', host='127.0.0.1', port=provider.server.server_address[1])
        local = httpx.Request(request.method,url,headers=request.headers,content=request.content,extensions=request.extensions)
        return self.network.handle_request(local)
    def close(self):self.network.close()


def test_actual_tcp_primary_shutdown_routes_once_to_alternative(tmp_path, monkeypatch):
    a, b = Provider('primary'), Provider('alternative')
    client = httpx.Client(transport=LoopbackRoutes({'primary.example':a,'alternate.example':b}))
    store = Store(str(tmp_path/'live-tcp.sqlite3'))
    rt = WorkflowRuntime(store, McpProxy(store, allow_private=True, http=client))
    ids = []
    try:
        for host in ('primary.example','alternate.example'):
            rid=store.upsert_resource({'key':'tcp-test:'+host,'kind':'mcp','source':'isolated-test','name':host,'description':'Public documentation test','category':'dev_tools','url':'https://'+host+'/mcp','price_usdc':0,'details':{}})
            tools=[tool()];store.record_usage(rid,usage.compact_tools(tools),usage.tools_hash(usage.compact_tools(tools)),{},None,{'ok':True},full_tools=tools)
            with store.tx() as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
            registry=Registry(store);registry.approve(store.resource(rid),'docs.search.v1','search_docs')
            async def runner(identity,**kwargs):
                value=rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
                return {'execution_succeeded':value.get('ok') is True,'simulated':False,'output':value.get('result')}
            with ThreadPoolExecutor(max_workers=1) as pool:
                value=pool.submit(lambda:asyncio.run(run_test(registry,store.resource(rid),'docs.search.v1',{'query':'network verification','language':'en','limit':2},runner))).result(timeout=10)
            assert value['ok'],value
            ids.append(rid)
        wf=save(store,[node('search',resource_id=ids[0],tool='search_docs',input={'query':'network verification','language':'en','limit':2})],name='Isolated real TCP failover')
        config(rt,wf,ids)
        assert wait(rt,rt.submit(wf))['status']=='succeeded'
        config(rt,wf,ids,'canary');rt.fallback.set_control({'enabled':True,'revision':0},1)
        monkeypatch.setattr(rt.fallback,'sample',lambda _:0)  # Selection only in this isolated DB.
        a.calls.clear();b.calls.clear();a.close()
        result=wait(rt,rt.submit(wf,allow_fallback=True,fallback_notice=NOTICE))
        assert result['status']=='succeeded',result
        assert not a.calls and len(b.calls)==1
        item=result['node_results'][0]
        assert item['fallback_used'] and item['resource_id']==ids[1] and item['attempts']==2
        decisions=rt.fallback.decisions(result['run_id'])
        assert decisions['decisions'][0]['decision']=='alternate'
        assert [v['status'] for v in decisions['attempts']]==['failed','succeeded']
        report={'checked_at':time.time(),'scope':'Two isolated loopback HTTP providers; not operating or independent public providers.',
                'primary_listener_closed':a.stopped,'primary_business_calls_after_shutdown':len(a.calls),
                'alternative_business_calls':len(b.calls),'result':result['status'],'fallback_used':item['fallback_used'],
                'execution_outcome':result['execution_outcome'],'attempt_statuses':[v['status'] for v in decisions['attempts']],
                'production_activation':False,'public_provider_business_calls':0}
        Path('reports/agent-fallback-validation-2026-10-24/tcp-failover.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:
        for f in rt.futures.values():f.result(timeout=5)
        a.close();b.close();client.close();store._db.close()
