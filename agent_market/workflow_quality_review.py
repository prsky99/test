"""Pre-run scoped staff review queue; real expertise/holdout remain separate."""
from dataclasses import dataclass
import math
import re
import secrets

from .shadow_ledger import SignedWorkspaceModule, clock, exact, identifier
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _rows, _safe_text
from .workflow_review_packets import DIMENSIONS, RUBRIC_VERSION, RUBRIC_SHA256, rubric

PROFILE='workspace-quality-review-v1'
NOTICE='workspace-quality-reserve-v1'
BIND_NOTICE='workspace-quality-bind-v1'
INSPECT_NOTICE='workspace-quality-inspect-v1'
REVIEW_NOTICE='workspace-quality-score-v1'
ADJUDICATE_NOTICE='workspace-quality-adjudicate-v1'
SCHEMA=(
    '''CREATE TABLE IF NOT EXISTS workspace_quality_assignments (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,run_id TEXT,payload TEXT NOT NULL,signature TEXT NOT NULL,
       UNIQUE(workspace_id,run_id))''',
    '''CREATE TABLE IF NOT EXISTS workspace_quality_disclosures (
       assignment_id TEXT NOT NULL,user_id INTEGER NOT NULL,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,
       signature TEXT NOT NULL,PRIMARY KEY(assignment_id,user_id))''',
    '''CREATE TABLE IF NOT EXISTS workspace_quality_judgments (
       assignment_id TEXT NOT NULL,user_id INTEGER NOT NULL,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,
       signature TEXT NOT NULL,PRIMARY KEY(assignment_id,user_id))''',
    '''CREATE TABLE IF NOT EXISTS workspace_quality_adjudications (
       assignment_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
)


def digest(value):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{64}',value):raise WorkspaceInvalid()
    return value


def scores(value, *, nullable=True):
    if type(value) is not dict or set(value)!=set(DIMENSIONS):raise WorkspaceInvalid()
    if any(not(nullable and score is None) and (type(score) is not int or not 0<=score<=2) for score in value.values()):
        raise WorkspaceInvalid()
    return value


@dataclass(frozen=True)
class ReviewerQualification:
    user_id:int
    qualification_hash:str
    independence_hash:str
    audit_hash:str
    expires:float
    environment:str
    assignment_id:str|None=None
    identity_hash:str|None=None


@dataclass(frozen=True)
class ReviewedSource:
    workspace_id:str
    source_hash:str
    audit_hash:str
    expires:float
    environment:str


class QualityNotCurrent(WorkspaceDenied):
    pass


class WorkflowQualityReview(SignedWorkspaceModule):
    def __init__(self,access,execution,*,qualification_source=None,source_verifier=None):
        super().__init__(access,PROFILE,SCHEMA)
        if execution.access is not access and execution.store is not access.store:raise WorkspaceInvalid()
        if any(value is not None and not callable(value) for value in (qualification_source,source_verifier)):raise WorkspaceInvalid()
        self.execution=execution;self.qualification_source=qualification_source;self.source_verifier=source_verifier

    def _context(self,db,ws,wd,wv,actor,*,write=False,owner=False):
        self.scope(ws,actor,write=write,owner=owner)
        self.access._open_draft(self.access._draft_row(ws,wd))
        row=self.access._version_row(ws,wd,wv);value=self.access._open_version(row)
        if not row['active']:raise WorkspaceDenied()
        return value

    def _participant(self,db,ws,uid):
        if type(uid) is not int or uid<1:raise WorkspaceInvalid()
        rows=_rows(db,'''SELECT u.id FROM admin_users u JOIN workspace_memberships m ON m.user_id=u.id
            WHERE u.id=? AND u.active=1 AND u.role IN ('admin','superadmin') AND m.workspace_id=?
            AND m.active=1 AND m.role IN ('owner','editor')''',(uid,ws))
        if len(rows)!=1:raise WorkspaceDenied()

    def _authority(self,db,ws,ids):
        workspace=_rows(db,'SELECT revision,active FROM organization_workspaces WHERE id=?',(ws,))
        if len(workspace)!=1 or workspace[0]['active']!=1:raise QualityNotCurrent()
        participants={}
        for uid in sorted(set(ids)):
            rows=_rows(db,'''SELECT m.revision,m.role,u.role AS global_role,u.updated_at FROM workspace_memberships m
                JOIN admin_users u ON u.id=m.user_id WHERE m.workspace_id=? AND m.user_id=? AND m.active=1
                AND u.active=1 AND m.role IN ('owner','editor') AND u.role IN ('admin','superadmin')''',(ws,uid))
            if len(rows)!=1:raise QualityNotCurrent()
            participants[str(uid)]=rows[0]
        return {'workspace_revision':workspace[0]['revision'],'participants':participants}

    def _metadata(self,db,ws,identity):
        identifier(identity,'wqa')
        rows=_rows(db,'SELECT * FROM workspace_quality_assignments WHERE id=? AND workspace_id=?',(identity,ws))
        if len(rows)!=1:raise WorkspaceDenied()
        value=self.opened(rows[0])
        if value['id']!=identity or value['workspace_id']!=ws or value['run_id']!=rows[0]['run_id']:raise WorkspaceConflict()
        return value

    def _assignment(self,db,ws,identity,actor,*,write=False,owner=False):
        self.scope(ws,actor,write=write,owner=owner)
        value=self._metadata(db,ws,identity)
        rubric()
        if value['rubric_hash']!=RUBRIC_SHA256:raise QualityNotCurrent()
        try:snapshot=self._context(db,ws,value['draft_id'],value['snapshot_id'],actor,write=write,owner=owner)
        except WorkspaceDenied:raise QualityNotCurrent() from None
        if value['snapshot_hash']!=_hash(snapshot['snapshot']):raise WorkspaceConflict()
        ids=[value['created_by'],value['executor_user_id'],value['adjudicator_user_id'],*value['reviewer_ids']]
        if value['authority']!=self._authority(db,ws,ids):raise QualityNotCurrent()
        return value

    @staticmethod
    def dto(value):
        return {key:value[key] for key in ('id','draft_id','snapshot_id','dataset_hash','case_hash','source_hash',
            'created','run_id','reviewer_ids','executor_user_id','adjudicator_user_id')}|{
            'profile':PROFILE,'rubric_version':RUBRIC_VERSION,'rubric_sha256':RUBRIC_SHA256,
            'human_expert_reviewed':False,'holdout_status':'not_established','external_calls':0}

    def options(self,ws,actor):
        dimensions=rubric()
        with self.access._tx(actor) as(db,user):
            member,_=self.scope(ws,actor)
            participants=_rows(db,'''SELECT u.id,u.role,m.role AS workspace_role FROM admin_users u
                JOIN workspace_memberships m ON m.user_id=u.id WHERE m.workspace_id=? AND m.active=1
                AND u.active=1 AND u.role IN ('admin','superadmin') AND m.role IN ('owner','editor') ORDER BY u.id LIMIT 101''',(ws,))
            return {'profile':PROFILE,'rubric':dimensions,'rubric_version':RUBRIC_VERSION,'rubric_sha256':RUBRIC_SHA256,
                'participants':participants,'can_manage':member['member_role']=='owner' and user['role']!='operator',
                'notices':{'reserve':NOTICE,'bind':BIND_NOTICE,'inspect':INSPECT_NOTICE,'review':REVIEW_NOTICE,'adjudicate':ADJUDICATE_NOTICE},
                'qualification_source_configured':self.qualification_source is not None,'source_verifier_configured':self.source_verifier is not None,
                'model_calls':0,'automatic_execution':False,'holdout_status':'not_established'}

    def reserve(self,ws,body,actor):
        exact(body,('draft_id','snapshot_id','dataset_hash','case_hash','source_hash','source_ref',
            'executor_user_id','reviewer_ids','adjudicator_user_id','authorized','notice'))
        for key in ('dataset_hash','case_hash','source_hash'):digest(body[key])
        if (body['authorized'] is not True or body['notice']!=NOTICE or type(body['source_ref']) is not str
                or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',body['source_ref'])
                or type(body['reviewer_ids']) is not list or not 2<=len(body['reviewer_ids'])<=4
                or any(type(uid) is not int for uid in body['reviewer_ids'])):raise WorkspaceInvalid()
        distinct=[body['executor_user_id'],body['adjudicator_user_id'],*body['reviewer_ids']]
        if any(type(uid) is not int or uid<1 for uid in distinct):raise WorkspaceInvalid()
        if len(set(distinct))!=len(distinct) or actor.user_id in body['reviewer_ids'] or actor.user_id==body['adjudicator_user_id']:
            raise WorkspaceInvalid()
        dimensions=rubric()
        with self.access._tx(actor,write=True) as(db,_):
            snapshot=self._context(db,ws,body['draft_id'],body['snapshot_id'],actor,write=True,owner=True)
            for uid in distinct:self._participant(db,ws,uid)
            if db.execute('SELECT COUNT(*) FROM workspace_quality_assignments WHERE workspace_id=?',(ws,)).fetchone()[0]>=200:raise WorkspaceConflict()
            node=self.execution._node(snapshot)
            _,pin=self.execution._resource(db,node)
            control=self.execution._control(db)
            value={'profile':PROFILE,'id':'wqa_'+secrets.token_hex(16),'workspace_id':ws,
                **{key:body[key] for key in ('draft_id','snapshot_id','dataset_hash','case_hash','source_hash','source_ref',
                    'executor_user_id','reviewer_ids','adjudicator_user_id')},'snapshot_hash':_hash(snapshot['snapshot']),
                'created':clock(),'created_by':actor.user_id,'rubric_hash':RUBRIC_SHA256,'run_id':None,'run_hash':None,
                'authority':self._authority(db,ws,[actor.user_id,*distinct]),'binding_hash':pin,'controls':control}
            db.execute('INSERT INTO workspace_quality_assignments VALUES(?,?,NULL,?,?)',(value['id'],ws,_canonical(value),self.sign(value)))
            self.access._audit(db,actor,ws,'quality.reserve',value['id'],None)
            return self.dto(value)

    def _run(self,db,assignment):
        if not assignment['run_id']:raise WorkspaceConflict()
        row,ticket,claims,payload=self.execution._load_run(db,assignment['run_id'],assignment['workspace_id'],assignment['draft_id'],assignment['snapshot_id'])
        if (payload['status']!='succeeded' or payload['dispatched'] is None
                or payload['actor_user_id']!=assignment['executor_user_id'] or payload['created']<assignment['created']
                or payload['finished'] is None or payload['finished']<payload['dispatched']
                or payload['finished']>clock()+5 or claims['snapshot_hash']!=self.access._version_row(
                    assignment['workspace_id'],assignment['draft_id'],assignment['snapshot_id'])['payload_hash']):raise WorkspaceConflict()
        if assignment['run_hash'] is not None and assignment['run_hash']!=_hash(payload):raise WorkspaceConflict()
        snapshot=self.access._open_version(self.access._version_row(assignment['workspace_id'],assignment['draft_id'],assignment['snapshot_id']))
        try:
            _,pin=self.execution._resource(db,self.execution._node(snapshot))
            control=self.execution._control(db)
        except WorkspaceDenied:raise QualityNotCurrent() from None
        if claims['binding_hash']!=assignment['binding_hash'] or pin!=assignment['binding_hash'] or claims['controls']!=assignment['controls'] or control!=assignment['controls']:
            raise QualityNotCurrent()
        return payload

    def bind(self,ws,identity,body,actor):
        exact(body,('run_id','authorized','notice'));identifier(body['run_id'],'wpr')
        if body['authorized'] is not True or body['notice']!=BIND_NOTICE:raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as(db,_):
            value=self._assignment(db,ws,identity,actor,write=True,owner=True)
            if value['run_id'] is not None:
                if value['run_id']!=body['run_id']:raise WorkspaceConflict()
                self._run(db,value);return self.dto(value)|{'replayed':True}
            value['run_id']=body['run_id'];payload=self._run(db,value);value['run_hash']=_hash(payload)
            if db.execute('SELECT 1 FROM workspace_quality_assignments WHERE workspace_id=? AND run_id=?',(ws,body['run_id'])).fetchone():raise WorkspaceConflict()
            db.execute('UPDATE workspace_quality_assignments SET run_id=?,payload=?,signature=? WHERE id=? AND workspace_id=?',
                (body['run_id'],_canonical(value),self.sign(value),identity,ws))
            self.access._audit(db,actor,ws,'quality.bind',identity,None)
            return self.dto(value)

    def inspect(self,ws,identity,body,actor):
        exact(body,('authorized','notice'))
        if body['authorized'] is not True or body['notice']!=INSPECT_NOTICE:raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as(db,_):
            value=self._assignment(db,ws,identity,actor,write=True)
            if actor.user_id not in [*value['reviewer_ids'],value['adjudicator_user_id']]:raise WorkspaceDenied()
            self._participant(db,ws,actor.user_id);payload=self._run(db,value)
            prior=_rows(db,'SELECT * FROM workspace_quality_disclosures WHERE assignment_id=? AND user_id=?',(identity,actor.user_id))
            if prior:self.opened(prior[0])
            else:
                disclosure={'assignment_id':identity,'workspace_id':ws,'user_id':actor.user_id,'created':clock(),'run_hash':value['run_hash']}
                db.execute('INSERT INTO workspace_quality_disclosures VALUES(?,?,?,?,?)',(identity,actor.user_id,ws,_canonical(disclosure),self.sign(disclosure)))
                self.access._audit(db,actor,ws,'quality.inspect',identity,None)
            return {'assignment':self.dto(value),'output':payload['output'],'source_ref':value['source_ref'],
                    'source_hash':value['source_hash'],'source_material_is_separate':True,'rubric':rubric(),
                    'blind_or_anonymous':False,'holdout_status':'not_established'}

    def review(self,ws,identity,body,actor):
        exact(body,('scores','source_observed_at','source_reviewed','no_conflict_declared','notes','authorized','notice'))
        scores(body['scores']);_safe_text(body['notes'],1000,empty=True)
        if (body['authorized'] is not True or body['notice']!=REVIEW_NOTICE or body['source_reviewed'] is not True
                or body['no_conflict_declared'] is not True or type(body['source_observed_at']) not in (int,float)
                or not math.isfinite(body['source_observed_at']) or not 0<body['source_observed_at']<=clock()+5):raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as(db,_):
            value=self._assignment(db,ws,identity,actor,write=True)
            if actor.user_id not in value['reviewer_ids'] or actor.user_id in (value['executor_user_id'],value['created_by']):raise WorkspaceDenied()
            self._participant(db,ws,actor.user_id);self._run(db,value)
            disclosed=_rows(db,'SELECT * FROM workspace_quality_disclosures WHERE assignment_id=? AND user_id=?',(identity,actor.user_id))
            if len(disclosed)!=1 or self.opened(disclosed[0])['run_hash']!=value['run_hash']:raise WorkspaceDenied()
            old=_rows(db,'SELECT * FROM workspace_quality_judgments WHERE assignment_id=? AND user_id=?',(identity,actor.user_id))
            if old:
                original=self.opened(old[0])
                if original['judgment']!=body:raise WorkspaceConflict()
                return {'recorded':True,'replayed':True,'human_expert_reviewed':False}
            judgment={'assignment_id':identity,'workspace_id':ws,'user_id':actor.user_id,'created':clock(),
                'run_hash':value['run_hash'],'rubric_hash':RUBRIC_SHA256,'judgment':body}
            db.execute('INSERT INTO workspace_quality_judgments VALUES(?,?,?,?,?)',(identity,actor.user_id,ws,_canonical(judgment),self.sign(judgment)))
            self.access._audit(db,actor,ws,'quality.review',identity,None)
            return {'recorded':True,'replayed':False,'human_expert_reviewed':False}

    def _reviews(self,db,value):
        rows=_rows(db,'SELECT * FROM workspace_quality_judgments WHERE assignment_id=? ORDER BY user_id',(value['id'],))
        result=[]
        for row in rows:
            judgment=self.opened(row)
            if (row['workspace_id']!=value['workspace_id'] or row['user_id'] not in value['reviewer_ids']
                    or judgment['user_id']!=row['user_id'] or judgment['assignment_id']!=value['id']
                    or judgment['run_hash']!=value['run_hash']):raise WorkspaceConflict()
            result.append(judgment)
        return result

    def adjudicate(self,ws,identity,body,actor):
        exact(body,('scores','reason','authorized','notice'));scores(body['scores'],nullable=False);_safe_text(body['reason'],1000)
        if body['authorized'] is not True or body['notice']!=ADJUDICATE_NOTICE:raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as(db,_):
            value=self._assignment(db,ws,identity,actor,write=True)
            if actor.user_id!=value['adjudicator_user_id']:raise WorkspaceDenied()
            self._participant(db,ws,actor.user_id);self._run(db,value);reviews=self._reviews(db,value)
            disclosed=_rows(db,'SELECT * FROM workspace_quality_disclosures WHERE assignment_id=? AND user_id=?',(identity,actor.user_id))
            if len(disclosed)!=1 or self.opened(disclosed[0])['run_hash']!=value['run_hash']:raise WorkspaceDenied()
            if len(reviews)!=len(value['reviewer_ids']) or any(any(score is None for score in review['judgment']['scores'].values()) for review in reviews):raise WorkspaceConflict()
            if all(review['judgment']['scores']==reviews[0]['judgment']['scores'] for review in reviews):raise WorkspaceConflict()
            rows=_rows(db,'SELECT * FROM workspace_quality_adjudications WHERE assignment_id=?',(identity,))
            if rows:
                if self.opened(rows[0])['decision']!=body:raise WorkspaceConflict()
                return {'recorded':True,'replayed':True}
            adjudication={'assignment_id':identity,'workspace_id':ws,'user_id':actor.user_id,'created':clock(),
                'run_hash':value['run_hash'],'review_hashes':[_hash(review) for review in reviews],'decision':body}
            db.execute('INSERT INTO workspace_quality_adjudications VALUES(?,?,?,?)',(identity,ws,_canonical(adjudication),self.sign(adjudication)))
            self.access._audit(db,actor,ws,'quality.adjudicate',identity,None)
            return {'recorded':True,'replayed':False}

    def assignments(self,ws,actor):
        with self.access._tx(actor) as(db,_):
            self.scope(ws,actor)
            rows=_rows(db,'SELECT * FROM workspace_quality_assignments WHERE workspace_id=? ORDER BY rowid DESC LIMIT 30',(ws,))
            return [self.dto(self._metadata(db,ws,row['id'])) for row in rows]

    def _not_current(self,value):
        return {'assignment':self.dto(value),'status':'retained_assignment_not_current','review_count':0,
            'reviews':[],'scores_complete':False,'disagreement':False,'adjudicated':False,
            'qualified_operating_evidence':False,'human_expert_reviewed':False,'actual_independence_verified':False,
            'source_evidence_verified':False,'holdout_status':'not_established','automatic_winner':None,'execution_authorized':False}

    def status(self,ws,identity,actor):
        with self.access._tx(actor) as(db,_):
            self.scope(ws,actor)
            value=self._metadata(db,ws,identity)
            try:
                self._assignment(db,ws,identity,actor)
                if value['run_id']:self._run(db,value)
            except QualityNotCurrent:
                return self._not_current(value)
            reviews=self._reviews(db,value)
            complete=len(reviews)==len(value['reviewer_ids']) and all(all(score is not None for score in r['judgment']['scores'].values()) for r in reviews)
            disagreement=complete and any(r['judgment']['scores']!=reviews[0]['judgment']['scores'] for r in reviews[1:])
            rows=_rows(db,'SELECT * FROM workspace_quality_adjudications WHERE assignment_id=?',(identity,))
            adjudicated=False
            if rows:
                a=self.opened(rows[0]);adjudicated=a['run_hash']==value['run_hash'] and a['review_hashes']==[_hash(r) for r in reviews]
                if not adjudicated:raise WorkspaceConflict()
            result={'assignment':self.dto(value),'reviews':[{'user_id':r['user_id'],'scores':r['judgment']['scores'],'recorded_at':r['created']} for r in reviews],
                'review_count':len(reviews),'scores_complete':complete,'disagreement':disagreement,'adjudicated':adjudicated,
                'status':'needs_adjudication' if disagreement and not adjudicated else 'staff_reviews_recorded' if complete else 'review_pending',
                'human_expert_reviewed':False,'actual_independence_verified':False,'source_evidence_verified':False,
                'qualified_operating_evidence':False,'holdout_status':'not_established','automatic_winner':None,'execution_authorized':False}
            checkpoint=(_hash(value),[_hash(review) for review in reviews],[_hash(self.opened(row)) for row in rows])
        # Real qualifications and source evidence are external independently
        # audited inputs. Never turn staff declarations into expert credentials.
        now=clock();qualified=False;source_ok=False
        try:
            if complete and self.qualification_source:
                ids=[*value['reviewer_ids'],value['adjudicator_user_id']]
                records=[self.qualification_source(ws,uid,value['id']) for uid in ids]
                qualified=all(type(record) is ReviewerQualification and type(record.user_id) is int and record.user_id==uid
                    and record.assignment_id==value['id']
                    and record.environment=='operating' and type(record.expires) in (int,float)
                    and math.isfinite(record.expires) and record.expires>now
                    and all(type(h) is str and re.fullmatch(r'[0-9a-f]{64}',h) for h in
                        (record.identity_hash,record.qualification_hash,record.independence_hash,record.audit_hash)) for uid,record in zip(ids,records))
                qualified=qualified and len({record.identity_hash for record in records})==len(records)
            if complete and self.source_verifier:
                source=self.source_verifier(ws,value['source_hash'],value['source_ref'])
                source_ok=(type(source) is ReviewedSource and source.workspace_id==ws and source.source_hash==value['source_hash']
                    and source.environment=='operating' and type(source.expires) in (int,float) and math.isfinite(source.expires)
                    and source.expires>now and type(source.audit_hash) is str and re.fullmatch(r'[0-9a-f]{64}',source.audit_hash) is not None)
        except Exception:qualified=False;source_ok=False
        with self.access._tx(actor) as(db,_):
            try:
                current=self._assignment(db,ws,identity,actor)
                if current['run_id']:self._run(db,current)
            except QualityNotCurrent:return self._not_current(value)
            current_reviews=self._reviews(db,current)
            current_adjudications=_rows(db,'SELECT * FROM workspace_quality_adjudications WHERE assignment_id=?',(identity,))
            if checkpoint!=(_hash(current),[_hash(review) for review in current_reviews],[_hash(self.opened(row)) for row in current_adjudications]):raise WorkspaceConflict()
            for uid in value['reviewer_ids']:self._participant(db,ws,uid)
        result.update(actual_independence_verified=qualified,source_evidence_verified=source_ok,
            qualified_operating_evidence=bool(complete and (not disagreement or adjudicated) and qualified and source_ok))
        return result
