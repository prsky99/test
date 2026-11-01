"""Reviewed contract templates and private SDK lifecycle; no execution by composition."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
import secrets
import threading
import html
import json
from urllib.parse import unquote

from .capability_registry import Registry
from .capability_contracts import CONTRACTS
from .workspace_typed_flows import LIMITS as TYPED_LIMITS
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceLimit, WorkspaceInvalid, _canonical, _hash, _identity, _rows, _safe_text, _tree
from .search_quality import observed

PROFILE = 'workspace-contract-app-factory-v1'
from .workspace_admin_events import track_generation
NOTICE = 'workspace-factory-save-v1'
SDK_NOTICE = 'workspace-sdk-lifecycle-v1'
MODEL_NOTICE = 'public-objective-model-proposal-only-v1'
MODEL_PROFILE = 'bounded-model-contract-proposal-v1'
DOCS_KEY = 'agentconcierge-owned:technical-docs'
DOCS_WORDS = re.compile(r'\b(?:documentation|docs|manuals?|reference guides?|api reference|user guides?)\b', re.I)
RESEARCH_WORDS = re.compile(r'\b(?:research|papers?|studies|study|journals?|academic|scholarly|preprints?|literature)\b', re.I)

REVIEW_LIMIT, REVIEW_WINDOW = 100, 30 * 86400


def _admit_review(db, ws):
    # Reviews carry no time column; their audit rows do. Only the last 30 days count.
    recent = db.execute('''SELECT COUNT(*) FROM workspace_access_audit WHERE workspace_id=?
        AND action IN ('factory.prepare','factory.plan_review') AND created>=?''', (ws, clock() - REVIEW_WINDOW)).fetchone()[0]
    if recent >= REVIEW_LIMIT:
        raise WorkspaceLimit('This workspace made %d workflow proposals in the last 30 days, the limit. '
                             'Older proposals stop counting after 30 days. Saved workflows can still be edited and run.' % REVIEW_LIMIT)


MODEL_CONTRACTS = ('news.search.v1', 'docs.search.v1')
MODEL_SECONDS = 60
MODEL_OUTPUT_PROFILE = {'legacy_nodes': ['resource_id','contract_id','input'],
    'typed_nodes': ['id','resource_id','contract_id','input','bindings','after','when'],
    'projection': {'node_id':'declared_prior_node','path':'schema_checked_primitive_path'},
    'branch': {'node_id':'declared_prior_node','path':'boolean_or_enum_schema_path','equals':'declared_value'},
    'expressions': False, 'input_schema_coercion': False}
MODEL_ACTIVE_REQUESTS = 4
MODEL_ADMITTED_REQUESTS = 16
_proposal_pool = ThreadPoolExecutor(max_workers=MODEL_ACTIVE_REQUESTS, thread_name_prefix='reviewed-model-proposal')
_proposal_slots = threading.BoundedSemaphore(MODEL_ADMITTED_REQUESTS)
SDK_PROFILES = {'workspace-sdk-v2': '2.0.0', 'workspace-typed-sdk-v2': '2.1.0'}
RELEASE_PROFILES = {'workspace-executable-release-v1': 'workspace-sdk-v2',
                    'workspace-typed-executable-release-v1': 'workspace-typed-sdk-v2'}
TEMPLATES = (
    {'id': 'research_digest', 'name': 'News and Documentation Brief', 'contracts': ['news.search.v1', 'docs.search.v1']},
    {'id': 'documentation_crosscheck', 'name': 'Documentation Cross-check', 'contracts': ['docs.search.v1', 'docs.search.v1']},
    {'id': 'product_brief', 'name': 'Product Evidence and Documentation', 'contracts': ['products.compare.v2', 'docs.search.v1']},
)
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_factory_reviews(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_factory_commits(review_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,flow_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_sdk_policies(workspace_id TEXT NOT NULL,sdk_profile TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(workspace_id,sdk_profile))''',
    'CREATE TABLE IF NOT EXISTS workspace_expansion_restore_blocks(authority_id TEXT PRIMARY KEY)',
)


class AppFactory(SignedWorkspaceModule):
    def __init__(self, typed_flows, *, releases=None, typed_releases=None, model_proposer=None):
        if model_proposer is not None and not callable(model_proposer):
            raise WorkspaceInvalid()
        super().__init__(typed_flows.access, PROFILE, SCHEMA)
        self.typed = typed_flows
        self.releases, self.typed_releases = releases, typed_releases
        self._model_proposer = model_proposer
        self._model_generation = secrets.token_hex(16)
        for core in (releases, typed_releases):
            if core is not None:
                if core.store is not self.store: raise WorkspaceInvalid()
                core.compatibility_guard = self.enforce_compatibility

    @property
    def model_proposer(self):
        return self._model_proposer

    @model_proposer.setter
    def model_proposer(self, value):
        if value is not None and not callable(value):
            raise WorkspaceInvalid()
        self._model_proposer = value
        self._model_generation = secrets.token_hex(16)

    def _authority(self, ws, actor, *, write=False, owner=False):
        member, user = self.scope(ws, actor, write=write, owner=owner)
        return {'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
                'member_role': member['member_role'], 'user_role': user['role'], 'user_id': actor.user_id,
                'session_ref': actor.session_ref}

    def _review(self, db, ws, identity):
        _identity(identity, 'wfr')
        rows = _rows(db, 'SELECT * FROM workspace_factory_reviews WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1: raise WorkspaceDenied()
        value = self.opened(rows[0])
        if (value.get('profile') != PROFILE or value.get('id') != identity or value.get('workspace_id') != ws
                or db.execute('SELECT 1 FROM workspace_expansion_restore_blocks WHERE authority_id=?', (identity,)).fetchone()):
            raise WorkspaceDenied()
        return value

    def _pin(self, db, node):
        return self.typed._pin(db, node, self.typed._sample(node))

    def _candidates(self, db, contract):
        result = []
        rows = _rows(db, '''SELECT DISTINCT v.resource_id FROM connection_versions v JOIN capability_approvals a ON a.version_id=v.id
            WHERE a.contract_id=? ORDER BY v.resource_id LIMIT 100''', (contract,))
        for row in rows:
            rid = row['resource_id']; resource = self.store.resource(rid)
            if (not resource or not resource.get('active')
                    or resource.get('eval_security') in ('quarantine', 'review')
                    or resource.get('health_status') not in ('healthy', 'reachable')
                    or resource.get('inactive_reason')):
                continue
            try:
                node = self._node('candidate', rid, contract, 'Reviewed application task', None, [])
                self._pin(db, node)
                ready = Registry(self.store).projection(resource).get('connection_readiness', {})
                observed = ready.get('verified_at')
                observed = observed if type(observed) in (int, float) else 0
                active = resource.get('last_seen', 0)
                active = active if type(active) in (int, float) else 0
                grade = {'A': 4, 'B': 3, 'C': 2, 'D': 1}.get(resource.get('eval_grade'), 0)
                # Technical Documentation sorts last so templates keep their research sources;
                # _route_docs picks it for documentation objectives.
                result.append(((resource.get('key') != DOCS_KEY, observed, active, grade, rid), rid))
            except (WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict, ValueError, TypeError, KeyError):
                continue
        return [rid for _, rid in sorted(result, reverse=True)]

    def _route_docs(self, objective, candidates):
        """Documentation requests search documentation; research requests keep the paper indexes."""
        docs = {item['resource_id'] for item in candidates if item['contract_id'] == 'docs.search.v1'
                and (self.store.resource(item['resource_id']) or {}).get('key') == DOCS_KEY}
        if not docs:
            return candidates
        wants_docs, wants_research = bool(DOCS_WORDS.search(objective)), bool(RESEARCH_WORDS.search(objective))
        if wants_docs and not wants_research:
            return [item for item in candidates if item['contract_id'] != 'docs.search.v1' or item['resource_id'] in docs]
        if not wants_docs:
            return [item for item in candidates if item['resource_id'] not in docs]
        return candidates  # both kinds were asked for

    @staticmethod
    def _node(identity, rid, contract, purpose, from_utc, criteria):
        values = {'query': purpose, 'language': 'en', 'limit': 3}
        if contract == 'news.search.v1':
            values['from_utc'] = from_utc or (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        if contract == 'products.compare.v2':
            values['criteria'] = criteria or [{'criterion_id': 'capacity', 'dimension': 'storage'}]
        return {'id': identity, 'resource_id': rid, 'contract_id': contract, 'input': values,
                'bindings': {}, 'after': [], 'when': None}

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            authority = self._authority(ws, actor)
            return {'profile': PROFILE, 'templates': copy.deepcopy(TEMPLATES),
                    'can_edit': authority['member_role'] in ('owner', 'editor') and authority['user_role'] != 'operator',
                    'can_manage_sdk': authority['member_role'] == 'owner' and authority['user_role'] != 'operator',
                    'notice': NOTICE, 'sdk_notice': SDK_NOTICE, 'sdk_profiles': dict(SDK_PROFILES),
                    'model_proposal_configured': self.model_proposer is not None,
                    'model_candidates_available': any(self._candidates(db, contract) for contract in MODEL_CONTRACTS) if self.model_proposer is not None else False,
                    'model_proposal_notice': MODEL_NOTICE, 'model_proposal_profile': MODEL_PROFILE,
                    'model_proposal_contracts': list(MODEL_CONTRACTS),
                    'provider_calls': 0, 'automatic_execution': False, 'public_activation': False,
                    'long_lived_profiles': False, 'gateway_dependency': True}

    def prepare(self, ws, body, actor):
        exact(body, ('template_id', 'purpose', 'resource_ids', 'name', 'from_utc', 'criteria'))
        purpose = _safe_text(body['purpose'], 500); name = _safe_text(body['name'], 120)
        chosen = body['template_id']
        if chosen == 'auto':
            chosen = ('product_brief' if re.search(r'\b(compare|product|capacity)\b', purpose, re.I) else
                      'research_digest' if re.search(r'\b(news|digest|research)\b', purpose, re.I) else 'documentation_crosscheck')
        templates = [value for value in TEMPLATES if value['id'] == chosen]
        if len(templates) != 1 or body['resource_ids'] is not None and (type(body['resource_ids']) is not list
                or len(body['resource_ids']) != 2 or any(type(rid) is not int or not 0 < rid < 2**31 for rid in body['resource_ids'])
                or len(set(body['resource_ids'])) != 2): raise WorkspaceInvalid()
        if body['from_utc'] is not None:
            if type(body['from_utc']) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', body['from_utc']): raise WorkspaceInvalid()
            try: datetime.strptime(body['from_utc'], '%Y-%m-%dT%H:%M:%SZ')
            except ValueError: raise WorkspaceInvalid() from None
        if type(body['criteria']) is not list or len(body['criteria']) > 10: raise WorkspaceInvalid()
        if chosen != 'product_brief' and body['criteria'] or chosen != 'research_digest' and body['from_utc'] is not None:
            raise WorkspaceInvalid()
        template = templates[0]
        with self.access._tx(actor, write=True) as (db, _):
            authority = self._authority(ws, actor, write=True)
            _admit_review(db, ws)
            selected, definition = [], {'nodes': []}
            for ordinal, contract in enumerate(template['contracts']):
                if body['resource_ids'] is None:
                    candidates = [rid for rid in self._candidates(db, contract) if rid not in selected]
                    if not candidates: raise WorkspaceDenied()
                    rid = candidates[0]
                else: rid = body['resource_ids'][ordinal]
                selected.append(rid)
                definition['nodes'].append(self._node('step_' + str(ordinal + 1), rid, contract, purpose, body['from_utc'], body['criteria']))
            definition = self.typed._definition(definition)
            pins = {node['id']: self._pin(db, node) for node in definition['nodes']}
            now = clock(); identity = 'wfr_' + secrets.token_hex(16)
            value = {'profile': PROFILE, 'id': identity, 'workspace_id': ws, 'name': name,
                     'template_id': chosen, 'created': now, 'expires': now + 300,
                     'authority': authority, 'definition': definition, 'pins': pins}
            if hasattr(self.typed,'credits'):
                value['credit_charge']=self.typed.credits.quote_in_transaction(db,ws,(value.get('base_flow') or {}).get('id'),actor)
            db.execute('INSERT INTO workspace_factory_reviews VALUES(?,?,?,?)', (identity, ws, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'factory.prepare', identity, 1)
            return {**({'credit_charge':value['credit_charge']} if 'credit_charge' in value else {}), 'profile': PROFILE, 'review_id': identity, 'name': name, 'template_id': chosen,
                    'expires': value['expires'], 'definition': definition,
                    'destinations': [{'node_id': node['id'], 'resource_id': node['resource_id'],
                                      'contract_id': node['contract_id'], 'tool': pins[node['id']]['tool']} for node in definition['nodes']],
                    'provider_calls': 0, 'notice': NOTICE, 'requires_separate_execution_consent': True}

    def commit(self, ws, body, actor):
        exact(body, ('review_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE: raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            authority = self._authority(ws, actor, write=True)
            value = self._review(db, ws, body['review_id'])
            if value['authority'] != authority: raise WorkspaceDenied()
            previous = _rows(db, 'SELECT * FROM workspace_factory_commits WHERE review_id=? AND workspace_id=?', (value['id'], ws))
            if previous:
                receipt = self.opened(previous[0])
                if receipt.get('review_hash') != _hash(value): raise WorkspaceConflict()
                return {**receipt['flow'], 'replayed': True, 'provider_calls': 0}
            if (value.get('origin') == MODEL_PROFILE and (self.model_proposer is None
                    or value['model_proposal']['generation'] != self._model_generation)):
                raise WorkspaceDenied()
            if not value['created'] <= clock() < value['expires']: raise WorkspaceDenied()
            if value.get('base_flow'):
                _, base = self.typed._flow(db, ws, value['base_flow']['id'])
                if base['revision'] != value['base_flow']['revision'] or base['version_id'] != value['base_flow']['version_id']:
                    raise WorkspaceConflict()
            current = {node['id']: self._pin(db, node) for node in value['definition']['nodes']}
            if current != value['pins']: raise WorkspaceDenied()
            if hasattr(self.typed,'credits') and value.get('credit_charge') != self.typed.credits.quote_in_transaction(db,ws,(value.get('base_flow') or {}).get('id'),actor):
                raise WorkspaceConflict()
            # An edited workflow becomes the next revision of the same workflow (11-01), so edits no longer
            # pile up copies; runs stay pinned to their own version. A workflow at its version limit starts anew.
            base_flow = value.get('base_flow')
            if base_flow and base_flow['revision'] < TYPED_LIMITS['versions']:
                command = {'flow_id': base_flow['id'], 'revision': base_flow['revision'], 'name': value['name'], 'definition': value['definition']}
            else:
                command = {'flow_id': None, 'revision': 0, 'name': value['name'], 'definition': value['definition']}
            if hasattr(self.typed, 'save_reviewed'):
                flow = self.typed.save_reviewed(db,ws,command,actor,(value.get('base_flow') or {}).get('id'))
            else:
                flow = self.typed._save_in_transaction(db,ws,command,actor)
            receipt = {'review_hash': _hash(value), 'flow': flow}
            db.execute('INSERT INTO workspace_factory_commits VALUES(?,?,?,?,?)',
                       (value['id'], ws, flow['id'], _canonical(receipt), self.sign(receipt)))
            self.access._audit(db, actor, ws, 'factory.commit', flow['id'], flow['revision'])
            return {**flow, 'replayed': False, 'provider_calls': 0}

    def prepare_plan(self, ws, body, actor, *, _model_context=None):
        """Review an explicit typed plan; save as a new draft, never mutate a run."""
        exact(body, ('name', 'definition', 'base_flow_id', 'base_revision'))
        name = _safe_text(body['name'], 120)
        if (body['base_flow_id'] is None) != (body['base_revision'] is None):
            raise WorkspaceInvalid()
        if type(body['definition']) is not dict or type(body['definition'].get('nodes')) is not list or not 2 <= len(body['definition']['nodes']) <= TYPED_LIMITS['nodes']:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            authority = self._authority(ws, actor, write=True)
            definition = self.typed._definition(body['definition'])
            pins = {node['id']: self._pin(db, node) for node in definition['nodes']}
            if _model_context is not None:
                if (authority != _model_context['authority']
                        or self.model_proposer is not _model_context['adapter']
                        or self._model_generation != _model_context['generation']
                        or clock() >= _model_context['deadline']
                        or any(pins[node['id']] != _model_context['pins'][(node['resource_id'], node['contract_id'])]
                               for node in definition['nodes'])):
                    raise WorkspaceConflict()
            base = None; changes = []
            if body['base_flow_id'] is not None:
                _, flow = self.typed._flow(db, ws, body['base_flow_id'])
                if type(body['base_revision']) is not int or body['base_revision'] != flow['revision']:
                    raise WorkspaceConflict()
                base = {key: flow[key] for key in ('id', 'revision', 'version_id')}
                prior = self.typed._version(db, ws, flow['id'], flow['version_id'])
                old_nodes = {node['id']: node for node in prior['definition']['nodes']}
                new_nodes = {node['id']: node for node in definition['nodes']}
                for node_id in sorted(set(old_nodes) | set(new_nodes)):
                    if node_id not in old_nodes: changes.append({'node_id': node_id, 'change': 'added'})
                    elif node_id not in new_nodes: changes.append({'node_id': node_id, 'change': 'removed'})
                    else:
                        for field in ('resource_id', 'contract_id', 'input', 'bindings', 'after', 'when'):
                            if old_nodes[node_id][field] != new_nodes[node_id][field]:
                                changes.append({'node_id': node_id, 'change': field})
            _admit_review(db, ws)
            now = clock(); identity = 'wfr_' + secrets.token_hex(16)
            value = {'profile': PROFILE, 'id': identity, 'workspace_id': ws, 'name': name,
                     'template_id': 'reviewed_typed_plan', 'created': now, 'expires': now+300,
                     'authority': authority, 'definition': definition, 'pins': pins, 'base_flow': base,
                     'origin': 'explicit_new_draft_proposal'}
            if _model_context is not None:
                value['origin'] = MODEL_PROFILE
                value['model_proposal'] = {key: _model_context[key] for key in ('objective_hash', 'candidate_hash', 'generation')}
            if hasattr(self.typed,'credits'):
                value['credit_charge']=self.typed.credits.quote_in_transaction(db,ws,(value.get('base_flow') or {}).get('id'),actor)
            db.execute('INSERT INTO workspace_factory_reviews VALUES(?,?,?,?)', (identity, ws, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'factory.plan_review', identity, 1)
            return {**({'credit_charge':value['credit_charge']} if 'credit_charge' in value else {}), 'profile': PROFILE, 'review_id': identity, 'notice': NOTICE, 'expires': value['expires'],
                    'definition': definition, 'base_flow': base, 'changes': changes, 'new_draft_only': not base or base['revision'] >= TYPED_LIMITS['versions'],
                    'definition_hash': _hash(definition), 'provider_calls': 0, 'automatic_replanning': False,
                    'destinations': [{'node_id': node['id'], 'resource_id': node['resource_id'],
                                      'contract_id': node['contract_id'], 'tool': pins[node['id']]['tool']} for node in definition['nodes']],
                    'requires_separate_execution_consent': True}

    @track_generation
    @observed('workflow_generation')
    def prepare_model_proposal(self, ws, body, actor):
        """Opt-in advisory model output becomes an unexecuted exact graph review."""
        exact(body, ('objective', 'name', 'authorized', 'notice', 'data_attestation'))
        objective = _safe_text(body['objective'], 500); name = _safe_text(body['name'], 120)
        decoded = objective
        for _ in range(3):
            decoded = html.unescape(unquote(decoded))
        if (body['authorized'] is not True or body['notice'] != MODEL_NOTICE
                or body['data_attestation'] != 'public_objective_without_personal_or_private_data'
                or '@' in decoded):
            raise WorkspaceInvalid()
        adapter, generation = self.model_proposer, self._model_generation
        if adapter is None:
            raise WorkspaceDenied()
        with self.access._tx(actor) as (db, _):
            authority = self._authority(ws, actor, write=True)
            _admit_review(db, ws)
            candidates = []; pins = {}
            for contract in MODEL_CONTRACTS:
                for rid in self._candidates(db, contract)[:10]:
                    node = self._node('candidate', rid, contract, 'Public proposal candidate', None, [])
                    pins[(rid, contract)] = self._pin(db, node)
                    candidates.append({'resource_id': rid, 'contract_id': contract})
            if not candidates:
                raise WorkspaceDenied()
        # Goal parsing is English; a validated translation (outside the transaction) lets
        # Korean, Japanese and other objectives reach the same checks instead of failing them.
        normalize = getattr(adapter, 'normalize_objective', None)
        if callable(normalize):
            objective = normalize(objective) or objective
        candidates = self._route_docs(objective, candidates)
        from .workspace_goal_coverage import missing, incomplete
        try:
            unavailable=missing(objective,{item['contract_id'] for item in candidates})
        except WorkspaceInvalid as error:
            return incomplete([getattr(error,'requirement','An explicit order and two to ten supported search steps')],0)
        if unavailable:return incomplete(unavailable,0)
        envelope = {'profile': MODEL_PROFILE, 'objective': objective,
            'candidates': candidates, 'contracts': {key: {
                'input_schema':copy.deepcopy(CONTRACTS[key]['input_schema']),
                'output_schema':copy.deepcopy(CONTRACTS[key]['output_schema'])} for key in MODEL_CONTRACTS},
            'limits': {'minimum_nodes': 2, 'maximum_nodes': TYPED_LIMITS['nodes']},
            'output_profile': copy.deepcopy(MODEL_OUTPUT_PROFILE)}
        from .workflow_goal_policy import scoped_context, validate_goal, goal_sequence, GoalQueryMismatch, GoalNeedsDetails
        try:
            envelope = scoped_context(envelope)
            if goal_sequence(envelope) is None:
                return incomplete(['An explicit supported public news or documentation search objective'],0)
        except WorkspaceInvalid as error:
            return incomplete([getattr(error,'requirement','An explicit order and two to ten supported search steps')],0)
        candidates = envelope['candidates']
        slots = _proposal_slots
        if not slots.acquire(blocking=False):
            raise WorkspaceConflict()
        deadline = clock()+MODEL_SECONDS
        generation_quality = {'local_query_repairs': 0}
        def current_authority():
            with self.access._tx(actor) as (db, _):
                current = self._authority(ws, actor, write=True)
                if (current != authority or self.model_proposer is not adapter
                        or self._model_generation != generation or clock() >= deadline):
                    raise WorkspaceConflict()
                for (rid, contract), pin in pins.items():
                    node = self._node('candidate', rid, contract, 'Public proposal candidate', None, [])
                    if self._pin(db, node) != pin: raise WorkspaceConflict()
        def invoke():
            from .workflow_model_proposer import OllamaGraphProposer
            from .workflow_chatgpt import ChatGPTGraphProposer
            if type(adapter) is OllamaGraphProposer:
                def quality(repairs):
                    generation_quality['local_query_repairs'] = repairs
                return adapter.propose(copy.deepcopy(envelope), _guard=current_authority, _repair_attempts=1, _quality=quality)
            if type(adapter) is ChatGPTGraphProposer:
                return adapter.propose(copy.deepcopy(envelope), _guard=current_authority)
            current_authority()
            return adapter(copy.deepcopy(envelope))
        try:
            future = _proposal_pool.submit(invoke)
        except BaseException:
            slots.release()
            raise
        future.add_done_callback(lambda _: slots.release())
        try:
            proposal = future.result(timeout=MODEL_SECONDS)
        except GoalNeedsDetails as error:
            return incomplete([error.requirement],1)
        except GoalQueryMismatch:
            return incomplete(['A search query preserving the original subject and any stated version'],1)
        except Exception:
            # A queued task can be cancelled locally; a running remote request
            # keeps its slot until it completes and its authority is rechecked.
            future.cancel()
            # A local timeout is not a claim that the remote model request was
            # cancelled. No automatic retry or review/draft is produced.
            raise WorkspaceConflict() from None
        _tree(proposal)
        encoded = _canonical(proposal)
        if len(encoded.encode('ascii')) > 16384:
            raise WorkspaceInvalid()
        proposal = json.loads(encoded)
        exact(proposal, ('nodes',))
        if type(proposal['nodes']) is not list or not 2 <= len(proposal['nodes']) <= TYPED_LIMITS['nodes']:
            raise WorkspaceInvalid()
        definition = {'nodes': []}
        for index, item in enumerate(proposal['nodes']):
            if type(item) is not dict:
                raise WorkspaceInvalid()
            typed = set(item) == {'id','resource_id','contract_id','input','bindings','after','when'}
            if not typed:
                exact(item, ('resource_id', 'contract_id', 'input'))
            if (type(item['resource_id']) is not int or type(item['contract_id']) is not str
                    or (item['resource_id'], item['contract_id']) not in pins):
                raise WorkspaceInvalid()
            definition['nodes'].append(copy.deepcopy(item) if typed else {
                'id': 'step_'+str(index+1), 'resource_id': item['resource_id'],
                'contract_id': item['contract_id'], 'input': item['input'], 'bindings': {},
                'after': ['step_'+str(index)] if index else [], 'when': None})
        # An explicit list of subjects gets one search step per subject (up to the
        # node limit) with the agent the model chose; models tended to keep two.
        from .workspace_goal_coverage import topics
        listed = topics(objective, TYPED_LIMITS['nodes'])
        doc_nodes = [node for node in definition['nodes'] if node['contract_id'] == 'docs.search.v1']
        chosen = next(iter(doc_nodes),None)
        if len(listed) >= 2 and chosen and (chosen['resource_id'], 'docs.search.v1') in pins:
            template = {key: value for key, value in chosen['input'].items() if key != 'query'}
            template = {'language': template.get('language', 'en'), 'limit': template.get('limit', 1)}
            definition = {'nodes': [{'id': 'step_'+str(index+1), 'resource_id': doc_nodes[index % len(doc_nodes)]['resource_id'],
                'contract_id': 'docs.search.v1', 'input': {**template, 'query': subject}, 'bindings': {},
                'after': [], 'when': None} for index, subject in enumerate(listed)]}
        try:
            validate_goal(envelope,definition['nodes'])
        except GoalNeedsDetails as error:
            return incomplete([error.requirement],1)
        except GoalQueryMismatch:
            return incomplete(['A search query preserving every named subject and any stated version'],1)
        uncovered=missing(objective,{node['contract_id'] for node in definition['nodes']})
        if uncovered:return incomplete(uncovered,1)
        result = self.prepare_plan(ws, {'name': name, 'definition': definition,
            'base_flow_id': None, 'base_revision': None}, actor, _model_context={
                'authority': authority, 'adapter': adapter, 'generation': generation, 'pins': pins,
                'deadline': deadline, 'objective_hash': _hash(objective), 'candidate_hash': _hash(candidates)})
        return result | {'state': 'review_required', 'proposal_profile': MODEL_PROFILE,
            'generation_quality': generation_quality,
            'model_calls': 1, 'agent_calls': 0, 'automatic_execution': False,
            'general_natural_language_planner': False, 'shared_scope': 'attested_public_objective_and_approved_candidate_metadata_only'}

    def prepare_support_patch(self, ws, body, actor):
        """Verify a bounded JSON patch against an immutable typed version.

        The proposal always becomes a separate reviewed draft. It cannot alter
        an active run, release, authority, tool name or provider schema.
        """
        from .workflow_support import DOCS
        exact(body, ('flow_id','revision','version_id','name','patch','documents'))
        patch, documents = body['patch'], body['documents']
        if (type(patch) is not list or not 1 <= len(patch) <= 12
                or type(documents) is not list or not 1 <= len(documents) <= len(DOCS)
                or any(type(value) is not str for value in documents)
                or len(set(documents)) != len(documents) or set(documents)-{doc['id'] for doc in DOCS}):
            raise WorkspaceInvalid()
        with self.access._tx(actor) as (db,_):
            self._authority(ws,actor,write=True)
            _, flow = self.typed._flow(db,ws,body['flow_id'])
            if flow['revision'] != body['revision'] or flow['version_id'] != body['version_id']:
                raise WorkspaceConflict()
            version = self.typed._version(db,ws,flow['id'],flow['version_id'])
            definition = copy.deepcopy(version['definition'])
        seen = set()
        for operation in patch:
            exact(operation, ('op','path','value'))
            path = operation['path']
            if operation['op'] != 'replace' or type(path) is not str or path in seen:
                raise WorkspaceInvalid()
            match = re.fullmatch(r'/nodes/([0-9])/(input|bindings|after|when|resource_id)',path)
            if not match or int(match[1]) >= len(definition['nodes']):
                raise WorkspaceInvalid()
            seen.add(path)
            definition['nodes'][int(match[1])][match[2]] = copy.deepcopy(operation['value'])
        result = self.prepare_plan(ws,{'name':body['name'],'definition':definition,
            'base_flow_id':flow['id'],'base_revision':flow['revision']},actor)
        return result | {'patch':copy.deepcopy(patch),'source_documents':[dict(doc) for doc in DOCS if doc['id'] in documents],
                         'source_version_id':body['version_id'],'guidance_verified':False,'automatic_execution':False}

    def prepare_intent(self, ws, body, actor):
        """Bounded English intent proposal; ambiguity requests details, never guesses."""
        exact(body, ('purpose', 'name', 'resource_ids', 'from_utc', 'criteria'))
        purpose = _safe_text(body['purpose'], 500); _safe_text(body['name'], 120)
        with self.access._tx(actor):
            self._authority(ws, actor, write=True)
        clauses = re.split(r'\s+then\s+|\s*;\s*', purpose, flags=re.I)
        if not 2 <= len(clauses) <= TYPED_LIMITS['nodes']:
            return {'profile': PROFILE, 'state': 'needs_details', 'provider_calls': 0,
                    'questions': ['Describe two to ten steps separated by then. Identify documentation, news or a product comparison in every step.'],
                    'supported_contracts': ['docs.search.v1', 'news.search.v1', 'products.compare.v2']}
        contracts = []
        for clause in clauses:
            kinds = [contract for pattern, contract in ((r'\b(docs?|documentation|reference|manual|api)\b', 'docs.search.v1'),
                     (r'\b(news|headlines|stocks?)\b', 'news.search.v1'), (r'\b(products?|compare|capacity)\b', 'products.compare.v2'))
                     if re.search(pattern, clause, re.I)]
            if len(kinds) != 1:
                return {'profile': PROFILE, 'state': 'needs_details', 'provider_calls': 0,
                        'questions': ['Make each step one explicit supported task. Resolve mixed or unspecified goals before review.']}
            contracts.append(kinds[0])
        supplied = body['resource_ids']
        if supplied is not None and (type(supplied) is not list or len(supplied) != len(clauses)
                or any(type(rid) is not int or not 0 < rid < 2**31 for rid in supplied)):
            raise WorkspaceInvalid()
        if type(body['criteria']) is not list or len(body['criteria']) > 10:
            raise WorkspaceInvalid()
        if body['from_utc'] is not None:
            if type(body['from_utc']) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', body['from_utc']):
                raise WorkspaceInvalid()
            try: datetime.strptime(body['from_utc'], '%Y-%m-%dT%H:%M:%SZ')
            except ValueError: raise WorkspaceInvalid() from None
        selected = []; nodes = []
        with self.access._tx(actor) as (db, _):
            self._authority(ws, actor, write=True)
            for index, (clause, contract) in enumerate(zip(clauses, contracts)):
                choices = self._candidates(db, contract) if supplied is None else [supplied[index]]
                if not choices:
                    raise WorkspaceDenied()
                rid = choices[0]; selected.append(rid)
                node = self._node('step_' + str(index+1), rid, contract, clause, body['from_utc'], body['criteria'])
                node['after'] = ['step_' + str(index)] if index else []
                nodes.append(node)
        result = self.prepare_plan(ws, {'name': body['name'], 'definition': {'nodes': nodes},
                                       'base_flow_id': None, 'base_revision': None}, actor)
        return result | {'state': 'review_required', 'planner': 'bounded-english-contract-intent-v1',
                         'general_natural_language_planner': False, 'no_implicit_output_sharing': True}

    def _policy(self, db, ws, profile):
        rows = _rows(db, 'SELECT * FROM workspace_sdk_policies WHERE workspace_id=? AND sdk_profile=?', (ws, profile))
        if not rows: return None
        value = self.opened(rows[0])
        if (value.get('profile') != 'workspace-sdk-lifecycle-v1' or value.get('workspace_id') != ws
                or value.get('sdk_profile') != profile or value.get('revision') != rows[0]['revision']): raise WorkspaceConflict()
        return value

    @staticmethod
    def _owner_state(db, ws, uid):
        if type(uid) is str and uid.startswith('cu_'):
            _identity(uid, 'cu')
            rows = _rows(db, '''SELECT w.revision AS workspace_revision,m.revision AS member_revision,
                m.role AS member_role,'customer' AS user_role,u.revision AS identity_revision,
                o.revision AS organization_revision FROM organization_workspaces w
                JOIN customer_workspace_links m ON m.workspace_id=w.id
                JOIN customer_identities u ON u.id=m.customer_id
                JOIN customer_organizations o ON o.workspace_id=w.id
                WHERE w.id=? AND w.active=1 AND m.customer_id=? AND m.active=1 AND m.role='owner'
                AND u.active=1 AND o.active=1''', (ws, uid))
            return rows[0] if len(rows) == 1 else None
        rows = _rows(db, '''SELECT w.revision AS workspace_revision,m.revision AS member_revision,m.role AS member_role,u.role AS user_role
            FROM organization_workspaces w JOIN workspace_memberships m ON m.workspace_id=w.id JOIN admin_users u ON u.id=m.user_id
            WHERE w.id=? AND w.active=1 AND m.user_id=? AND m.active=1 AND u.active=1''', (ws, uid))
        return rows[0] if len(rows) == 1 else None

    def enforce_compatibility(self, db, release):
        profile = RELEASE_PROFILES.get(release.get('profile'))
        if profile is None: raise WorkspaceDenied()
        value = self._policy(db, release['workspace_id'], profile)
        if value is None: return
        owner_state = self._owner_state(db, value['workspace_id'], value['owner_id'])
        block = value['id'] + ':' + str(value['revision'])
        if (db.execute('SELECT 1 FROM workspace_expansion_restore_blocks WHERE authority_id=?', (block,)).fetchone()
                or not value['accepting_runs'] or value['sunset_at'] <= clock()
                or value['minimum_sdk_version'] != SDK_PROFILES[profile]
                or owner_state is None or value.get('owner_state') is None or owner_state != value['owner_state']):
            raise WorkspaceDenied()

    def configure_sdk(self, ws, body, actor):
        exact(body, ('sdk_profile', 'revision', 'accepting_runs', 'minimum_sdk_version', 'sunset_seconds', 'authorized', 'notice'))
        profile = body['sdk_profile']
        if (type(profile) is not str or profile not in SDK_PROFILES or type(body['revision']) is not int or body['revision'] < 0
                or type(body['accepting_runs']) is not bool or body['minimum_sdk_version'] != SDK_PROFILES[profile]
                or type(body['sunset_seconds']) is not int or not 300 <= body['sunset_seconds'] <= 2592000
                or body['authorized'] is not True or body['notice'] != SDK_NOTICE): raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._authority(ws, actor, write=True, owner=True)
            prior = self._policy(db, ws, profile); revision = prior['revision'] if prior else 0
            if revision != body['revision'] or revision >= 100: raise WorkspaceConflict()
            owner_state = self._owner_state(db, ws, actor.user_id)
            if owner_state is None: raise WorkspaceDenied()
            now = clock(); value = {'profile': 'workspace-sdk-lifecycle-v1', 'id': 'wlp_' + _hash([ws, profile])[:32],
                'workspace_id': ws, 'sdk_profile': profile, 'minimum_sdk_version': SDK_PROFILES[profile],
                'revision': revision + 1, 'accepting_runs': body['accepting_runs'], 'sunset_at': now + body['sunset_seconds'],
                'owner_id': actor.user_id, 'owner_state': owner_state, 'created': now}
            if prior is None:
                db.execute('INSERT INTO workspace_sdk_policies VALUES(?,?,?,?,?)',
                    (ws, profile, value['revision'], _canonical(value), self.sign(value)))
            elif db.execute('''UPDATE workspace_sdk_policies SET revision=?,payload=?,signature=?
                    WHERE workspace_id=? AND sdk_profile=? AND revision=?''',
                    (value['revision'], _canonical(value), self.sign(value), ws, profile, revision)).rowcount != 1:
                raise WorkspaceConflict()
            self.access._audit(db, actor, ws, 'sdk_policy.configure', value['id'], value['revision'])
            return {key: value[key] for key in ('sdk_profile', 'revision', 'minimum_sdk_version', 'accepting_runs', 'sunset_at')}

    def catalog(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            authority = self._authority(ws, actor); policies = []
            for profile, version in SDK_PROFILES.items():
                policy = self._policy(db, ws, profile)
                owner_state = self._owner_state(db, ws, policy['owner_id']) if policy else None
                policies.append({'sdk_profile': profile, 'minimum_sdk_version': version,
                    'revision': policy['revision'] if policy else 0,
                    'accepting_runs': policy['accepting_runs'] if policy else True,
                    'sunset_at': policy['sunset_at'] if policy else None,
                    'current_owner': policy is None or (owner_state is not None and policy.get('owner_state') is not None
                        and owner_state == policy['owner_state']),
                    'restored_block': bool(policy and db.execute('SELECT 1 FROM workspace_expansion_restore_blocks WHERE authority_id=?',
                        (policy['id'] + ':' + str(policy['revision']),)).fetchone())})
            releases = []
            if self.releases is not None:
                for row in _rows(db, 'SELECT * FROM workspace_executable_releases WHERE workspace_id=? ORDER BY created DESC LIMIT 100', (ws,)):
                    value = self.releases._open(row); profile = RELEASE_PROFILES.get(value.get('profile'))
                    if profile is None: raise WorkspaceConflict()
                    core = self.typed_releases if profile == 'workspace-typed-sdk-v2' else self.releases
                    if core is None: raise WorkspaceConflict()
                    _, value = core._release(db, row['id'], active=False)
                    blocked = False
                    try: self.enforce_compatibility(db, value)
                    except WorkspaceDenied: blocked = True
                    deployments = []
                    for entry in _rows(db, 'SELECT * FROM workspace_release_deployments WHERE release_id=? ORDER BY created DESC LIMIT 100', (row['id'],)):
                        entry, payload = core._deployment(db, entry['app_id'], active=False)
                        deployments.append({**core._dto(entry, True), 'allowed_origins': payload['allowed_origins']})
                    releases.append({**core._dto(row), 'sdk_profile': profile, 'sdk_version': SDK_PROFILES[profile],
                        'catalog_hash': _hash(value), 'blocked_by_sdk_policy': blocked, 'deployments': deployments,
                        'requires_current_execution_review': True})
            result = {'profile': PROFILE, 'policies': policies, 'releases': releases, 'provider_calls': 0,
                      'public_sdk1_unchanged': True, 'customer_workspace_public': False, 'gateway_dependency': True}
            # This server MAC protects this private projection; it is not a public
            # signature, a deployment grant or an execution capability.
            return {**result, 'projection_mac': self.sign({'workspace_id': ws, 'authority': authority, 'result': result})}
