"""Individual relationship workbench using recorded chat and permission facts."""
import json
import time

from .sanitizer import sanitize_text
from ..concierge.token_hygiene import redact_visitor_tokens
from ..concierge.task_updates import NOTICE_VERSION, MARKETING_NOTICE

STATES = ('new','reviewing','waiting','resolved','archived')


def decoded(value):
    try:
        data=json.loads(value or '{}')
        return data if isinstance(data,dict) else {}
    except (ValueError,TypeError):
        return {}


def safe_text(value,limit):
    if not isinstance(value,str) or len(value)>limit:
        raise ValueError('Invalid text length.')
    return redact_visitor_tokens(sanitize_text(value,max_length=limit)).strip()


class VisitorDesk:
    def __init__(self,store,updates=None):
        self.store,self.updates=store,updates

    def list(self,q='',contact='all',protocol='',case_state='',offset=0,limit=100,tier='',source='all'):
        if self.updates:
            self.updates.maintain()
        native = getattr(self.store, 'visitor_desk_list', None)
        if callable(native):
            return native(q,contact,protocol,case_state,offset,limit,tier,source)
        now=time.time()
        # Values are bound. Only fixed filter fragments are composed here.
        base="""WITH base AS (
          SELECT v.id,v.name,v.channel,v.user_agent,v.first_seen,v.last_seen,v.visits,v.visit_days,v.messages,v.tier,
            (SELECT task FROM agent_interests i WHERE i.visitor_id=v.id ORDER BY updated DESC LIMIT 1) AS last_task,
            (SELECT kind FROM agent_interests i WHERE i.visitor_id=v.id ORDER BY updated DESC LIMIT 1) AS requested_protocol,
            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.state='active' AND w.expires>?) AS active_watches,
            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.channel!='poll' AND w.sealed IS NOT NULL) AS inbox_contacts,
            (SELECT COUNT(*) FROM agent_contacts c WHERE c.visitor_id=v.id AND c.url!='') AS legacy_contacts,
            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.channel!='poll' AND w.state='active' AND w.expires>? AND w.verified_at IS NOT NULL AND w.sealed IS NOT NULL AND w.authority=1 AND w.notice_version=?) AS authorized_inboxes,
            (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id=v.id AND w.state='pending_verification' AND w.code_expires>?) AS pending_contacts,
            (SELECT COUNT(*) FROM agent_task_events e JOIN agent_task_watches w ON w.id=e.watch_id WHERE w.visitor_id=v.id AND e.status='sent') AS digests,
            (SELECT COUNT(*) FROM agent_marketing_permissions m WHERE m.visitor_id=v.id AND m.withdrawn_at IS NULL) AS marketing_opt_ins,
            (SELECT COUNT(*) FROM agent_marketing_permissions m JOIN agent_task_watches w ON w.id=m.watch_id WHERE m.visitor_id=v.id AND m.withdrawn_at IS NULL AND m.verified_at IS NOT NULL AND m.notice_version=? AND m.expires>? AND w.state='active' AND w.expires>? AND w.verified_at IS NOT NULL AND w.sealed IS NOT NULL AND w.authority=1 AND w.notice_version=?) AS marketing_eligible_contacts,
            COALESCE(c.status,'new') AS case_status,COALESCE(c.owner,'') AS owner,c.next_followup,c.updated AS case_updated
          FROM agent_visitors v LEFT JOIN agent_visitor_cases c ON c.visitor_id=v.id
        ) """
        conditions=[];base_params=[now,now,NOTICE_VERSION,now,MARKETING_NOTICE,now,now,NOTICE_VERSION];params=list(base_params)
        if q:
            pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            conditions.append("(name LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\' OR last_task LIKE ? ESCAPE '\\')")
            params.extend([pattern]*3)
        filters={'registered':'inbox_contacts+legacy_contacts>0','authorized':'authorized_inboxes>0',
                 'marketing':'marketing_eligible_contacts>0','pending':'pending_contacts>0','legacy':'legacy_contacts>0','none':'inbox_contacts+legacy_contacts=0'}
        if contact in filters:
            conditions.append(filters[contact])
        if protocol:
            conditions.append("COALESCE(requested_protocol,'any')=?");params.append(protocol)
        if case_state:
            conditions.append('case_status=?');params.append(case_state)
        if tier:
            conditions.append('tier=?');params.append(tier)
        if source=='live':   # 11-12 PM: our own measurements ('internal') are not live traffic
            conditions.append("COALESCE(channel,'')!='admin-test' AND COALESCE(user_agent,'')<>'internal'")
        elif source=='simulation':
            conditions.append("channel='admin-test'")
        elif source=='internal':
            conditions.append("user_agent='internal'")
        where=' WHERE '+' AND '.join(conditions) if conditions else ''
        rows=[dict(r) for r in self.store.query(base+'SELECT * FROM base'+where+' ORDER BY last_seen DESC,id LIMIT ? OFFSET ?',(*params,limit,offset))]
        summary=dict(self.store.query(base+'''SELECT COUNT(*) AS total,
          COALESCE(SUM(inbox_contacts+legacy_contacts>0),0) AS registered,
          COALESCE(SUM(authorized_inboxes>0),0) AS authorized,
          COALESCE(SUM(pending_contacts>0),0) AS pending,
          COALESCE(SUM(marketing_eligible_contacts>0),0) AS marketing_eligible,
          COALESCE(SUM(case_status IN ('new','reviewing')),0) AS needs_review,
          COALESCE(SUM(case_status NOT IN ('resolved','archived') AND next_followup IS NOT NULL AND next_followup<=?),0) AS followup_due
          FROM base'''+where,(*base_params,now,*params[len(base_params):]))[0])
        return {'items':rows,'filtered_stats':summary,'pagination':{'total':summary['total'],'offset':offset,'limit':limit,'has_more':offset+len(rows)<summary['total']}}

    def detail(self,vid):
        if self.updates:
            self.updates.maintain()
        messages=[dict(r) for r in self.store.query('SELECT id,at,role,channel,text,data FROM agent_messages WHERE visitor_id=? ORDER BY id DESC LIMIT 200',(vid,))]
        by_id={row['id']:row for row in messages}
        turns=[]
        for row in messages:
            data=decoded(row['data'])
            if row['role']!='concierge' or data.get('record_version')!=1:
                continue
            question=by_id.get(data.get('request_message_id'))
            if question and question['role']!='agent':
                question=None
            request=decoded(question['data']) if question else {}
            recommendations=data.get('recommendations')
            recommendations=[item for item in recommendations[:1] if isinstance(item,dict)] if isinstance(recommendations,list) else []
            turns.append({'id':row['id'],'at':row['at'],'channel':row['channel'],
                'question':redact_visitor_tokens(question['text']) if question else None,
                'question_retained':question is not None,'protocol_mode':request.get('protocol_mode','unknown'),
                'protocol_filter':data.get('protocol_filter'),'task':data.get('task'),
                'intent':data.get('intent'),'status':data.get('status'),'metadata_truncated':bool(data.get('metadata_truncated')),
                'reply':redact_visitor_tokens(row['text']),'recommendations':recommendations})
        case_rows=self.store.query('SELECT * FROM agent_visitor_cases WHERE visitor_id=?',(vid,))
        case=dict(case_rows[0]) if case_rows else {'visitor_id':vid,'status':'new','owner':'','next_followup':None,'version':0}
        notes=[dict(r) for r in self.store.query('SELECT id,at,actor,kind,body FROM agent_visitor_case_notes WHERE visitor_id=? ORDER BY id DESC LIMIT 50',(vid,))]
        contacts=[]
        if self.updates:
            for row in self.store.query("SELECT * FROM agent_task_watches WHERE visitor_id=? ORDER BY CASE WHEN state IN ('active','paused','pending_verification') THEN 0 ELSE 1 END,created DESC LIMIT 100",(vid,)):
                contacts.append(self.updates.admin_summary(dict(row)))
        return {'case':case,'case_notes':notes,'chat_turns':turns,'recorded_turns':len(turns),
                'legacy_messages':sum(1 for row in messages if not decoded(row['data']).get('record_version')),
                'contact_relationships':contacts,'policy':{'marketing_enabled':False,'bulk_dispatch_enabled':False,'scope':'requested_task_updates'}}

    def save_case(self,vid,data,actor):
        if not self.store.query('SELECT 1 FROM agent_visitors WHERE id=?',(vid,)):
            raise LookupError('Visitor not found.')
        if data.get('status') not in STATES:
            raise ValueError('Invalid case status.')
        owner=safe_text(data.get('owner',''),80)
        note=safe_text(data.get('note',''),2000)
        followup=data.get('next_followup')
        if followup is not None:
            import math
            if type(followup) not in (int,float) or not math.isfinite(followup) or not 0<followup<time.time()+366*86400:
                raise ValueError('Invalid follow-up time.')
        version=data.get('version')
        if data['status'] in ('resolved','archived'):
            followup=None
        if type(version) is not int or version<0:
            raise ValueError('A current case version is required.')
        with self.store.tx() as db:
            old=db.execute('SELECT version FROM agent_visitor_cases WHERE visitor_id=?',(vid,)).fetchone()
            if (old['version'] if old else 0)!=version:
                raise RuntimeError('The case changed. Reload before saving.')
            db.execute('''INSERT INTO agent_visitor_cases (visitor_id,status,owner,next_followup,updated,updated_by,version)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(visitor_id) DO UPDATE SET status=excluded.status,owner=excluded.owner,
                next_followup=excluded.next_followup,updated=excluded.updated,updated_by=excluded.updated_by,version=excluded.version''',
                (vid,data['status'],owner,followup,time.time(),actor,version+1))
            if note:
                db.execute('INSERT INTO agent_visitor_case_notes (visitor_id,at,actor,kind,body) VALUES (?,?,?,?,?)',(vid,time.time(),actor,'internal',note))
            db.execute('DELETE FROM agent_visitor_case_notes WHERE visitor_id=? AND id NOT IN (SELECT id FROM agent_visitor_case_notes WHERE visitor_id=? ORDER BY id DESC LIMIT 100)',(vid,vid))
        return {'ok':True,'version':version+1}
