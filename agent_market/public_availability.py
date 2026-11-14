"""Measured public reachability and bounded conversation-retention maintenance."""
import logging
import os
import time
from contextlib import closing
from urllib.parse import urlsplit

from .concierge.http_security import bounded_client, outbound_operation

WINDOW_DAYS=30
# Aligned with scripts/net_path.py (PM 11-12 net-path report, item 3): both give up after 5 s (curl -m 5 there),
# and net_path calls a 200 slower than 4 s a stall. The public judgement is unchanged (200 within TIMEOUT_S);
# the log now says when a check was slow by the net_path rule, which phase it stopped in, and when the answer
# was a block (403/429: our own edge or app block, or a Cloudflare rule) rather than a path stall.
TIMEOUT_S=5
SLOW_S=4.0
# 11-14: the public name changed from Agent Concierge to AgentValCon (05:27 frontend). Either name means our own
# status page answered; anything else is a wrong page behind the domain.
SERVICE_NAMES=frozenset({'AgentValCon','Agent Concierge'})
BLOCKED=(403,429)
# httpcore trace step names ('<module>.<step>.started|complete|failed') and the phase each one is.
PHASES={'connect_tcp':'tcp','start_tls':'tls','send_request_headers':'send','send_request_body':'send',
        'receive_response_headers':'first_byte','receive_response_body':'body'}
log=logging.getLogger(__name__)


class PhaseTrace:
    """httpcore trace callback: remembers the last phase that started and whether it completed."""
    def __init__(self):self.phase=None;self.done=False
    def __call__(self,event,info):
        step,_,state=event.rpartition('.')
        name=PHASES.get(step.rpartition('.')[2])
        if name is None:return
        if state=='started':self.phase,self.done=name,False
        elif state=='complete':self.phase,self.done=name,True
    def stalled_at(self):
        """The phase a failed request stopped in; 'before_connect' when no connection step started."""
        if self.phase is None:return 'before_connect'
        return self.phase if not self.done else 'after_'+self.phase


class AvailabilityMonitor:
    def __init__(self,front,*,clock=time.time,http=None,local_http=None):
        self.front,self.clock,self.http,self.local_http=front,clock,http,local_http
        self.next_check=0
    def due(self):return self.clock()>=self.next_check
    def run(self):
        now=self.clock();self.next_check=now+60
        origin=self.front.public_url or 'https://agentconcierge.biz'
        parsed=urlsplit(origin)
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.path not in ('','/'):
            return
        status=None;ok=False;started=time.monotonic();trace=PhaseTrace()
        try:
            with outbound_operation(TIMEOUT_S),closing(bounded_client(self.http,timeout=TIMEOUT_S,headers={'User-Agent':'AgentConciergeAvailability/1.0'})) as client:
                response=client.get(origin.rstrip('/')+'/status.json',extensions={'trace':trace})
                status=response.status_code
                data=response.json() if status==200 else {}
                ok=status==200 and data.get('service') in SERVICE_NAMES
        except (ValueError,TimeoutError,OSError):pass
        except Exception:
            # Network failures become failed observations; never a fabricated success.
            pass
        latency=round((time.monotonic()-started)*1000,1)
        if not ok:self.record_origin(status,latency,trace.stalled_at())
        elif latency>SLOW_S*1000:
            log.info('Public availability check slow (%.0f ms over the %.0f s net_path stall line); counted as available',
                     latency,SLOW_S)
        with self.front.store.tx() as db:
            db.execute('INSERT INTO public_availability_checks (checked_at,ok,status_code,latency_ms) VALUES (?,?,?,?)',(now,int(ok),status,latency))
            db.execute('DELETE FROM public_availability_checks WHERE checked_at<?',(now-WINDOW_DAYS*86400,))


    def record_origin(self,status,latency,stalled_at=None):
        """Internal log only: ask the local proxy the same question, to tell an origin problem
        from a network-path problem (Cloudflare edge and tunnel), or a block (403/429) from either.
        The public status is unchanged."""
        origin=os.environ.get('AVAILABILITY_LOCAL_ORIGIN','http://127.0.0.1:8400')
        local=None;started=time.monotonic()
        try:
            host=urlsplit(self.front.public_url or 'https://agentconcierge.biz').hostname or 'agentconcierge.biz'
            with outbound_operation(3),closing(bounded_client(self.local_http,timeout=3,allow_private=True)) as client:
                local=client.get(origin.rstrip('/')+'/status.json',
                                 headers={'User-Agent':'AgentConciergeAvailability/1.0','Host':host}).status_code
        except Exception:
            pass
        local_ms=round((time.monotonic()-started)*1000,1)
        verdict='origin' if local!=200 or local_ms>=3000 else 'blocked' if status in BLOCKED else 'path'
        where='' if status is not None or not stalled_at else '; stopped at '+stalled_at
        log.warning('Public availability check failed (status %s, %.0f ms%s); local origin %s in %.0f ms -> %s problem',
                    status,latency,where,local,local_ms,verdict)
        return verdict


class ConversationRetention:
    def __init__(self,book,*,clock=time.time):self.book,self.clock,self.next_check=book,clock,0
    def due(self):return self.clock()>=self.next_check
    def run(self):
        self.next_check=self.clock()+60
        report=self.book.prune_conversations()
        self.next_check=self.clock()+(10 if any(n>=1000 for n in report.values()) else 3600)
        return report


PROJECTION_SECONDS=30


def projection(store,now=None):
    """Public status from the per-minute probe rows. /status.json is itself the probe target, so the
    default (current) view is reused for PROJECTION_SECONDS: a slow database cannot make the status
    request time out (11-09 20:44-20:56, five 5 s probe timeouts)."""
    if now is None:
        cached=getattr(store,'_availability_projection',None)
        current=time.monotonic()
        if cached and current-cached[0]<PROJECTION_SECONDS:return cached[1]
        value=_projection(store,time.time())
        try:store._availability_projection=(current,value)
        except AttributeError:pass
        return value
    return _projection(store,now)


def _projection(store,now):
    rows=store.query('SELECT COUNT(*) AS n,SUM(ok) AS succeeded,MIN(checked_at) AS first_check,MAX(checked_at) AS last_check,AVG(latency_ms) AS response_ms FROM public_availability_checks WHERE checked_at>=?',(now-WINDOW_DAYS*86400,))
    total=dict(rows[0]);n=total['n']
    recent=store.query('SELECT checked_at,ok,status_code FROM public_availability_checks ORDER BY checked_at DESC LIMIT 120')
    last=recent[0] if recent else None
    state='unknown' if not last or now-last['checked_at']>180 else 'operational' if last['ok'] else 'degraded'
    incidents=[];current=None
    for row in reversed(recent):
        if not row['ok']:
            if current is None:current={'observed_since':row['checked_at'],'last_observed':row['checked_at'],'resolved_at':None,'http_status':row['status_code']};incidents.append(current)
            else:current['last_observed']=row['checked_at'];current['http_status']=row['status_code']
        elif current is not None:current['resolved_at']=row['checked_at'];current=None
    return {'status':state,'availability':{'method':'one public status request per minute; observed check success ratio, not an SLA',
        'window_days':WINDOW_DAYS,'observation_count':n,'availability_percent':round(100*total['succeeded']/n,3) if n else None,
        'first_check':total['first_check'],'last_check':total['last_check'],'average_response_ms':round(total['response_ms'],1) if n else None},
        'recent_incidents':list(reversed(incidents))[:10]}
