"""Measured public reachability and bounded conversation-retention maintenance."""
import time
from contextlib import closing
from urllib.parse import urlsplit

from .concierge.http_security import bounded_client, outbound_operation

WINDOW_DAYS=30


class AvailabilityMonitor:
    def __init__(self,front,*,clock=time.time,http=None):
        self.front,self.clock,self.http=front,clock,http
        self.next_check=0
    def due(self):return self.clock()>=self.next_check
    def run(self):
        now=self.clock();self.next_check=now+60
        origin=self.front.public_url or 'https://agentconcierge.biz'
        parsed=urlsplit(origin)
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.path not in ('','/'):
            return
        status=None;ok=False;started=time.monotonic()
        try:
            with outbound_operation(5),closing(bounded_client(self.http,timeout=5,headers={'User-Agent':'AgentConciergeAvailability/1.0'})) as client:
                response=client.get(origin.rstrip('/')+'/status.json')
                status=response.status_code
                data=response.json() if status==200 else {}
                ok=status==200 and data.get('service')=='Agent Concierge'
        except (ValueError,TimeoutError,OSError):pass
        except Exception:
            # Network failures become failed observations; never a fabricated success.
            pass
        latency=round((time.monotonic()-started)*1000,1)
        with self.front.store.tx() as db:
            db.execute('INSERT INTO public_availability_checks (checked_at,ok,status_code,latency_ms) VALUES (?,?,?,?)',(now,int(ok),status,latency))
            db.execute('DELETE FROM public_availability_checks WHERE checked_at<?',(now-WINDOW_DAYS*86400,))


class ConversationRetention:
    def __init__(self,book,*,clock=time.time):self.book,self.clock,self.next_check=book,clock,0
    def due(self):return self.clock()>=self.next_check
    def run(self):
        self.next_check=self.clock()+60
        report=self.book.prune_conversations()
        self.next_check=self.clock()+(10 if any(n>=1000 for n in report.values()) else 3600)
        return report


def projection(store,now=None):
    now=time.time() if now is None else now
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
