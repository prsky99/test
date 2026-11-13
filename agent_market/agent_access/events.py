"""Durable change publication shared by public feeds and verified dependencies."""
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime,timezone

from ..capability_registry import digest,Registry
from ..concierge.connections import public_agent
from ..concierge.discovery_state import execution_state
from .storage import transaction,ready,enqueue,identity

log=logging.getLogger(__name__)
# 11-13 (PM 23:0x, plan A): pending rows read per round. The round still evaluates at most `limit` rows; the wider window
# only lets it mark the empty repeats of a resource it already evaluated (96% of the 508k backlog). It starts at 200 and
# grows by 50 up to 500 while a round's transaction stays under a quarter of the 5 s statement limit, and halves back
# toward 200 when it passes half of it.
WINDOW_START,WINDOW_MAX,WINDOW_STEP=200,2000,100
GROW_BELOW_S,SHRINK_ABOVE_S=1.75,3.0
# 11-14 (PM 03:1x, plan A2): after plan A the backlog held at 512k and 102 h behind: 32 evaluations a round, one round a
# tick (19 rounds in 10 minutes, slowest 0.54 s) barely passed the inflow. A round now evaluates until EVAL_BUDGET_S has
# passed or EVAL_MAX rows (the same oldest-first order, one evaluation per resource a round), and while a round fills its
# whole window (a backlog) the tick runs further rounds, each its own transaction, for up to TICK_BUDGET_S.
EVAL_MAX,EVAL_BUDGET_S=256,1.0
TICK_ROUNDS,TICK_BUDGET_S=8,6.0

EVENT_TYPES=('verified','withdrawn','execution_verification_changed','health_changed','schema_changed','quality_changed')


