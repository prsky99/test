"""Deterministic scoped documentation and reviewed private-draft JSON patches."""
import copy
import secrets

from .shadow_ledger import SignedWorkspaceModule, clock, exact, identifier
from .workspace_access import (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
    _canonical, _hash, _revision, _rows, _safe_text)

PROFILE = 'workspace-support-proposals-v1'
NOTICE = 'workspace-support-proposal-v1'
APPLY_NOTICE = 'workspace-support-apply-v1'
DOCS = (
    {'id': 'public-search-workflow', 'title': 'Building a read-only search workflow', 'version': 'public-guidance-v1',
     'text': 'Choose a public news or documentation objective. Review the available approved agents, their order, each literal input and any binding from an earlier result. A workflow can include two to ten reviewed read-only steps. Review the proposed graph before saving a new private draft. Saving does not call agents. Run it only after separate execution consent. Search results are sources to inspect, not a generated summary or a guarantee of factual accuracy.'},
    {'id': 'private-snapshots', 'title': 'Private saved snapshots',
     'text': 'A saved snapshot is immutable design data. Current workspace membership is required. Saving does not publish, deploy or execute a workflow.'},
    {'id': 'private-manual-run', 'title': 'Private manual execution',
     'text': 'The current bounded profile permits one informational MCP tool with literal inputs. Input transfer and one execution require fresh explicit authorization. Unknown outcomes are not automatically retried.'},
    {'id': 'typed-product-evidence', 'title': 'Typed product evidence',
     'text': 'Product evidence retains units, currency, source and observation time. Missing evidence is explicit. Schema validation does not certify factual accuracy or authorize payment.'},
    {'id': 'safe-change-review', 'title': 'Reviewing a draft change',
     'text': 'Review the exact JSON patch and apply a new private draft revision. Test and publication are separate actions. This support tool cannot execute commands, contact providers or publish a release.'},
    {'id': 'typed-workflow-review', 'title': 'Reviewing a private typed workflow', 'version': 'public-guidance-v2',
     'text': 'The separate private typed profile supports two to ten reviewed read-only steps. Review every destination, literal input, declared prior-output binding and branch. Saving a workflow does not call an agent. Each execution requires fresh consent; an uncertain submission must be inspected in retained history before another action.'},
    {'id': 'app-deployment-lifecycle', 'title': 'Private application deployment lifecycle', 'version': 'public-guidance-v3',
     'text': 'An exported private app requires an approved origin, a same-origin backend and a current deployment authorization. The app depends on the Agent Concierge gateway. Expiry, withdrawal or a changed workflow can prevent new executions. Public workspace access does not authorize application execution.'},
    {'id': 'current-evidence-limits', 'title': 'Understanding current evidence', 'version': 'public-guidance-v2',
     'text': 'A retained observation is evidence of the recorded check, not a guarantee of factual accuracy or future availability. Evaluation scope, sample size, version, time, source retention and independent review matter. Missing, expired, withdrawn or deleted source evidence must not retain a positive quality claim.'},
    {'id': 'verified-task-updates', 'title': 'Verified task update destinations', 'version': 'public-guidance-v2',
     'text': 'Task updates are optional and purpose-specific. A browser subscription requires native permission and confirmation by clicking the delivered test notification. A webhook or inbox must pass destination verification. A delivery receipt means the update was accepted, not that another agent completed a task. Advertising permission is separate.'},
)
SCHEMA = ('''CREATE TABLE IF NOT EXISTS workspace_support_proposals (
    id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,draft_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,
    payload TEXT NOT NULL,signature TEXT NOT NULL)''',)


