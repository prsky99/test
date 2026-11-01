"""Independent publication authority for one bounded canonical public connection.

Candidates, explicit private tests, publication and public per-run sharing are
different signed purposes. No private typed/pair or deployment purpose is reused.
"""
import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

from .capability_contracts import validate
from .capability_registry import canonical, digest
from .concierge.execution_policy import ExecutionDenied
from . import workflow_public_flow as flow

PROFILE = flow.PROFILE
SOURCE_NODE = flow.SOURCE_NODE
NODE = flow.NODE
TEST_SHARE_NOTICE = 'workflow-public-flow-test-share-v1'
TEST_RUN_NOTICE = 'workflow-public-flow-test-run-v1'
PUBLISH_NOTICE = 'workflow-public-flow-publish-v1'
SHARE_NOTICE = 'workflow-public-flow-share-v1'
RUN_NOTICE = 'workflow-public-flow-run-v1'
CANDIDATE = 'workflow-public-flow-candidate-v1'
PUBLISH_PLAN = 'workflow-public-flow-publication-plan-v1'
TICKET = 'workflow-public-flow-ticket-v1'
TTL = 900
NAME = 'Reviewed news to documentation connection'
DESCRIPTION = 'One news search, then one documentation search using only its first verified safe title.'
SCHEMA = '''CREATE TABLE IF NOT EXISTS workflow_publication_grants (
 id TEXT PRIMARY KEY,workflow_id INTEGER NOT NULL UNIQUE,revision INTEGER NOT NULL,
 active INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
 created REAL NOT NULL,expires REAL NOT NULL,revoked REAL);
'''
DECLARATIONS = {'proposal', 'signature', 'sharing_authority', 'sharing_notice', 'run_authority', 'run_notice'}


def stable_json(value):
    """Normalize integral floats before signing browser-transported JSON."""
    if isinstance(value, dict): return {key: stable_json(item) for key, item in value.items()}
    if isinstance(value, list): return [stable_json(item) for item in value]
    return flow.stamp(value)


