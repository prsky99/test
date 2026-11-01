"""Two HTTP clients against one disposable app, never the operating service."""
import json
import shutil
import socket
import subprocess
import threading
import time

import httpx
import uvicorn

from agent_market.agent_access.client import DiscoveryClient
from agent_market.concierge.front import create_front_app
from tests.test_agent_adoption import adoption,routing  # noqa: F401


NODE_CLIENT=r'''
const origin=process.argv[1];let session;let sequence=0;
async function rpc(method,params={}) {
  const response=await fetch(origin+'/mcp/compact',{method:'POST',
    headers:{'Content-Type':'application/json',...(session?{'Mcp-Session-Id':session}:{})},
    body:JSON.stringify({jsonrpc:'2.0',id:++sequence,method,params}),signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw Error('HTTP_'+response.status);
  session=response.headers.get('mcp-session-id')||session;
  const value=await response.json();if(value.error)throw Error('RPC_ERROR');return value.result;
}
await rpc('initialize',{protocolVersion:'2025-06-18',capabilities:{},clientInfo:{name:'acceptance-node',version:process.version}});
const listed=await rpc('tools/list');
async function call(name,args={}){
  const value=await rpc('tools/call',{name,arguments:args});
  if(value.isError)throw Error('TOOL_REFUSED');return value.structuredContent;
}
const found=await call('discover',{task:'public documentation search',protocol:'mcp'});
if(!found.items.length)throw Error('NO_MATCH');
const described=await call('describe',{resource_id:found.items[0].id});
const resumed=await call('resume');
if(!described.tools_schema.length||!resumed.recommendations?.length)throw Error('EMPTY_CONTRACT');
console.log(JSON.stringify({runtime:process.version,tools:listed.tools.map(t=>t.name),discover:true,describe:true,resume:true}));
'''


def test_python_and_node_remote_clients_and_payload_measurement(adoption):
    core,v,ids,calls,*_=adoption
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(64)
    origin='http://127.0.0.1:'+str(sock.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(create_front_app(core.front),log_level='critical',lifespan='off'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    deadline=time.monotonic()+8
    try:
        while not server.started and time.monotonic()<deadline:time.sleep(.01)
        assert server.started
        assert shutil.which('node')
        with httpx.Client(base_url=origin,trust_env=False,timeout=10)as http:
            python=DiscoveryClient(http=http);python.connect()
            listed=python.rpc('tools/list')['tools']
            cold=python.discover('public documentation search',protocol='mcp')
            definition=python.describe(cold['items'][0]['id'])
            assert definition['tools_schema']and python.resume()['recommendations']
            samples=[]
            for _ in range(5):
                start=time.perf_counter()
                cached=python.discover('public documentation search',protocol='mcp',known_schema_digests=[definition['schema_digest']])
                samples.append(round((time.perf_counter()-start)*1000,3))
            assert cached['schema_cached']
            legacy=http.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}})
            assert legacy.status_code==200 and legacy.json()['result']['tools']
        node=subprocess.run(['node','--input-type=module','-e',NODE_CLIENT,origin],capture_output=True,text=True,timeout=30,check=True)
        result=json.loads(node.stdout)
        assert result['tools']==[t['name']for t in listed]==['discover','describe','execute','resume','report']
        measurement={'scope':'synthetic local HTTP; five warm samples; not a production SLA',
            'clients':{'python_httpx':True,'node_fetch':result},'legacy_tools_list_bytes':len(legacy.content),
            'compact_tools_list_bytes':len(json.dumps({'tools':listed},separators=(',',':')).encode()),
            'cold_discover_bytes':len(json.dumps(cold,separators=(',',':')).encode()),
            'known_schema_discover_bytes':len(json.dumps(cached,separators=(',',':')).encode()),
            'warm_http_ms':samples,'additional_provider_calls':len(calls),'candidate_cache_enabled':False}
        assert measurement['known_schema_discover_bytes']<measurement['cold_discover_bytes']<=8192
        assert not calls
        print('ADOPTION_MEASUREMENT '+json.dumps(measurement,sort_keys=True))
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()
        assert not thread.is_alive()
