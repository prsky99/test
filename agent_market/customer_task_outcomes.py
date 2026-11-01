"""Purpose-consented customer task outcomes, separate from provider quality.

No support employee can impersonate a customer's report. Execution success,
customer-reported business success and long-term cohort observations stay
separate. Withdrawal removes an observation from all aggregates immediately.
"""
from .customer_workspace_runtime import CustomerRuntimeActor
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceDenied,WorkspaceConflict,WorkspaceInvalid,_canonical,_hash,_rows,_identity

PROFILE='customer-task-outcomes-v1'
NOTICE='customer-task-outcome-service-improvement-v1'
WITHDRAW_NOTICE='customer-task-outcome-withdraw-v1'
SCHEMA=(
    '''CREATE TABLE IF NOT EXISTS customer_task_outcomes(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS customer_task_outcome_withdrawals(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS customer_task_outcome_restore_blocks(id TEXT PRIMARY KEY)',
)


class CustomerTaskOutcomes(SignedWorkspaceModule):
    def __init__(self, access, sources):
        if sources.access is not access:
            raise WorkspaceInvalid()
        super().__init__(access,PROFILE,SCHEMA)
        self.sources=sources

    def _customer(self,ws,actor):
        if type(actor) is not CustomerRuntimeActor or actor.workspace_id != ws or actor.token_ref is not None:
            raise WorkspaceDenied()
        self.scope(ws,actor)

    def record(self,ws,body,actor):
        exact(body,('source_kind','subject_id','version_id','run_id','task_succeeded','correction_count',
                    'support_minutes','authorized','notice'))
        if (body['authorized'] is not True or body['notice'] != NOTICE
                or type(body['task_succeeded']) not in (bool,type(None))
                or type(body['correction_count']) is not int or not 0 <= body['correction_count'] <= 100
                or type(body['support_minutes']) is not int or not 0 <= body['support_minutes'] <= 1440):
            raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            self._customer(ws,actor)
            source=self.sources._source(db,ws,body)
            if source['source_kind']=='typed':
                _,_,claims=self.sources.typed._run(db,ws,source['subject_id'],source['run_id'])
            else:
                _,_,claims,_=self.sources.execution._load_run(db,source['run_id'],ws,
                    source['subject_id'],source['version_id'],decrypt_output=False)
            if claims.get('actor_kind')!='customer' or claims.get('actor_user_id')!=actor.customer_id:
                raise WorkspaceDenied()
            # A customer may report usefulness even for a technically failed
            # attempt; that statement never rewrites the execution outcome.
            identity='cto_'+_hash([ws,actor.customer_id,source['run_id']])[:32]
            if (db.execute('SELECT 1 FROM customer_task_outcome_withdrawals WHERE id=?',(identity,)).fetchone()
                    or db.execute('SELECT 1 FROM customer_task_outcome_restore_blocks WHERE id=?',(identity,)).fetchone()):
                raise WorkspaceDenied()
            value={'profile':PROFILE,'id':identity,'workspace_id':ws,'customer_ref':_hash([ws,actor.customer_id]),
                   'source':source,'task_succeeded':body['task_succeeded'],'correction_count':body['correction_count'],
                   'support_minutes':body['support_minutes'],'consent_notice':NOTICE,'purpose':'service_improvement',
                   'provenance':'customer_reported','created':clock()}
            previous=_rows(db,'SELECT * FROM customer_task_outcomes WHERE id=? AND workspace_id=?',(identity,ws))
            if previous:
                old=self.opened(previous[0]); value['created']=old['created']
                if value != old:
                    raise WorkspaceConflict()
                return {'outcome_id':identity,'replayed':True,'provenance':'customer_reported'}
            if db.execute('SELECT COUNT(*) FROM customer_task_outcomes WHERE workspace_id=?',(ws,)).fetchone()[0] >= 1000:
                raise WorkspaceConflict()
            db.execute('INSERT INTO customer_task_outcomes VALUES(?,?,?,?)',(identity,ws,_canonical(value),self.sign(value)))
            self.access._audit(db,actor,ws,'customer_outcome.record',identity,1)
            return {'outcome_id':identity,'replayed':False,'provenance':'customer_reported'}

    def withdraw(self,ws,body,actor):
        exact(body,('outcome_id','authorized','notice'))
        _identity(ws,'ws');_identity(body['outcome_id'],'cto')
        if body['authorized'] is not True or body['notice'] != WITHDRAW_NOTICE:
            raise WorkspaceInvalid()
        if type(actor) is not CustomerRuntimeActor or actor.workspace_id!=ws or actor.token_ref is not None:
            raise WorkspaceDenied()
        # A person's own purpose authorization can be withdrawn after a role or
        # membership change. This grants no workspace read or execution right.
        with self.access.identity.tx() as db:
            self.access.identity._session(db,actor.session_ref,actor.customer_id)
            rows=_rows(db,'SELECT * FROM customer_task_outcomes WHERE id=? AND workspace_id=?',(body['outcome_id'],ws))
            if len(rows)!=1:
                raise WorkspaceDenied()
            value=self.opened(rows[0])
            if value.get('profile')!=PROFILE or value['id']!=body['outcome_id'] or value['workspace_id']!=ws:
                raise WorkspaceConflict()
            if value['customer_ref'] != _hash([ws,actor.customer_id]):
                raise WorkspaceDenied()
            old=_rows(db,'SELECT * FROM customer_task_outcome_withdrawals WHERE id=?',(value['id'],))
            if old:
                if self.opened(old[0])['outcome_hash'] != _hash(value):
                    raise WorkspaceConflict()
                return {'withdrawn':True,'replayed':True}
            withdrawal={'id':value['id'],'workspace_id':ws,'outcome_hash':_hash(value),'created':clock()}
            db.execute('INSERT INTO customer_task_outcome_withdrawals VALUES(?,?,?,?)',
                (value['id'],ws,_canonical(withdrawal),self.sign(withdrawal)))
            db.execute('''INSERT INTO customer_workspace_audit
                (workspace_id,customer_id,action,object_id,revision,created) VALUES(?,?,?,?,?,?)''',
                (ws,actor.customer_id,'customer_outcome.withdraw',value['id'],1,clock()))
            self.access.identity._session(db,actor.session_ref,actor.customer_id)
            return {'withdrawn':True,'replayed':False}

    def report(self,ws,actor):
        with self.access._tx(actor) as (db,_):
            self._customer(ws,actor)
            rows=_rows(db,'SELECT * FROM customer_task_outcomes WHERE workspace_id=? ORDER BY id LIMIT 1001',(ws,))
            if len(rows)>1000:
                raise WorkspaceConflict()
            retained=[];excluded={'withdrawn':0,'restored':0,'source_changed':0,'source_unavailable':0}
            for row in rows:
                value=self.opened(row)
                if value.get('profile')!=PROFILE or value['id']!=row['id'] or value['workspace_id']!=ws:
                    raise WorkspaceConflict()
                tombstones=_rows(db,'SELECT * FROM customer_task_outcome_withdrawals WHERE id=?',(value['id'],))
                if tombstones:
                    if self.opened(tombstones[0])['outcome_hash'] != _hash(value):
                        raise WorkspaceConflict()
                    excluded['withdrawn']+=1;continue
                if db.execute('SELECT 1 FROM customer_task_outcome_restore_blocks WHERE id=?',(value['id'],)).fetchone():
                    excluded['restored']+=1;continue
                try:source=self.sources._source(db,ws,value['source'])
                except (WorkspaceDenied,WorkspaceConflict):
                    excluded['source_unavailable']+=1;continue
                if source != value['source']:
                    excluded['source_changed']+=1;continue
                retained.append(value)
            reported=[value for value in retained if value['task_succeeded'] is not None]
            groups={}
            for value in retained:
                groups.setdefault(value['customer_ref'],[]).append(value['source']['created'])
            eligible=sum(clock()-min(times)>=28*86400 for times in groups.values())
            repeated=sum(max(times)-min(times)>=28*86400 for times in groups.values())
            own=_hash([ws,actor.customer_id])
            return {'profile':PROFILE,'purpose':'service_improvement','provenance':'customer_reported',
                'sample_count':len(retained),'reported_success_count':sum(v['task_succeeded'] for v in reported),
                'reported_outcome_count':len(reported),'unknown_outcome_count':len(retained)-len(reported),
                'execution_succeeded_count':sum(v['source']['execution_status']=='succeeded' for v in retained),
                'correction_count':sum(v['correction_count'] for v in retained),
                'reported_support_minutes':sum(v['support_minutes'] for v in retained),
                'cohort_28_day_eligible':eligible,'cohort_28_day_reused':repeated,
                'cohort_observation_complete':bool(eligible),'excluded':excluded,
                'own_records':[{'outcome_id':v['id'],'run_id':v['source']['run_id']} for v in retained if v['customer_ref']==own],
                'independently_verified_business_success':False,'provider_quality_qualified':False,
                'marketing_permission':False,'model_training_permission':False,'notice':NOTICE,'withdrawal_notice':WITHDRAW_NOTICE}
