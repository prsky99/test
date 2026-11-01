"""Small synchronous discovery client; execution POSTs are never retried."""
import time
import random
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import httpx


class ClientError(ValueError):
    pass


class DiscoveryClient:
    def __init__(self,*,http=None,sleep=time.sleep,clock=time.monotonic,jitter=random.random,cancelled=lambda:False):
        self.http=http or httpx.Client(base_url='https://agentconcierge.biz',verify=True,trust_env=False,follow_redirects=False,timeout=20)
        self.owned=http is None;self.sleep=sleep;self.clock=clock;self._session=None;self._sequence=0
        self.jitter=jitter;self.cancelled=cancelled

    def __repr__(self):return '<AgentConciergeDiscoveryClient>'

    def close(self):
        if self.owned:self.http.close()

    def _request(self,method,path,**kwargs):
        headers={'Mcp-Session-Id':self._session}if self._session else{}
        if method=='GET'and path.startswith('/api/agent/v1/'):headers['X-Visitor-Token']=self._session or''
        deadline=self.clock()+30
        for attempt in range(3 if method=='GET'else 1):
            if self.cancelled():raise ClientError('CANCELLED')
            remaining=deadline-self.clock()
            if remaining<=0:raise ClientError('DEADLINE_EXCEEDED')
            response=self.http.request(method,path,headers=headers,timeout=min(20,remaining),**kwargs)
            if method=='GET'and response.status_code in (429,503)and attempt<2:
                raw=response.headers.get('retry-after','')
                try:delay=float(raw)
                except ValueError:
                    try:delay=(parsedate_to_datetime(raw)-datetime.now(timezone.utc)).total_seconds()
                    except (TypeError,ValueError,OverflowError):delay=2**attempt+.25*self.jitter()
                delay=max(0,min(30,delay,deadline-self.clock()))
                if self.cancelled():raise ClientError('CANCELLED')
                self.sleep(delay);continue
            if response.status_code>=400:raise ClientError('HTTP_'+str(response.status_code))
            token=response.headers.get('mcp-session-id')or response.headers.get('x-visitor-token')
            if token:self._session=token
            return response
        raise ClientError('SERVICE_BUSY')

    def rpc(self,method,params=None):
        self._sequence+=1
        response=self._request('POST','/mcp/compact',json={'jsonrpc':'2.0','id':self._sequence,'method':method,'params':params or{}})
        body=response.json()
        if body.get('id')!=self._sequence or'error'in body:raise ClientError('PROTOCOL_ERROR')
        return body['result']

    def connect(self):
        return self.rpc('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'agent-concierge-python','version':'1.0.0'}})

    def call(self,name,arguments=None):
        if self._session is None:self.connect()
        result=self.rpc('tools/call',{'name':name,'arguments':arguments or{}})
        if result.get('isError'):raise ClientError((result.get('structuredContent')or{}).get('error_code','REQUEST_REFUSED'))
        return result['structuredContent']

    def discover(self,task,**kwargs):return self.call('discover',{'task':task,**kwargs})
    def describe(self,resource_id,**kwargs):return self.call('describe',{'resource_id':resource_id,**kwargs})
    def resume(self):return self.call('resume')
    def report(self,resource_id,ok,**kwargs):return self.call('report',{'resource_id':resource_id,'ok':ok,**kwargs})
    def execute(self,preparation_id,grant,idempotency_key):
        return self.call('execute',{'action':'run','preparation_id':preparation_id,'grant':grant,'idempotency_key':idempotency_key})
    def status(self,operation_id):return self.call('execute',{'action':'status','operation_id':operation_id})
    def cancel(self,operation_id):return self.call('execute',{'action':'cancel','operation_id':operation_id})
    def feed(self,**params):return self._request('GET','/api/feed/verified.json',params=params).json()