class Events:
    def __init__(self,front):
        self.front=front;self.store=front.store
        self.window=WINDOW_START;self.backlogged=False;self.rounds={'rounds':0,'evaluated':0,'superseded':0,'published':0,'max_s':0.0,'since':time.monotonic()}
        self.key=hmac.new(front.updates.key,b'adoption-feed-cursor-v1',hashlib.sha256).digest()

    def sweep(self,limit=32):
        if not ready(self.store):return 0
        rows=self.store.query('SELECT resource_id,version_id FROM adoption_publications WHERE expires<=? OR updated<? ORDER BY updated LIMIT ?',
                             (time.time(),time.time()-60,limit))
        with transaction(self.store)as db:
            for row in rows:enqueue(self.store,db,row['resource_id'],'recheck',row['version_id'],int(time.time()/60))
        return len(rows)

    def publish(self,limit=None,window=None,budget=None):
        """Store.tx serializes publishers; sequence and projection commit together.

        11-13 (PM, plan A): the round reads up to `window` pending rows, oldest first, and evaluates at most `limit`.
        A row without an observation payload for a resource this round already evaluated is marked ignored without a
        second evaluation: the outcome is decided by the resource's current state, which a second evaluation in the
        same round reads unchanged, so it would be ignored one by one too. The published events, their ids and their
        order are those of the one-by-one way; only the empty repeats are settled sooner."""
        if not ready(self.store):return 0
        if limit is None:limit,budget=EVAL_MAX,EVAL_BUDGET_S if budget is None else budget
        window=max(limit,int(self.window if window is None else window))
        started=time.monotonic();changed=evaluated=superseded=0;self.backlogged=False
        with transaction(self.store)as db:
            pending=db.execute("SELECT * FROM adoption_changes WHERE status='pending' ORDER BY created,id LIMIT ?",(window,)).fetchall()
            self.backlogged=len(pending)>=window   # more pending rows beyond this round's window
            seq=int((self.store.get_meta('adoption_published_sequence')or{}).get('value',0))
            done=set()
            for raw in pending:
                row=dict(raw);rid=row['resource_id']
                if not row['payload'] and rid in done:
                    db.execute("UPDATE adoption_changes SET status='ignored' WHERE id=?",(row['id'],));superseded+=1;continue
                if evaluated>=limit or budget is not None and evaluated and time.monotonic()-started>budget:continue
                evaluated+=1;done.add(rid)
                resource=self.store.resource(rid)
                observation=json.loads(row['payload'])if row['payload']else{}
                state=execution_state(self.store,resource)
                before=db.execute('SELECT * FROM adoption_publications WHERE resource_id=?',(rid,)).fetchone()
                projection={'execution':state,'active':bool(resource and resource.get('active')),
                    'health':resource.get('health_status')if resource else None,'grade':resource.get('eval_grade')if resource else None}
                signature=digest(projection)
                execution_observation=observation.get('scope')=='execution'
                health_observation=observation.get('scope')=='health'
                if before and before['signature']==signature and not (execution_observation or health_observation)or not before and not state['verified']:
                    if before:db.execute('UPDATE adoption_publications SET updated=?,expires=? WHERE resource_id=?',
                        (time.time(),state['expires_at']if state['verified']else time.time()+3600,rid))
                    db.execute("UPDATE adoption_changes SET status='ignored' WHERE id=?",(row['id'],));continue
                seq+=1;now=time.time();previous=json.loads(before['state'])if before else{}
                event=('withdrawn'if not projection['active']else
                    'schema_changed'if before and before['version_id']!=state['version_id']else
                    'health_changed'if before and (health_observation or previous.get('health')!=projection['health'])else
                    'execution_verification_changed'if before and (execution_observation or previous.get('execution')!=state)else
                    'quality_changed'if before else'verified')
                card=public_agent({'id':rid,'kind':resource['kind'],'name':str(resource.get('name')or'Agent')[:120]},resource=resource)if resource else {'id':rid}
                payload={'resource_id':rid,'protocol':resource.get('kind')if resource else None,
                    'event_type':event,'version_id':state['version_id'],'verified':state['verified'],
                    'verified_at':state['verified_at'],'expires_at':state['expires_at'],'evidence_scope':'execution',
                    'url':card.get('url'),'name':card.get('name','Agent'),'observed_at':now}
                if execution_observation:
                    payload['recorded_outcome']=observation['outcome']
                    payload['evidence_finished_at']=observation['finished']
                    payload['observed_version_id']=row['version_id']
                if health_observation:
                    payload['recorded_health']=observation['status']
                    payload['health_observed_at']=observation['finished']
                db.execute('INSERT INTO adoption_publications VALUES (?,?,?,?,?,?,?) ON CONFLICT(resource_id) DO UPDATE SET signature=excluded.signature,expires=excluded.expires,version_id=excluded.version_id,verified=excluded.verified,updated=excluded.updated,state=excluded.state',
                    (rid,signature,state['expires_at']if state['verified']else now+3600,state['version_id'],int(state['verified']),now,json.dumps(projection)))
                db.execute("UPDATE adoption_changes SET status='published',published_seq=?,payload=? WHERE id=?",(seq,json.dumps(payload),row['id']))
                changed+=1
            db.execute('INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('adoption_published_sequence',json.dumps({'value':seq})))
        self._paced(time.monotonic()-started,window,evaluated,superseded,changed)
        return changed

    def _paced(self,elapsed,window,evaluated,superseded,changed):
        """Adjust the window from this round's time and log a summary every ten minutes (11-13 PM plan A)."""
        if elapsed<GROW_BELOW_S and window>=self.window:self.window=min(WINDOW_MAX,self.window+WINDOW_STEP)
        elif elapsed>SHRINK_ABOVE_S:self.window=max(WINDOW_START,self.window//2)
        r=self.rounds;r['rounds']+=1;r['evaluated']+=evaluated;r['superseded']+=superseded;r['published']+=changed
        r['max_s']=max(r['max_s'],elapsed)
        if time.monotonic()-r['since']>=600:
            log.info('Change feed rounds: %d, evaluated %d, superseded %d, published %d, slowest %.2f s, window now %d',
                     r['rounds'],r['evaluated'],r['superseded'],r['published'],r['max_s'],self.window)
            self.rounds={'rounds':0,'evaluated':0,'superseded':0,'published':0,'max_s':0.0,'since':time.monotonic()}

    def cursor(self,snapshot,after,protocol,expires=None):
        # A fixed UTC-hour boundary keeps equivalent pages conditionally cacheable.
        expires=expires or (int(time.time())//3600+1)*3600
        raw=json.dumps([snapshot,after,protocol,expires],separators=(',',':'))
        import base64
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')+'.'+hmac.new(self.key,raw.encode(),hashlib.sha256).hexdigest()

    def feed(self,protocol=None,cursor=None,limit=30):
        if protocol not in (None,'a2a','mcp','x402')or type(limit)is not int or not 1<=limit<=100:raise ValueError('INVALID_INPUT')
        snapshot=int((self.store.get_meta('adoption_published_sequence')or{}).get('value',0));after=0;expires=None
        if cursor:
            import base64
            try:
                if type(cursor)is not str or len(cursor)>512:raise ValueError()
                encoded,signature=cursor.split('.')
                raw=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)).decode()
                if not hmac.compare_digest(signature,hmac.new(self.key,raw.encode(),hashlib.sha256).hexdigest()):raise ValueError()
                fixed,after,scope,expires=json.loads(raw)
                if (type(fixed)is not int or type(after)is not int or type(expires)is not int or
                        not 0<=after<=fixed<=snapshot or scope!=protocol or not time.time()<expires<=time.time()+3600):raise ValueError()
                snapshot=fixed
            except (ValueError,TypeError,KeyError):raise ValueError('INVALID_CURSOR')from None
            first=self.store.query("SELECT MIN(published_seq) AS first_seq FROM adoption_changes WHERE status='published' AND created>?",(time.time()-30*86400,))[0]['first_seq']
            if first is not None and after<int(first)-1 or first is None and after<snapshot:
                raise ValueError('RESYNC_REQUIRED')
        rows=self.store.query("SELECT * FROM adoption_changes WHERE status='published' AND published_seq>? AND published_seq<=? AND created>? ORDER BY published_seq LIMIT 500",
                              (after,snapshot,time.time()-30*86400))
        from .projection import current_states
        scoped=[r for r in rows if (json.loads(r['payload'])['protocol']==protocol if protocol else json.loads(r['payload'])['protocol']in('a2a','mcp'))][:limit]
        _,states=current_states(self.store,[r['resource_id']for r in scoped])
        items=[];last=after;more=False
        for row in rows:
            data=json.loads(row['payload'])
            if protocol and data['protocol']!=protocol or protocol is None and data['protocol']not in ('a2a','mcp'):
                last=row['published_seq'];continue
            if len(items)==limit:more=True;break
            current=states.get(data['resource_id'],{'verified':False,'version_id':None,'verified_at':None,'expires_at':None})
            data['currently_verified']=bool(current['verified']and current['version_id']==data['version_id'])
            data['current_verified_at']=current['verified_at'];data['current_expires_at']=current['expires_at']
            stamp=datetime.fromtimestamp(data['observed_at'],timezone.utc).isoformat()
            items.append({'id':'ac_event_'+row['id'],'url':data.get('url')or'https://agentconcierge.biz/#explore',
                'title':'Agent verification update','content_text':'Recorded execution verification changed. Revalidate before execution.',
                'date_published':stamp,'_agentconcierge':data})
            last=row['published_seq']
        if len(rows)==500:more=True
        result={'version':'https://jsonfeed.org/version/1.1','title':'Agent Concierge verification changes',
            'home_page_url':'https://agentconcierge.biz/','feed_url':'https://agentconcierge.biz/api/feed/verified.json','items':items}
        if more:result['_next_cursor']=self.cursor(snapshot,last,protocol,expires)
        return result

    def dependency(self,owner,watch_id,rid,*,authorized=False,notice=None,version_id=None,contract_id=None,event_types=None):
        if authorized is not True or notice!='agent-dependency-watch-v1':raise ValueError('AUTHORIZATION_REQUIRED')
        if (type(watch_id)is not str or not re.fullmatch('tw_[0-9a-f]{32}',watch_id)or
                type(rid)is not int or not 0<rid<2**31 or contract_id is not None and type(contract_id)is not str):
            raise ValueError('INVALID_INPUT')
        row=self.front.updates._get(watch_id,owner)
        if row['state']!='active'or not self.front.updates.admin_summary(row)['permission_current']:raise ValueError('AUTHORIZATION_REQUIRED')
        resource=self.store.resource(rid)
        if not resource:raise ValueError('NOT_FOUND')
        version=Registry(self.store).current(resource,create=False)
        current_version=version['id']if version else None
        if version_id is not None and version_id!=current_version:raise ValueError('SCHEMA_CHANGED')
        if contract_id is not None:
            approved=self.store.query('SELECT contract_id FROM capability_approvals WHERE version_id=?',(current_version,))
            if contract_id not in [r[0]for r in approved]:raise ValueError('UNSUPPORTED_CONTRACT')
        types=list(EVENT_TYPES)if event_types is None else event_types
        if (type(types)is not list or not 1<=len(types)<=len(EVENT_TYPES)or
                any(type(item)is not str or item not in EVENT_TYPES for item in types)or len(set(types))!=len(types)):
            raise ValueError('INVALID_INPUT')
        types=sorted(types)
        with transaction(self.store)as db:
            old=db.execute('SELECT * FROM adoption_dependencies WHERE watch_id=? AND resource_id=?',(watch_id,rid)).fetchone()
            if old and (old['version_id']!=current_version or old['contract_id']!=contract_id or json.loads(old['event_types'])!=types):
                raise ValueError('IDEMPOTENCY_CONFLICT')
            db.execute('INSERT OR IGNORE INTO adoption_dependencies(id,owner,watch_id,resource_id,created,version_id,contract_id,event_types) VALUES (?,?,?,?,?,?,?,?)',
                       (identity('adw'),owner,watch_id,rid,time.time(),current_version,contract_id,json.dumps(types)))
            db.execute('INSERT INTO agent_task_permissions(watch_id,visitor_id,action,purpose,notice_version,at) VALUES (?,?,?,?,?,?)',
                       (watch_id,owner,'dependency_registered','task_updates',notice,time.time()))
        return {'registered':True,'resource_id':rid,'version_id':current_version,'contract_id':contract_id,
                'event_types':types,'delivery_authorized_by':'existing_verified_task_watch'}

    def notify(self,limit=32):
        if not ready(self.store):return 0
        count=0
        dependencies=self.store.query('SELECT * FROM adoption_dependencies WHERE active=1 ORDER BY last_seq LIMIT ?',(limit,))
        for dependency in dependencies:
            try:
                watch=self.front.updates._get(dependency['watch_id'],dependency['owner'])
                allowed=watch['state']=='active'and self.front.updates.admin_summary(watch)['permission_current']
            except ValueError:allowed=False
            with transaction(self.store)as db:
                if not allowed:
                    db.execute('UPDATE adoption_dependencies SET active=0 WHERE id=?',(dependency['id'],));continue
                changes=db.execute("SELECT * FROM adoption_changes WHERE resource_id=? AND status='published' AND published_seq>? ORDER BY published_seq LIMIT 30",
                                   (dependency['resource_id'],dependency['last_seq'])).fetchall()
                for change in changes:
                    changed=json.loads(change['payload'])
                    if changed['event_type']not in json.loads(dependency['event_types']):
                        db.execute('UPDATE adoption_dependencies SET last_seq=? WHERE id=?',(change['published_seq'],dependency['id']))
                        continue
                    payload={'type':'dependency_update','purpose':'task_updates','schema_version':1,
                        'message':'A watched agent changed. Revalidate before execution.',
                        'resource_id':dependency['resource_id'],'event_id':change['id'],'event_type':changed['event_type'],
                        'watched_version':dependency['version_id'],'current_version':changed['version_id'],
                        'contract_id':dependency['contract_id'],'return_url':'https://agentconcierge.biz/#explore'}
                    seal=hmac.new(self.key,(dependency['id']+':'+json.dumps(payload,sort_keys=True)+':'+str(watch['sealed'])).encode(),hashlib.sha256).hexdigest()
                    event_key='dependency:'+dependency['id']+':'+seal
                    if db.execute('SELECT 1 FROM agent_task_events WHERE watch_id=? AND evidence=?',(watch['id'],event_key)).fetchone():continue
                    db.execute('INSERT INTO agent_task_events(id,watch_id,created,payload,status,next_attempt,evidence) VALUES (?,?,?,?,?,?,?)',
                        (identity('te'),watch['id'],time.time(),json.dumps(payload),'ready'if watch['channel']=='poll'else'pending',time.time(),event_key))
                    db.execute('UPDATE adoption_dependencies SET last_seq=? WHERE id=?',(change['published_seq'],dependency['id']))
                    count+=1
        return count

    def catch_up(self,rounds=TICK_ROUNDS,budget=TICK_BUDGET_S):
        """One round, and more while a round reads a full window (a backlog), within the tick's time budget."""
        started=time.monotonic();changed=0
        for _ in range(max(1,rounds)):
            changed+=self.publish()
            if not self.backlogged or time.monotonic()-started>budget:break
        return changed

    def tick(self):
        self.sweep();self.catch_up();count=self.notify()
        with transaction(self.store)as db:
            db.execute("DELETE FROM adoption_changes WHERE id IN (SELECT id FROM adoption_changes WHERE status IN ('ignored','published') AND created<? LIMIT 100)",(time.time()-30*86400,))
            db.execute("UPDATE adoption_preparations SET sealed='' WHERE id IN (SELECT p.id FROM adoption_preparations p WHERE p.created<? AND p.sealed!='' AND NOT EXISTS(SELECT 1 FROM adoption_operations o WHERE o.preparation_id=p.id AND o.status IN ('prepared','dispatched')) LIMIT 100)",(time.time()-86400,))
            db.execute("UPDATE adoption_operations SET sealed=NULL WHERE id IN (SELECT id FROM adoption_operations WHERE status IN ('succeeded','failed','cancelled') AND updated<? AND sealed IS NOT NULL LIMIT 100)",(time.time()-86400,))
        return count

    def delivery_valid(self,watch,event,payload):
        if payload.get('type')!='dependency_update'or payload.get('purpose')!='task_updates':return False
        proof=str(event.get('evidence')or'')
        parts=proof.split(':')
        if len(parts)!=3 or parts[0]!='dependency':return False
        dep=self.store.query('SELECT * FROM adoption_dependencies WHERE id=? AND owner=? AND watch_id=? AND active=1',
                             (parts[1],watch['visitor_id'],watch['id']))
        if not dep or payload.get('resource_id')!=dep[0]['resource_id']:return False
        expected=hmac.new(self.key,(parts[1]+':'+json.dumps(payload,sort_keys=True)+':'+str(watch['sealed'])).encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,parts[2])