class Publication:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store
        with self.store._lock: self.store._db.executescript(SCHEMA)

    def _owner(self, actor):
        owner = str(actor) if type(actor) is int else actor
        if not isinstance(owner, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', owner): raise ValueError('A current highest administrator is required.')
        rows = self.store.query('SELECT role,active FROM admin_users WHERE id=?', (int(owner),))
        if len(rows) != 1 or rows[0]['role'] != 'superadmin' or not rows[0]['active']: raise ValueError('Highest-administrator authority changed.')
        return owner

    def _epoch(self, reviewed_at):
        rows = self.store.query('SELECT updated FROM execution_controls WHERE id=1')
        if len(rows) != 1 or flow.timestamp(rows[0]['updated']) > flow.timestamp(reviewed_at): raise ValueError('Execution controls changed; review a new purpose.')

    def _envelope(self, value):
        value = stable_json(value)
        return {'proposal': value, 'signature': self.runtime.authority.signature(value)}

    def _unpack(self, body, audience, fields):
        value = body['proposal']; signature = body['signature']
        if (not isinstance(value, dict) or set(value) != fields or len(canonical(value)) > 90000
                or value['audience'] != audience or not isinstance(signature, str)
                or not hmac.compare_digest(signature, self.runtime.authority.signature(value))): raise ValueError('The signed review changed.')
        created = flow.timestamp(value['created']); expires = flow.timestamp(value['expires'])
        if created > time.time() + 5 or not created <= time.time() < expires: raise ValueError('The signed review expired.')
        return value

    @staticmethod
    def _declared(body, share, run):
        if (not isinstance(body, dict) or set(body) != DECLARATIONS or body['sharing_authority'] is not True
                or body['sharing_notice'] != share or body['run_authority'] is not True or body['run_notice'] != run):
            raise ValueError('Separate current input-sharing and one live-run authorizations are required.')

    def options(self, actor):
        self._owner(actor)
        def choices(contract): return [{key: item[key] for key in ('id', 'label')} for item in self.runtime.composer.candidates(contract, allow_empty=True)]
        news, docs = choices('news.search.v1'), choices('docs.search.v1')
        return {'ok': True, 'profile': PROFILE, 'news': news, 'docs': docs, 'available': bool(news and docs),
                'notices': {'share': TEST_SHARE_NOTICE, 'run': TEST_RUN_NOTICE, 'publish': PUBLISH_NOTICE}}

    def _preview(self, workflow, expires):
        source, target = flow.definition(self.runtime, workflow, current=False)
        def label(value, prefix): return prefix + ' agent ' + value['pin']['version']['agent_ref'][-8:]
        return {'source': {'label': label(source, 'News'), 'contract': 'news.search.v1', 'input': copy.deepcopy(source['input'])},
                'target': {'label': label(target, 'Documentation'), 'contract': 'docs.search.v1', 'settings': copy.deepcopy(target['input'])},
                'connection': {'path': ['items', 0, 'title'], 'target_field': 'query'},
                'expires': flow.stamp(expires), 'max_calls': 2, 'max_seconds': 25}

    def candidate(self, body, actor):
        owner = self._owner(actor)
        if not isinstance(body, dict) or set(body) != {'source_id', 'target_id', 'query', 'from_utc', 'limit'}: raise ValueError('Review one news source, documentation target and fixed public inputs.')
        query = flow.public_title(body['query']); limit = body['limit']
        if type(limit) is not int or not 1 <= limit <= 5: raise ValueError('Use one to five results.')
        news = {item['id']: item for item in self.runtime.composer.candidates('news.search.v1')}
        docs = {item['id']: item for item in self.runtime.composer.candidates('docs.search.v1')}
        if body['source_id'] not in news or body['target_id'] not in docs: raise ValueError('Choose currently approved candidates.')
        created = flow.stamp(time.time()); nonce = secrets.token_hex(16)
        source = {'audience': SOURCE_NODE, 'contract': 'news.search.v1', 'pin': copy.deepcopy(news[body['source_id']]['pin']),
                  'input': {'query': query, 'language': 'en', 'limit': limit, 'from_utc': body['from_utc']},
                  'profile': PROFILE, 'nonce': nonce, 'owner': owner, 'reviewed_at': created}
        validate('news.search.v1', source['input'])
        target = {'audience': NODE, 'contract': 'docs.search.v1', 'pin': copy.deepcopy(docs[body['target_id']]['pin']),
                  'input': {'language': 'en', 'limit': limit}}
        def node(nid, name, binding, x):
            return {'id': nid, 'name': name, 'type': 'agent', 'kind': 'mcp', 'resource_id': binding['pin']['resource_id'],
                    'position': {'x': x, 'y': 180}, 'data': {'tool': binding['pin']['approval']['tool'], 'input': copy.deepcopy(binding['input']), 'composition': flow.signed(self.runtime, binding)}}
        # Normalize the complete binding before signing; client JSON never
        # weakens verification by reinterpreting 0.0 as another signed value.
        source = stable_json(source); target = stable_json(target)
        source_node = node(flow.IDS[1], 'News source', source, 360)
        target['connection'] = flow.connection(source_node, target)
        workflow = {'name': NAME, 'description': DESCRIPTION, 'category': 'data_utility', 'trigger_type': 'manual',
                    'nodes': [{'id': 'start', 'name': 'Manual reviewed run', 'type': 'trigger', 'kind': 'trigger', 'position': {'x': 60, 'y': 180}, 'data': {}},
                              source_node, node(flow.IDS[2], 'Documentation target', target, 660)],
                    'edges': copy.deepcopy(list(flow.EDGES)), 'is_active': 1, 'is_template': 0,
                    'tags': 'public-flow-candidate:' + nonce, 'author': 'Public flow owner ' + owner}
        flow.definition(self.runtime, workflow)
        proposal = {'audience': CANDIDATE, 'owner': owner, 'nonce': nonce, 'created': created, 'expires': created + TTL, 'workflow': workflow}
        return {'ok': True, 'profile': PROFILE, **self._envelope(proposal), 'preview': self._preview(workflow, created + TTL),
                'executed': False, 'notices': {'share': TEST_SHARE_NOTICE, 'run': TEST_RUN_NOTICE, 'publish': PUBLISH_NOTICE}}

    def _candidate(self, body, owner):
        value = self._unpack(body, CANDIDATE, {'audience', 'owner', 'nonce', 'created', 'expires', 'workflow'})
        if (value['owner'] != owner or value['expires'] != value['created'] + TTL
                or not isinstance(value['nonce'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['nonce'])): raise ValueError('The candidate belongs to another review.')
        workflow = value['workflow']; source, _ = flow.definition(self.runtime, workflow)
        if (source['owner'] != owner or source['nonce'] != value['nonce'] or source['reviewed_at'] != value['created']
                or workflow.get('tags') != 'public-flow-candidate:' + value['nonce'] or workflow.get('author') != 'Public flow owner ' + owner
                or workflow.get('name') != NAME or workflow.get('description') != DESCRIPTION or workflow.get('category') != 'data_utility'
                or set(workflow) != {'name', 'description', 'category', 'trigger_type', 'nodes', 'edges', 'is_active', 'is_template', 'tags', 'author'}): raise ValueError('The reviewed canonical candidate changed.')
        self._epoch(value['created'])
        return value

    def _reserve(self, proposal):
        from .gateway.store import _graph_to_steps
        workflow = proposal['workflow']; packaged = {'nodes': workflow['nodes'], 'edges': workflow['edges'], 'steps': _graph_to_steps(workflow['nodes'], workflow['edges'])}
        with self.store._lock:
            if self.store._db.in_transaction: raise ValueError('Canonical reservation is temporarily unavailable.')
            with self.store.tx() as db:
                db.execute('BEGIN IMMEDIATE')
                rows = db.execute('SELECT id,name,description,category,trigger_type,steps,tags,is_active,is_template,author FROM agent_workflows WHERE tags=? LIMIT 2', (workflow['tags'],)).fetchall()
                if len(rows) > 1: raise ValueError('The canonical reservation is ambiguous.')
                if rows:
                    row = dict(rows[0])
                    if any(row[key] != workflow[key] for key in ('name', 'description', 'category', 'trigger_type', 'tags', 'is_active', 'is_template', 'author')) or json.loads(row['steps']) != packaged: raise ValueError('The reserved canonical definition changed.')
                    identity = row['id']
                else:
                    count = db.execute("SELECT COUNT(*) FROM agent_workflows WHERE author=? AND tags LIKE 'public-flow-candidate:%' AND created_at>?", (workflow['author'], time.time() - 3600)).fetchone()[0]
                    if count >= 20: raise ValueError('The canonical test preparation limit has been reached.')
                    now = time.time()
                    identity = db.execute('INSERT INTO agent_workflows(name,description,category,trigger_type,steps,tags,is_active,is_template,author,created_at,updated_at) VALUES (?,?,?,?,?,?,1,0,?,?,?)',
                                          (workflow['name'], workflow['description'], workflow['category'], workflow['trigger_type'], canonical(packaged), workflow['tags'], workflow['author'], now, now)).lastrowid
        return {**copy.deepcopy(workflow), 'id': identity}

    def test(self, body, actor):
        owner = self._owner(actor); self._declared(body, TEST_SHARE_NOTICE, TEST_RUN_NOTICE)
        candidate = self._candidate(body, owner); workflow = self._reserve(candidate)
        context = {'mode': 'test', **{key: body[key] for key in DECLARATIONS}}
        principal = self.runtime.principal('admin', owner, workflow['id'], role='superadmin')
        args = {'actor': 'publication-test:' + owner, 'source': 'admin', 'idempotency': candidate['nonce'], 'principal': principal, 'publication_context': context}
        try: job = self.runtime.submit(workflow, **args)
        except sqlite3.IntegrityError: job = self.runtime.submit(workflow, **args)
        return {'ok': True, 'profile': PROFILE, **job, 'workflow_id': workflow['id'], 'replayed': bool(job.get('replayed'))}

    def _history(self, store, run_id):
        rows = store.query('SELECT id,workflow_id,digest,substr(snapshot,1,180001) AS snapshot,actor,source,status,execution_outcome,created,idempotency_key FROM workflow_runs WHERE id=?', (run_id,))
        if len(rows) != 1 or len(rows[0]['snapshot']) > 180000: raise ValueError('A retained canonical test is required.')
        row = dict(rows[0]); workflow = json.loads(row['snapshot']); source, _ = flow.definition(self.runtime, workflow, current=False, now=row['created'])
        if digest(workflow) != row['digest'] or workflow['id'] != row['workflow_id'] or row['source'] != 'admin' or row['actor'] != 'publication-test:' + source['owner'] or row['idempotency_key'] != source['nonce']: raise ValueError('The canonical test scope changed.')
        records = store.query('SELECT substr(payload,1,16385) AS payload,signature FROM workflow_run_authority WHERE run_id=?', (run_id,))
        if len(records) != 1 or len(records[0]['payload']) > 16384: raise ValueError('Retained test authority is required.')
        authority = json.loads(records[0]['payload']); envelope = authority['principal']; principal = envelope['payload']
        if (not hmac.compare_digest(records[0]['signature'], self.runtime.authority.signature(authority))
                or not hmac.compare_digest(envelope['signature'], self.runtime.authority.signature(principal))
                or any(authority.get(key) != value for key, value in {'run_id': run_id, 'workflow_id': workflow['id'], 'digest': row['digest'], 'source': 'admin', 'grant_id': None}.items())
                or principal.get('kind') != 'admin' or principal.get('role') != 'superadmin' or principal.get('subject') != source['owner']
                or principal.get('audience') != 'workflow-runtime-v1' or principal.get('workflow_id') != workflow['id']
                or principal.get('public_connection') != self._test_scope(workflow)
                or flow.timestamp(principal.get('expires')) <= flow.timestamp(row['created'])): raise ValueError('The retained canonical test authority is invalid.')
        budgets = store.query('SELECT payload,signature FROM workflow_execution_budgets WHERE run_id=?', (run_id,))
        expected = {'audience': 'workflow-budget-v1', 'run_id': run_id, 'digest': row['digest'], 'source': 'admin', 'profile': 'standard', 'total_seconds': 25, 'node_seconds': 25}
        if len(budgets) != 1 or json.loads(budgets[0]['payload']) != expected or not hmac.compare_digest(budgets[0]['signature'], self.runtime.authority.signature(expected)): raise ValueError('The canonical test budget changed.')
        return row, workflow, principal

    def proof(self, run_id, owner):
        from .workflow_comparison import Comparison
        with Comparison(self.runtime).reader() as store:
            row, workflow, principal = self._history(store, run_id)
            if principal['subject'] != owner or row['status'] != 'succeeded' or row['execution_outcome'] != 'succeeded': raise ValueError('A successful explicit test of this canonical definition is required.')
            if len(store.query('SELECT 1 FROM workflow_execution_attempts WHERE run_id=?', (run_id,))) != 2 or store.query('SELECT 1 FROM workflow_routing_attempts WHERE run_id=? LIMIT 1', (run_id,)): raise ValueError('A canonical test may contain only its two certain attempts.')
            if {item['node_id'] for item in store.query('SELECT node_id FROM workflow_checkpoints WHERE run_id=?', (run_id,))} != set(flow.IDS): raise ValueError('The canonical test checkpoint set changed.')
            start_rows = store.query("SELECT substr(payload,1,262145) AS payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id='start'", (run_id,))
            if len(start_rows) != 1 or len(start_rows[0]['payload']) > 262144: raise ValueError('The signed manual trigger is unavailable.')
            start_cp = json.loads(start_rows[0]['payload']); start = start_cp['record']
            if (not hmac.compare_digest(start_rows[0]['signature'], self.runtime.authority.signature(start_cp))
                    or any(start_cp.get(key) != value for key, value in {'audience': 'workflow-checkpoint-v1', 'run_id': run_id, 'digest': row['digest'], 'node_id': 'start'}.items())
                    or start['node_id'] != 'start' or start['type'] != 'trigger' or start['kind'] != 'trigger' or start['status'] != 'succeeded'
                    or start['resource_id'] is not None or start['input'] != {} or start['data'] != {'trigger': 'manual'}
                    or start_cp['flow_output'] != start['data'] or start_cp.get('typed_input') is not None
                    or flow.timestamp(start['latency_ms']) > 60000 or flow.timestamp(start['started']) < row['created']
                    or start['started'] >= principal['expires']): raise ValueError('The signed manual trigger is invalid.')
            source_cp, _ = flow.source_proof(self.runtime, row, workflow, store=store, expires=principal['expires'], current=False)
            if source_cp['record']['started'] < start['started'] + start['latency_ms'] / 1000: raise ValueError('The signed source predates the manual trigger.')
            args, provenance = flow.resolved(self.runtime, row, workflow, store=store, expires=principal['expires'], current=False)
            target_cp = flow.checkpoint(self.runtime, store, row, workflow['nodes'][2], expires=principal['expires'])
            source_end = source_cp['record']['started'] + source_cp['record']['latency_ms'] / 1000
            target = target_cp['record']; observed = target['started'] + target['latency_ms'] / 1000
            if target['started'] < source_end or target['input'] != args or target_cp.get('typed_input') != provenance: raise ValueError('The canonical test derived-input provenance changed.')
            validate('docs.search.v1', args, target['data'].get('structuredContent', target['data']), now=observed)
            valid_until = min(source_end, observed) + 86400
            if valid_until <= time.time(): raise ValueError('The retained canonical test expired.')
            return workflow, {'run_id': run_id, 'definition_hash': digest(flow.graph_value(workflow)),
                              'source_checkpoint_hash': digest(source_cp), 'target_checkpoint_hash': digest(target_cp),
                              'valid_until': valid_until, 'tested_at': observed}

    def test_history(self, actor):
        owner = self._owner(actor); tests = []
        from .workflow_comparison import Comparison
        with Comparison(self.runtime).reader() as store:
            for item in store.query("SELECT id FROM workflow_runs WHERE actor=? AND source='admin' ORDER BY created DESC LIMIT 30", ('publication-test:' + owner,)):
                try: row, _, _ = self._history(store, item['id'])
                except (ValueError, TypeError, KeyError): continue
                tests.append({'run_id': row['id'], 'status': row['status'], 'outcome': row['execution_outcome'], 'created': row['created'], 'recorded_at': row['created']})
        return {'ok': True, 'profile': PROFILE, 'tests': tests}

    def inspect_test(self, run_id, actor):
        owner = self._owner(actor)
        from .workflow_comparison import Comparison
        with Comparison(self.runtime).reader() as store:
            row, workflow, principal = self._history(store, run_id)
            if principal['subject'] != owner: raise ValueError('The canonical test belongs to another owner.')
        available = False
        try: _, evidence = self.proof(run_id, owner); available = True
        except (ValueError, TypeError, KeyError, IndexError): evidence = None
        return {'ok': True, 'profile': PROFILE, 'run_id': run_id, 'status': row['status'], 'outcome': row['execution_outcome'],
                'run': {'run_id': run_id, 'status': row['status'], 'outcome': row['execution_outcome']},
                'publication_eligible': available, 'preview': self._preview(workflow, time.time()),
                'evidence': {'retained_certain_test': available}, 'expert_reviewed': False, 'holdout_verified': False}

    def publication_candidate(self, body, actor):
        owner = self._owner(actor)
        if not isinstance(body, dict) or set(body) != {'run_id', 'ttl_seconds'} or type(body['ttl_seconds']) is not int or not 300 <= body['ttl_seconds'] <= 86400: raise ValueError('Choose one retained canonical test and a bounded publication duration.')
        workflow, evidence = self.proof(body['run_id'], owner)
        current = self.store.get_workflow(workflow['id'])
        if flow.graph_value(current) != flow.graph_value(workflow): raise ValueError('The saved canonical definition changed.')
        flow.definition(self.runtime, current)
        created = flow.stamp(time.time()); expires = flow.stamp(min(created + body['ttl_seconds'], evidence['valid_until']))
        if expires - created < 300: raise ValueError('A fresh retained canonical test is required.')
        proposal = {'audience': PUBLISH_PLAN, 'owner': owner, 'created': created, 'expires': min(created + TTL, expires),
                    'workflow_id': workflow['id'], 'test_run_id': body['run_id'], 'definition_hash': digest(flow.graph_value(workflow)),
                    'proof_hash': digest(evidence), 'grant_expires': expires, 'nonce': secrets.token_hex(16)}
        return {'ok': True, 'profile': PROFILE, **self._envelope(proposal), 'preview': {**self._preview(workflow, expires), 'tested_at': evidence['tested_at']},
                'executed': False, 'publication_notice': PUBLISH_NOTICE}

    def publish(self, body, actor):
        owner = self._owner(actor)
        if (not isinstance(body, dict) or set(body) != {'proposal', 'signature', 'publication_authority', 'publication_notice'}
                or body['publication_authority'] is not True or body['publication_notice'] != PUBLISH_NOTICE): raise ValueError('Separate current publication authorization is required.')
        p = self._unpack(body, PUBLISH_PLAN, {'audience', 'owner', 'created', 'expires', 'workflow_id', 'test_run_id', 'definition_hash', 'proof_hash', 'grant_expires', 'nonce'})
        if p['owner'] != owner or p['expires'] != min(p['created'] + TTL, p['grant_expires']): raise ValueError('The publication review belongs to another purpose.')
        self._epoch(p['created']); workflow, evidence = self.proof(p['test_run_id'], owner)
        current = self.store.get_workflow(p['workflow_id']); flow.definition(self.runtime, current)
        if (flow.graph_value(workflow) != flow.graph_value(current) or digest(flow.graph_value(current)) != p['definition_hash']
                or digest(evidence) != p['proof_hash'] or not time.time() < flow.timestamp(p['grant_expires']) <= min(p['created'] + 86400, evidence['valid_until'])): raise ValueError('The reviewed canonical definition or proof changed.')
        identity = 'pub_' + secrets.token_hex(16); created = time.time()
        from .concierge.connections import bindings, gateway_agent_url
        private_connections = [{'gateway': gateway_agent_url(node['resource_id'], 'mcp'),
                                'raw_urls': sorted(bindings(self.store.resource(node['resource_id'])))} for node in workflow['nodes'][1:]]
        payload = {'audience': PUBLISH_NOTICE, 'profile': PROFILE, 'id': identity, 'workflow_id': workflow['id'], 'revision': 1,
                   'owner': owner, 'created': created, 'reviewed_at': p['created'], 'expires': p['grant_expires'],
                   'definition_hash': p['definition_hash'], 'workflow': workflow, 'proof': evidence,
                   'preview': self._preview(workflow, p['grant_expires']), 'private_connections': private_connections}
        with self.store.tx() as db:
            db.execute('INSERT INTO workflow_publication_grants VALUES (?,?,1,1,?,?,?,?,NULL)',
                       (identity, workflow['id'], canonical(payload), self.runtime.authority.signature(payload), created, p['grant_expires']))
        return {'ok': True, **self._metadata(payload), 'revision': 1, 'active': True, 'public_url': '/connections/' + identity}

    @staticmethod
    def _metadata(payload):
        return {'id': payload['id'], 'title': NAME, 'description': DESCRIPTION, 'expires': payload['expires'], 'url': '/connections/' + payload['id']}

    def metadata(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'pub_[a-f0-9]{32}', identity): raise ValueError('The publication is unavailable.')
        rows = self.store.query('SELECT * FROM workflow_publication_grants WHERE id=? AND active=1', (identity,))
        if len(rows) != 1 or len(rows[0]['payload']) > 180000: raise ValueError('The publication is unavailable.')
        row = dict(rows[0]); payload = json.loads(row['payload'])
        if (not hmac.compare_digest(row['signature'], self.runtime.authority.signature(payload))
                or payload.get('audience') != PUBLISH_NOTICE or payload.get('profile') != PROFILE or row['revoked'] is not None
                or type(payload.get('revision')) is not int or payload['revision'] < 1
                or any(payload.get(key) != row[key] for key in ('id', 'workflow_id', 'revision', 'created', 'expires'))
                or not flow.timestamp(payload['created']) <= time.time() < flow.timestamp(payload['expires'])): raise ValueError('The publication was revoked, expired or changed.')
        self._owner(payload['owner'])
        return payload

    def current(self, identity):
        payload = self.metadata(identity); self._epoch(payload['reviewed_at'])
        workflow = self.store.get_workflow(payload['workflow_id']); flow.definition(self.runtime, workflow)
        if flow.graph_value(workflow) != flow.graph_value(payload['workflow']) or digest(flow.graph_value(workflow)) != payload['definition_hash']: raise ValueError('The published canonical definition changed.')
        _, evidence = self.proof(payload['proof']['run_id'], payload['owner'])
        if evidence != payload['proof']: raise ValueError('The original retained publication proof changed.')
        return payload, workflow

    def releases(self, actor):
        owner = self._owner(actor); releases = []
        for row in self.store.query('SELECT id,revision,active,created,expires,revoked,payload FROM workflow_publication_grants ORDER BY created DESC LIMIT 50'):
            payload = json.loads(row['payload'])
            if payload.get('owner') == owner:
                releases.append({'id': row['id'], 'title': NAME, 'revision': row['revision'], 'active': bool(row['active']), 'created': row['created'], 'expires': row['expires'], 'revoked': row['revoked'], 'url': '/connections/' + row['id'], 'public_url': '/connections/' + row['id']})
        return {'ok': True, 'profile': PROFILE, 'releases': releases}

    def revoke(self, identity, revision, actor):
        owner = self._owner(actor)
        if type(revision) is not int: raise ValueError('Use the current publication revision.')
        rows = self.store.query('SELECT payload FROM workflow_publication_grants WHERE id=?', (identity,))
        if len(rows) != 1 or json.loads(rows[0]['payload']).get('owner') != owner: raise ValueError('The publication belongs to another owner.')
        with self.store.tx() as db:
            if db.execute('UPDATE workflow_publication_grants SET active=0,revision=revision+1,revoked=? WHERE id=? AND revision=? AND active=1', (time.time(), identity, revision)).rowcount != 1: raise ValueError('The publication revision changed.')
        for run in self.store.query("SELECT id FROM workflow_runs WHERE actor=? AND status IN ('queued','running')", ('public-flow:' + identity,)): self.runtime.cancel(run['id'])
        if self.store.query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_connection_deployments'"):
            for run in self.store.query("SELECT r.id FROM workflow_runs r JOIN workflow_connection_deployments d ON r.actor='connection-app:'||d.id WHERE d.release_id=? AND r.status IN ('queued','running')", (identity,)):
                self.runtime.cancel(run['id'])
        if self.store.query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_connection_automation'"):
            for grant in self.store.query('SELECT id FROM workflow_connection_automation WHERE release_id=?',(identity,)):
                self.runtime.automation.cancel(grant['id'])
        return {'ok': True, 'id': identity, 'active': False, 'revision': revision + 1}

    def public_list(self):
        releases = []
        for row in self.store.query('SELECT id FROM workflow_publication_grants WHERE active=1 AND expires>? ORDER BY created DESC LIMIT 20', (time.time(),)):
            try: payload, _ = self.current(row['id'])
            except (ValueError, TypeError, KeyError, IndexError): continue
            releases.append(self._metadata(payload))
        return {'ok': True, 'profile': PROFILE, 'releases': releases}

    def public_projection(self, identity):
        payload = self.metadata(identity)
        return {'ok': True, 'profile': PROFILE, **self._metadata(payload)}

    def prepare_run(self, identity):
        payload, workflow = self.current(identity); created = flow.stamp(time.time())
        proposal = {'audience': TICKET, 'profile': PROFILE, 'release_id': identity, 'revision': payload['revision'],
                    'definition_hash': payload['definition_hash'], 'rule_hash': digest(workflow['nodes'][2]['data']['composition']['payload']['connection']),
                    'nonce': secrets.token_hex(16), 'created': created, 'expires': flow.stamp(min(created + 300, payload['expires'])),
                    'reviewed_at': created, 'sharing_notice': SHARE_NOTICE, 'run_notice': RUN_NOTICE}
        return {'ok': True, 'profile': PROFILE, **self._envelope(proposal), 'preview': self._preview(workflow, proposal['expires']),
                'executed': False, 'notices': {'share': SHARE_NOTICE, 'run': RUN_NOTICE}}

    def _public_ticket(self, identity, body):
        self._declared(body, SHARE_NOTICE, RUN_NOTICE)
        p = self._unpack(body, TICKET, {'audience', 'profile', 'release_id', 'revision', 'definition_hash', 'rule_hash', 'nonce', 'created', 'expires', 'reviewed_at', 'sharing_notice', 'run_notice'})
        payload, workflow = self.current(identity)
        if (p['profile'] != PROFILE or p['release_id'] != identity or type(p['revision']) is not int or p['revision'] != payload['revision']
                or p['definition_hash'] != payload['definition_hash'] or p['rule_hash'] != digest(workflow['nodes'][2]['data']['composition']['payload']['connection'])
                or p['sharing_notice'] != SHARE_NOTICE or p['run_notice'] != RUN_NOTICE or p['reviewed_at'] != p['created']
                or p['expires'] > min(p['created'] + 300, payload['expires'])
                or not isinstance(p['nonce'], str) or not re.fullmatch(r'[a-f0-9]{32}', p['nonce'])): raise ValueError('The public run ticket changed.')
        self._epoch(p['reviewed_at'])
        return p, workflow

    def accepted_run(self, identity, body):
        p, workflow = self._public_ticket(identity, body)
        rows = self.store.query('SELECT * FROM workflow_runs WHERE actor=? AND idempotency_key=?', ('public-flow:' + identity, p['nonce']))
        if not rows: return None
        self.replay_scope(dict(rows[0]), self._public_scope(body))
        return rows[0]['id']

    def execute_run(self, identity, body):
        p, workflow = self._public_ticket(identity, body)
        principal = self.runtime.principal('public', identity, workflow['id'])
        args = {'actor': 'public-flow:' + identity, 'source': 'public', 'public': True, 'idempotency': p['nonce'],
                'principal': principal, 'publication_context': {'mode': 'public', **body}}
        try: job = self.runtime.submit(workflow, **args)
        except sqlite3.IntegrityError: job = self.runtime.submit(workflow, **args)
        return {'ok': True, 'profile': PROFILE, **job}

    def _access(self, identity, run_id, key):
        self.metadata(identity)
        rows = self.store.query('SELECT * FROM workflow_runs WHERE id=? AND actor=?', (run_id, 'public-flow:' + identity))
        if len(rows) != 1: raise ValueError('The run capability is unavailable.')
        row = dict(rows[0]); records = self.store.query('SELECT payload,signature FROM workflow_run_authority WHERE run_id=?', (run_id,))
        if len(records) != 1: raise ValueError('The retained run authority is unavailable.')
        authority = json.loads(records[0]['payload']); scope = authority['principal']['payload'].get('public_connection')
        self.replay_scope(row, scope, current=False)
        if not isinstance(key, str) or not hmac.compare_digest(key, self.run_key(row, scope)): raise ValueError('The release-scoped run capability is unavailable.')
        if time.time() > row['created'] + 3600: raise ValueError('The run capability expired.')
        return row

    def read_run(self, identity, run_id, key):
        self._access(identity, run_id, key)
        return self.project_result(identity, run_id, self.runtime.get(run_id))

    def project_result(self, identity, run_id, result):
        from .workflows import public_outcome
        from .concierge.recommendation_security import usable_endpoint
        from .concierge.connections import project
        from .concierge.report_projection import private_data
        from .concierge.security import public_metadata
        from urllib.parse import urlsplit
        publication = self.metadata(identity)
        connections = publication['private_connections']
        def display(value, *, citation=False):
            safe = private_data(public_metadata(public_outcome(value)))
            for connection in connections:
                projected = project(safe, connection['gateway'], connection['raw_urls'])
                if citation and projected != safe: return None
                safe = projected.replace(connection['gateway'], '[Connection address omitted]') if isinstance(projected, str) and projected != safe else projected
            return safe
        status = result.get('status') if result.get('status') in ('queued', 'running', 'succeeded', 'failed', 'cancelled') else 'failed'
        outcome = result.get('execution_outcome') if result.get('execution_outcome') in ('succeeded', 'failed', 'cancelled', 'unknown', None) else None
        rows = []
        known = {flow.IDS[1]: ('News search', ('title', 'url', 'source', 'published_at', 'retrieved_at', 'summary')),
                 flow.IDS[2]: ('Documentation search', ('title', 'url', 'excerpt', 'version', 'retrieved_at'))}
        for node in result.get('node_results', [])[:3]:
            if not isinstance(node, dict) or node.get('node_id') not in known: continue
            label, fields = known[node['node_id']]
            state = node.get('status') if node.get('status') in ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'blocked', 'skipped') else 'failed'
            projected = {'name': label, 'type': 'agent', 'status': state}
            data = node.get('data'); content = data.get('structuredContent', data) if isinstance(data, dict) else None
            if state == 'succeeded' and isinstance(content, dict) and isinstance(content.get('items'), list):
                items = []
                for item in content['items'][:5]:
                    if not isinstance(item, dict): continue
                    safe = {field: display(item[field], citation=field == 'url') for field in fields if field in item and (isinstance(item[field], str) or item[field] is None)}
                    url = safe.get('url')
                    if (not isinstance(url, str) or urlsplit(url).scheme != 'https' or not usable_endpoint(url)
                            or public_outcome(url) != url): safe.pop('url', None)
                    items.append(safe)
                projected['data'] = {'structuredContent': {'items': items, 'partial': content.get('partial') is True}}
            rows.append(projected)
        response = {'ok': status == 'succeeded', 'run_id': run_id, 'status': status, 'execution_outcome': outcome, 'node_results': rows}
        if status in ('failed', 'cancelled'): response['error'] = 'The run did not complete. Review its recorded status before retrying.'
        return response

    def cancel_run(self, identity, run_id, key):
        self._access(identity, run_id, key); self.runtime.cancel(run_id)
        return {'ok': True, 'cancel_requested': True}

    @staticmethod
    def _test_scope(workflow):
        source = workflow['nodes'][1]['data']['composition']['payload']
        return {'profile': PROFILE, 'mode': 'test', 'owner': source['owner'], 'nonce': source['nonce'],
                'definition_hash': digest(flow.graph_value(workflow)), 'reviewed_at': source['reviewed_at'],
                'expires': source['reviewed_at'] + TTL,
                'sharing_notice': TEST_SHARE_NOTICE, 'run_notice': TEST_RUN_NOTICE, 'sharing_authorized': True, 'run_authorized': True}

    @staticmethod
    def _public_scope(body):
        return {'profile': PROFILE, 'mode': 'public', 'proposal': copy.deepcopy(body['proposal']), 'signature': body['signature'],
                'sharing_authorized': True, 'run_authorized': True}

    def admit(self, workflow, claims, context, *, source, profile, fallback):
        if not flow.is_flow(workflow):
            if context is not None: raise ValueError('Public-connection purpose requires its canonical definition.')
            return None
        if not isinstance(context, dict) or set(context) != DECLARATIONS | {'mode'} or profile != 'standard' or fallback: raise ValueError('This connection requires a fresh standard manual purpose.')
        body = {key: context[key] for key in DECLARATIONS}
        flow.definition(self.runtime, workflow)
        if context['mode'] == 'test':
            if source != 'admin' or claims['kind'] != 'admin' or claims.get('role') != 'superadmin': raise ValueError('A highest-administrator canonical test is required.')
            self._declared(body, TEST_SHARE_NOTICE, TEST_RUN_NOTICE); p = self._candidate(body, self._owner(claims['subject']))
            expected = {**p['workflow'], 'id': workflow['id']}
            if flow.graph_value(expected) != flow.graph_value(workflow): raise ValueError('The canonical test definition changed.')
            return self._test_scope(workflow)
        if context['mode'] != 'public' or source != 'public' or claims['kind'] != 'public': raise ValueError('Use a current published manual-run purpose.')
        p, current = self._public_ticket(claims['subject'], body)
        if flow.graph_value(current) != flow.graph_value(workflow): raise ValueError('The public definition changed.')
        return self._public_scope(body)

    def run_scope(self, row, workflow):
        if not flow.is_flow(workflow): return
        authority = self.runtime.authority.run(row['id'], workflow['id'], row['digest'], row['source'])
        p = authority['principal']['payload']; scope = p.get('public_connection')
        if p.get('connection_automation') is not None:
            self.runtime.automation.run_scope(row,workflow,authority)
            return
        if p.get('connection_deployment') is not None:
            self.runtime.connection_deployments.run_scope(row,workflow,authority)
            return
        if (digest(workflow) != row['digest'] or authority.get('grant_id') is not None or not isinstance(scope, dict)
                or self.runtime.budgets.get(row)['profile'] != 'standard'): raise ValueError('The canonical run purpose changed.')
        flow.definition(self.runtime, workflow)
        if row['source'] == 'admin':
            expected = self._test_scope(workflow); self._epoch(expected['reviewed_at'])
            if (scope != expected or p['kind'] != 'admin' or p.get('role') != 'superadmin' or p['subject'] != expected['owner']
                    or row['actor'] != 'publication-test:' + expected['owner'] or row['idempotency_key'] != expected['nonce']): raise ValueError('The canonical test scope changed.')
            return
        if row['source'] != 'public' or scope.get('mode') != 'public' or p['kind'] != 'public': raise ValueError('The canonical public run scope changed.')
        body = {'proposal': scope['proposal'], 'signature': scope['signature'], 'sharing_authority': True, 'sharing_notice': SHARE_NOTICE, 'run_authority': True, 'run_notice': RUN_NOTICE}
        ticket, current = self._public_ticket(p['subject'], body)
        if scope != self._public_scope(body) or flow.graph_value(current) != flow.graph_value(workflow) or row['actor'] != 'public-flow:' + ticket['release_id'] or row['idempotency_key'] != ticket['nonce']: raise ValueError('The accepted public run purpose changed.')

    def dispatch_guard(self, row, workflow, node=None, arguments=None, provenance=None):
        try:
            self.run_scope(row, workflow)
            if flow.is_flow(workflow) and node is not None and node['id'] == flow.IDS[2]:
                expected, observed = flow.resolved(self.runtime, row, workflow)
                if arguments is not None and (expected != arguments or provenance != observed):
                    raise ValueError('The prepared source projection or derived input changed.')
                source_cp, _ = flow.source_proof(self.runtime, row, workflow)
                starts = self.store.query('SELECT started FROM workflow_node_runs WHERE run_id=? AND node_id=?', (row['id'], node['id']))
                if (len(starts) != 1 or flow.timestamp(starts[0]['started']) < source_cp['record']['started'] + source_cp['record']['latency_ms'] / 1000):
                    raise ValueError('The documentation call predates the source observation.')
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
            raise ExecutionDenied('The current public-connection authorization is unavailable.', error_code='POLICY_DENIED') from None

    def replay_scope(self, row, scope, *, current=True):
        if (not isinstance(scope, dict) or scope.get('profile') != PROFILE
                or scope.get('sharing_authorized') is not True or scope.get('run_authorized') is not True):
            raise ValueError('An exact retained connection purpose is required.')
        records = self.store.query('SELECT payload,signature FROM workflow_run_authority WHERE run_id=?', (row['id'],))
        if len(records) != 1 or len(records[0]['payload']) > 16384: raise ValueError('The retained run purpose is unavailable.')
        authority = json.loads(records[0]['payload']); envelope = authority['principal']; principal = envelope['payload']
        if (not hmac.compare_digest(records[0]['signature'], self.runtime.authority.signature(authority))
                or not hmac.compare_digest(envelope['signature'], self.runtime.authority.signature(principal))
                or any(authority.get(key) != row[key] for key in ('workflow_id', 'digest', 'source')) or authority.get('run_id') != row['id']
                or authority.get('grant_id') is not None or principal.get('public_connection') != scope
                or principal.get('workflow_id') != row['workflow_id'] or principal.get('audience') != 'workflow-runtime-v1'
                or flow.timestamp(principal.get('expires')) <= flow.timestamp(row['created'])): raise ValueError('The retained run purpose changed.')
        if scope.get('mode') == 'public':
            ticket = scope['proposal']
            fields = {'audience', 'profile', 'release_id', 'revision', 'definition_hash', 'rule_hash', 'nonce', 'created', 'expires', 'reviewed_at', 'sharing_notice', 'run_notice'}
            if (set(scope) != {'profile', 'mode', 'proposal', 'signature', 'sharing_authorized', 'run_authorized'}
                    or not isinstance(ticket, dict) or set(ticket) != fields or ticket['audience'] != TICKET or ticket['profile'] != PROFILE
                    or not isinstance(scope['signature'], str) or not hmac.compare_digest(scope['signature'], self.runtime.authority.signature(ticket))
                    or ticket['sharing_notice'] != SHARE_NOTICE or ticket['run_notice'] != RUN_NOTICE
                    or not flow.timestamp(ticket['created']) <= row['created'] < flow.timestamp(ticket['expires'])
                    or ticket['expires'] > ticket['created'] + 300 or ticket['reviewed_at'] != ticket['created']
                    or principal['expires'] > ticket['expires']): raise ValueError('The retained public run ticket is invalid.')
            if (principal['kind'] != 'public' or principal['subject'] != ticket['release_id'] or row['source'] != 'public'
                    or row['actor'] != 'public-flow:' + ticket['release_id'] or row['idempotency_key'] != ticket['nonce']): raise ValueError('The public nonce scope changed.')
            if not current:
                metadata = self.metadata(ticket['release_id'])
                if (type(ticket['revision']) is not int or ticket['revision'] != metadata['revision']
                        or ticket['definition_hash'] != metadata['definition_hash'] or ticket['expires'] > metadata['expires']
                        or ticket['rule_hash'] != digest(metadata['workflow']['nodes'][2]['data']['composition']['payload']['connection'])):
                    raise ValueError('The retained publication scope changed.')
        elif scope.get('mode') == 'test':
            if (scope != self._test_scope(json.loads(row['snapshot'])) or principal['kind'] != 'admin' or principal['subject'] != scope['owner']
                    or row['actor'] != 'publication-test:' + scope['owner'] or row['idempotency_key'] != scope['nonce'] or principal['expires'] > scope['expires']): raise ValueError('The canonical test nonce changed.')
        else: raise ValueError('An exact canonical purpose is required.')

    def run_key(self, row, scope):
        ticket = scope['proposal']; raw = hmac.new(self.runtime.key, ('workflow-public-flow-key-v1\0' + ticket['release_id'] + '\0' + ticket['nonce'] + '\0' + row['id']).encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')