class WorkflowSupport(SignedWorkspaceModule):
    def __init__(self, access):
        super().__init__(access, PROFILE, SCHEMA)

    @staticmethod
    def docs_hash(): return _hash(DOCS)

    def search(self,ws,body,actor):
        exact(body,('query',))
        with self.access._tx(actor) as (db,_):
            self.scope(ws,actor)
        from .first_party_guides import PlatformGuideAgent
        result=PlatformGuideAgent().search({'query':body['query'],'language':'en','limit':5})
        return {'profile':PROFILE,'items':result['items'],'document_hash':self.docs_hash(),
                'provider_calls':0,'model_calls':0,'guidance_verified':False}

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            return {'profile': PROFILE, 'notice': NOTICE, 'apply_notice': APPLY_NOTICE,
                'can_edit': member['member_role'] in ('owner', 'editor') and user['role'] != 'operator',
                'documents': [dict(doc) for doc in DOCS], 'document_hash': self.docs_hash(),
                'model_calls': 0, 'provider_calls': 0, 'automatic_execution': False,
                'publication_enabled': False, 'first_party_ranking_priority': False}

    def _context(self, ws, wd, wv, actor):
        member, user = self.scope(ws, actor, write=True)
        draft = self.access._open_draft(self.access._draft_row(ws, wd))
        row = self.access._version_row(ws, wd, wv)
        snapshot = self.access._open_version(row)
        if not row['active']: raise WorkspaceDenied()
        return member, user, draft, snapshot

    @staticmethod
    def dto(value):
        return {key: value[key] for key in ('id', 'draft_id', 'snapshot_id', 'created', 'expires',
            'patch', 'documents', 'applied_revision')} | {
            'profile': PROFILE, 'executed': False, 'published': False,
            'model_generated': value.get('model_generated', False)}

    def propose(self, ws, wd, wv, body, actor, *, expected_context=None, model_generated=False):
        if type(model_generated) is not bool:
            raise WorkspaceInvalid()
        exact(body, ('snapshot_revision', 'draft_revision', 'changes', 'documents', 'authorized', 'notice'))
        if (not _revision(body['snapshot_revision']) or not _revision(body['draft_revision'])
                or body['authorized'] is not True or body['notice'] != NOTICE
                or type(body['changes']) is not dict or not body['changes']
                or set(body['changes']) - {'name', 'description', 'literal_input'}
                or type(body['documents']) is not list or not 1 <= len(body['documents']) <= len(DOCS)
                or any(type(value) is not str for value in body['documents'])
                or len(set(body['documents'])) != len(body['documents'])
                or set(body['documents']) - {doc['id'] for doc in DOCS}):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            member, user, draft, snapshot = self._context(ws, wd, wv, actor)
            if expected_context is not None and expected_context != _hash([member, user, draft, snapshot]):
                raise WorkspaceConflict()
            if (draft['revision'] != body['draft_revision'] or snapshot['revision'] != body['snapshot_revision']
                    or snapshot['draft_revision'] != draft['revision']):
                raise WorkspaceConflict()
            if db.execute('SELECT COUNT(*) FROM workspace_support_proposals WHERE workspace_id=?', (ws,)).fetchone()[0] >= 200:
                raise WorkspaceConflict()
            proposed = {key: copy.deepcopy(draft[key]) for key in ('name', 'description', 'definition')}
            patch = []
            for key in ('name', 'description'):
                if key in body['changes']:
                    proposed[key] = _safe_text(body['changes'][key], 120 if key == 'name' else 1000, empty=key == 'description')
                    patch.append({'op': 'replace', 'path': '/' + key, 'value': proposed[key]})
            if 'literal_input' in body['changes']:
                change = body['changes']['literal_input']
                exact(change, ('node_id', 'input'))
                if type(change['node_id']) is not str or type(change['input']) is not dict:
                    raise WorkspaceInvalid()
                selected = [(index, node) for index, node in enumerate(proposed['definition']['nodes'])
                            if node['id'] == change['node_id']]
                if len(selected) != 1 or selected[0][1].get('kind') != 'mcp': raise WorkspaceInvalid()
                index, node = selected[0]
                node['data']['input'] = copy.deepcopy(change['input'])
                patch.append({'op': 'replace', 'path': '/definition/nodes/' + str(index) + '/data/input',
                              'value': copy.deepcopy(change['input'])})
            self.access._definition(proposed['definition'], db)
            now = clock()
            payload = {'profile': PROFILE, 'id': 'wsp_'+secrets.token_hex(16), 'workspace_id': ws,
                'draft_id': wd, 'snapshot_id': wv, 'draft_revision': draft['revision'],
                'snapshot_revision': snapshot['revision'], 'definition_hash': snapshot['definition_hash'],
                'snapshot_hash': _hash(snapshot['snapshot']), 'proposed': proposed, 'patch': patch,
                'documents': body['documents'], 'document_hash': self.docs_hash(),
                'created': now, 'expires': now+900, 'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
                'user_role': user['role'], 'applied_revision': None}
            if model_generated:
                payload['model_generated'] = True
            db.execute('INSERT INTO workspace_support_proposals VALUES(?,?,?,?,?,?)',
                (payload['id'], ws, wd, wv, _canonical(payload), self.sign(payload)))
            self.access._audit(db, actor, ws, 'support.propose', payload['id'], draft['revision'])
            return self.dto(payload)

    def _load(self, db, ws, identity):
        identifier(identity, 'wsp')
        rows = _rows(db, 'SELECT * FROM workspace_support_proposals WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1: raise WorkspaceDenied()
        value = self.opened(rows[0])
        if (value['id'] != identity or value['workspace_id'] != ws
                or value['draft_id'] != rows[0]['draft_id'] or value['snapshot_id'] != rows[0]['snapshot_id']
                or value['profile'] != PROFILE): raise WorkspaceConflict()
        return value

    def apply(self, ws, identity, body, actor):
        exact(body, ('authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != APPLY_NOTICE: raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            value = self._load(db, ws, identity)
            member, user, draft, snapshot = self._context(ws, value['draft_id'], value['snapshot_id'], actor)
            if value['actor_user_id'] != actor.user_id or value['session_ref'] != actor.session_ref:
                raise WorkspaceDenied()
            if value['applied_revision'] is not None:
                return {'draft_id': value['draft_id'], 'revision': value['applied_revision'], 'applied': True,
                        'replayed': True, 'executed': False, 'published': False}
            if (value['expires'] <= clock() or value['document_hash'] != self.docs_hash()
                    or member['revision'] != value['workspace_revision']
                    or member['member_revision'] != value['member_revision'] or user['role'] != value['user_role']
                    or draft['revision'] != value['draft_revision'] or snapshot['revision'] != value['snapshot_revision']
                    or _hash(snapshot['snapshot']) != value['snapshot_hash']):
                raise WorkspaceConflict()
            proposed = value['proposed']
            _safe_text(proposed['name'], 120); _safe_text(proposed['description'], 1000, empty=True)
            self.access._definition(proposed['definition'], db)
            old = self.access._draft_row(ws, value['draft_id'])
            revision, now = draft['revision']+1, clock()
            payload = self.access._draft_payload({**old, **proposed, 'revision': revision, 'updated': now})
            changed = db.execute('''UPDATE workspace_drafts SET name=?,description=?,definition=?,revision=?,updated=?,
                payload_hash=?,signature=? WHERE workspace_id=? AND id=? AND revision=? AND active=1''',
                (proposed['name'], proposed['description'], _canonical(proposed['definition']), revision, now,
                 _hash(payload), self.access._sign(payload), ws, value['draft_id'], draft['revision'])).rowcount
            if changed != 1: raise WorkspaceConflict()
            value['applied_revision'] = revision
            db.execute('UPDATE workspace_support_proposals SET payload=?,signature=? WHERE id=? AND workspace_id=?',
                       (_canonical(value), self.sign(value), identity, ws))
            self.access._audit(db, actor, ws, 'support.apply', identity, revision)
            return {'draft_id': value['draft_id'], 'revision': revision, 'applied': True, 'replayed': False,
                    'executed': False, 'published': False}

    def proposals(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            rows = _rows(db, 'SELECT id FROM workspace_support_proposals WHERE workspace_id=? ORDER BY rowid DESC LIMIT 30', (ws,))
            return [{key: value for key, value in self.dto(self._load(db, ws, row['id'])).items()
                     if key not in ('patch', 'documents')} for row in rows]

    def proposal(self, ws, identity, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            value = self._load(db, ws, identity)
            self.access._open_draft(self.access._draft_row(ws, value['draft_id']))
            row = self.access._version_row(ws, value['draft_id'], value['snapshot_id'])
            self.access._open_version(row)
            if not row['active']: raise WorkspaceDenied()
            return self.dto(value)
