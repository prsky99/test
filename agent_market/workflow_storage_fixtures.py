"""Synthetic current-schema storage scenarios, never an operating database.

The fixed seed selects repeatable synthetic content and scenario distribution.
Fresh cryptographic IDs still come from the production signing/admission code.
All MCP packets terminate in this module's in-memory transport. These records
are fixture effects, not provider-quality evidence or an operating rehearsal.
"""
import asyncio
import copy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import httpx

from .capability_contracts import CONTRACTS, run_test
from .capability_registry import Registry, canonical
from .collector import usage
from .concierge.proxy import McpProxy
from .execution_authority import Authority, SCHEMA as AUTHORITY_SCHEMA
from .gateway.admin_auth import ADMIN_SCHEMA, create_admin_user, create_session
from .gateway.store import Store
from .observability import journal_for
from .workflow_budgets import Budgets
from .workflow_composer import Composer, SAVE
from .workflow_connection_automation import ConnectionAutomation
from .workflow_connection_deployment import ConnectionDeployments
from .workflow_deployment_consent import DeploymentConsent
from .workflow_fallback import FallbackRouter
from .workflow_maintenance import Maintenance
from .workflow_operations import Operations
from .workflow_persistence import DurableRuns
from .workflow_publication import Publication
from .workflows import WorkflowRuntime, SCHEMA as WORKFLOW_SCHEMA

PROFILE = 'synthetic-workflow-storage-fixture-v1'
ORIGIN = 'https://storage-fixture.example'
MAX_COMPLETED = 40
GRANT_QUERIES = {
    'workflow_deployment_grants': {
        'inactive': 'SELECT id,revision,active,revoked FROM workflow_deployment_grants WHERE active=0 ORDER BY id',
        'active': 'SELECT COUNT(*) FROM workflow_deployment_grants WHERE active=1',
        'revisions': 'SELECT id,revision FROM workflow_deployment_grants ORDER BY id'},
    'workflow_publication_grants': {
        'inactive': 'SELECT id,revision,active,revoked FROM workflow_publication_grants WHERE active=0 ORDER BY id',
        'active': 'SELECT COUNT(*) FROM workflow_publication_grants WHERE active=1',
        'revisions': 'SELECT id,revision FROM workflow_publication_grants ORDER BY id'},
    'workflow_connection_deployments': {
        'inactive': 'SELECT id,revision,active,revoked FROM workflow_connection_deployments WHERE active=0 ORDER BY id',
        'active': 'SELECT COUNT(*) FROM workflow_connection_deployments WHERE active=1',
        'revisions': 'SELECT id,revision FROM workflow_connection_deployments ORDER BY id'},
    'workflow_connection_automation': {
        'inactive': 'SELECT id,revision,active,revoked FROM workflow_connection_automation WHERE active=0 ORDER BY id',
        'active': 'SELECT COUNT(*) FROM workflow_connection_automation WHERE active=1',
        'revisions': 'SELECT id,revision FROM workflow_connection_automation ORDER BY id'}}


def utc(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace('+00:00', 'Z')


def tool(contract):
    return {'name': {'news.search.v1': 'search_news', 'docs.search.v1': 'search_docs',
                     'products.compare.v2': 'compare_products'}[contract],
            'description': 'Search synthetic informational fixture sources',
            'inputSchema': copy.deepcopy(CONTRACTS[contract]['input_schema']),
            'outputSchema': copy.deepcopy(CONTRACTS[contract]['output_schema']),
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}}


class SyntheticTransport(httpx.BaseTransport):
    """No sockets, DNS, external handlers, callback URLs or configured models."""
    def __init__(self, seed):
        self.title = 'Synthetic documentation topic ' + str(int(hashlib.sha256(str(seed).encode()).hexdigest(), 16) % 100000)
        self.calls = []
        self.mode = 'success'
        self.specs = {'news.storage-fixture.example': ('news.search.v1', tool('news.search.v1')),
                      'docs.storage-fixture.example': ('docs.search.v1', tool('docs.search.v1')),
                      'products.storage-fixture.example': ('products.compare.v2', tool('products.compare.v2'))}

    def output(self, contract):
        stamp = utc(time.time())
        if contract == 'products.compare.v2':
            return {'structuredContent': {'items': [{'identity': {'brand': 'Synthetic', 'model': 'Storage sample',
                'variant': 'Fixture', 'identifier': {'scheme': 'provider_label', 'value': 'synthetic-item'}},
                'name': 'Synthetic storage item', 'url': 'https://evidence.example/synthetic-item', 'retrieved_at': stamp,
                'measurements': [{'criterion_id': 'mass', 'dimension': 'mass', 'status': 'reported',
                    'quantity': {'value': '1', 'unit': 'kg'}, 'source_url': 'https://evidence.example/mass', 'observed_at': stamp}],
                'price': {'status': 'missing', 'amount': None, 'currency': None, 'basis': None,
                          'source_url': None, 'observed_at': None}}], 'partial': True}}
        item = {'title': self.title, 'url': 'https://evidence.example/synthetic-source', 'retrieved_at': stamp}
        if contract == 'news.search.v1':
            item.update(source='Synthetic source', summary='Synthetic storage rehearsal content only.', published_at=stamp)
        else: item.update(excerpt='Synthetic documentation content only.', version='fixture-v1')
        return {'content': [], 'structuredContent': {'items': [item], 'partial': False}}

    def handle_request(self, request):
        if request.url.host not in self.specs or request.url.path != '/mcp':
            raise ValueError('Only the synthetic fixture transport is available.')
        if request.method == 'DELETE': return httpx.Response(204)
        if request.method != 'POST': return httpx.Response(405)
        body = json.loads(request.content); method = body.get('method'); identity = body.get('id')
        contract, spec = self.specs[request.url.host]
        if method == 'notifications/initialized': return httpx.Response(202)
        if method in ('server/discover', 'initialize'):
            result = {'protocolVersion': '2025-06-18', 'serverInfo': {'name': 'synthetic-storage-fixture', 'version': '1'}}
        elif method == 'tools/list': result = {'tools': [spec]}
        elif method == 'tools/call':
            self.calls.append({'contract': contract, 'arguments': copy.deepcopy(body['params']['arguments'])})
            if self.mode == 'unknown': raise httpx.ReadTimeout('Synthetic uncertain response.')
            result = self.output(contract)
        else: return httpx.Response(404)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': identity, 'result': result})


def runtime_context(store, key, proxy=None):
    """Compose trusted helpers without Runtime.__init__, env keys or recovery.

    This is fixture wiring, not an alternate operating-runtime constructor. In
    particular no lease recovery, queue launch, heartbeat or scheduler is run.
    """
    runtime = WorkflowRuntime.__new__(WorkflowRuntime)
    runtime.store, runtime.proxy, runtime.courier = store, proxy, None
    runtime.key = hmac.new(key, b'workflow-results-v1', hashlib.sha256).digest()
    runtime.journal = journal_for(store)
    runtime.lock, runtime.destination_lock = threading.RLock(), threading.RLock()
    runtime.futures, runtime.worker_seen = {}, 0
    runtime.instance = hashlib.sha256(key + b'fixture-owner').hexdigest()[:32]
    runtime.authority = Authority(store, runtime.key)
    with store._lock:
        store._db.executescript(WORKFLOW_SCHEMA + AUTHORITY_SCHEMA)
        # These two compatibility columns are normally installed by the
        # operating initializer; this fresh fixture never invokes that path.
        store._db.execute('ALTER TABLE workflow_runs ADD COLUMN lease_until REAL NOT NULL DEFAULT 0')
        store._db.execute('ALTER TABLE workflow_runs ADD COLUMN owner TEXT')
    store._workflow_runtime = runtime
    runtime.persistence = DurableRuns(store)
    from .workflow_io_profiles import IOProfiles
    from .workflow_products import Products
    runtime.io_profiles = IOProfiles(runtime)
    runtime.fallback = FallbackRouter(runtime)
    runtime.products = Products(runtime)
    runtime.budgets = Budgets(runtime)
    runtime.operations = Operations(runtime)
    runtime.maintenance = Maintenance(runtime)
    runtime.composer = Composer(runtime)
    runtime.deployment_consent = DeploymentConsent(runtime)
    runtime.publication = Publication(runtime)
    runtime.connection_deployments = ConnectionDeployments(runtime)
    runtime.automation = ConnectionAutomation(runtime)
    runtime.launch = lambda _run_id: None
    return runtime


class SyntheticFixture:
    def __init__(self, directory, seed, completed):
        self.directory, self.seed, self.completed = directory, seed, completed
        self.path = directory / 'catalog.sqlite3'
        # Explicitly synthetic, reproducible fixture key. Never load .env, the
        # user's update key or a configured operating key from the environment.
        self.key = hashlib.sha256(('storage-fixture-v1:' + str(seed)).encode()).digest()
        self.store = self.client = None
        self.refs, self.expected = {}, {}
        self.transport = SyntheticTransport(seed)
        self.retention_now = time.time() + 91 * 86400

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def close(self):
        if self.client is not None: self.client.close(); self.client = None
        if self.store is not None: self.store._db.close(); self.store = None

    def execute(self, job):
        """One synchronous admitted fixture task, never launch a worker."""
        row = self.runtime.persistence.claim(job['run_id'], self.runtime.instance, 25)
        if row is None: raise ValueError('The synthetic fixture task was not admitted.')
        self.runtime._execute_bounded(job['run_id'], row)
        result = self.runtime.get(job['run_id'])
        if result['status'] not in ('succeeded', 'failed', 'cancelled'):
            raise ValueError('The synthetic fixture task did not reach a terminal outcome.')
        return result

    def prepare_idle(self):
        """Deliberately settle only the synthetic queued scenario, with no call."""
        identity = self.refs['active_run']
        with self.store.tx() as db:
            db.execute("UPDATE workflow_runs SET status='cancelled',execution_outcome='cancelled',finished=?,cancel_requested=1 WHERE id=? AND status='queued'",
                       (time.time(), identity))
            db.execute("UPDATE workflow_node_runs SET status='cancelled' WHERE run_id=? AND status='queued'", (identity,))
        return {'synthetic_active_settled': True, 'external_calls': 0}

    def safe_summary(self):
        store = self.store
        unknown = store.query('SELECT execution_outcome FROM workflow_runs WHERE id=?', (self.refs['unknown_run'],))
        tampered = store.query("SELECT payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'", (self.refs['tampered_run'],))
        valid = (len(unknown) == len(tampered) == 1 and unknown[0][0] == 'unknown'
                 and tampered[0]['signature'] != self.runtime.authority.signature(json.loads(tampered[0]['payload']))
                 and self.runtime.deployment_consent.read_access(self.refs['sdk12']['app_id'], ORIGIN)['app']['active'] == 1
                 and self.runtime.connection_deployments.authorize(self.refs['sdk13']['app_id'], self.refs['sdk13']['publish_key'], ORIGIN, read=True)['id'] == self.refs['sdk13']['app_id'])
        return {'profile': PROFILE, 'synthetic': True, 'valid': valid, 'seed': self.seed, 'completed_requested': self.completed,
                'fixture_effects': {'mcp_calls': len(self.transport.calls), 'provider_network_calls': 0,
                                    'model_calls': 0, 'worker_starts': 0, 'scheduler_starts': 0},
                'counts': {'runs': store.query('SELECT COUNT(*) FROM workflow_runs')[0][0],
                           'checkpoints': store.query('SELECT COUNT(*) FROM workflow_checkpoints')[0][0],
                           'unknown_runs': store.query("SELECT COUNT(*) FROM workflow_runs WHERE execution_outcome='unknown'")[0][0],
                           'pending_deliveries': store.query("SELECT COUNT(*) FROM workflow_result_outbox WHERE status='pending'")[0][0],
                           'product_approvals': store.query("SELECT COUNT(*) FROM capability_approvals WHERE contract_id='products.compare.v2'")[0][0],
                           'sdk12_grants': store.query('SELECT COUNT(*) FROM workflow_deployment_grants')[0][0],
                           'publication_grants': store.query('SELECT COUNT(*) FROM workflow_publication_grants')[0][0],
                           'sdk13_grants': store.query('SELECT COUNT(*) FROM workflow_connection_deployments')[0][0],
                           'automation_grants': store.query('SELECT COUNT(*) FROM workflow_connection_automation')[0][0]},
                'claims': {'provider_quality_verified': False, 'operating_acceptance': False,
                           'external_delivery': False, 'trusted_timestamp': False}}

    def exercise_durable(self):
        """Reuse the real claim/fence/recovery boundary without an agent call."""
        from .workflow_persistence import FenceLost
        rt = self.runtime; workflow = self.refs['literal_workflow']; calls = len(self.transport.calls)
        job = rt.submit(workflow, actor='storage-fixture:durable', idempotency='durable-unknown-once',
                        principal=rt.principal('admin', self.refs['owner'], workflow['id'], role='superadmin'))
        row = rt.persistence.claim(job['run_id'], 'synthetic-owner-a', 25)
        single = row is not None and rt.persistence.claim(job['run_id'], 'synthetic-owner-b', 25) is None
        stale_denied = False
        try:
            with self.store.tx() as db: rt.persistence.owned(db, job['run_id'], 'synthetic-owner-a', row['fence'] - 1)
        except FenceLost: stale_denied = True
        rt.persistence.prepare(job['run_id'], 'synthetic-owner-a', row['fence'], 'search-1', 'a' * 64)
        rt.persistence.dispatch(job['run_id'], 'synthetic-owner-a', row['fence'], 'search-1')
        with self.store.tx() as db: db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?', (job['run_id'],))
        recovered = rt.persistence.recover()
        final = self.store.query('SELECT status,execution_outcome FROM workflow_runs WHERE id=?', (job['run_id'],))[0]
        attempt = self.store.query('SELECT status FROM workflow_execution_attempts WHERE run_id=?', (job['run_id'],))[0][0]
        no_reclaim = rt.persistence.claim(job['run_id'], 'synthetic-owner-c', 25) is None
        self.refs['durable_unknown_run'] = job['run_id']
        return {'scope': 'claim_fence_recovery_only', 'recovered_runs': recovered, 'fixture_agent_calls': 0,
                'invariants': {'one_claim_owner': single, 'stale_fence_denied': stale_denied,
                               'dispatched_recovered_unknown': final['status'] == 'failed' and final['execution_outcome'] == attempt == 'unknown',
                               'unknown_not_reclaimed': no_reclaim, 'no_provider_or_model_call': len(self.transport.calls) == calls}}

    def capture(self):
        """Private baseline; the runner must serialize only verification booleans."""
        def rows(sql, params=()): return [tuple(row) for row in self.store.query(sql, params)]
        return {'replay': rows('SELECT id,actor,idempotency_key FROM workflow_runs ORDER BY id'),
                'attempts': rows('SELECT run_id,node_id,input_hash,status FROM workflow_execution_attempts ORDER BY run_id,node_id'),
                'unknown': rows("SELECT * FROM workflow_runs WHERE execution_outcome='unknown' ORDER BY id"),
                'tampered': rows('SELECT * FROM workflow_checkpoints WHERE run_id=? ORDER BY node_id', (self.refs['tampered_run'],)),
                'held': rows('SELECT * FROM workflow_checkpoints WHERE run_id=? ORDER BY node_id', (self.refs['held_run'],)),
                'outbox': rows('SELECT * FROM workflow_result_outbox ORDER BY id'),
                'manual': rows('SELECT * FROM workflow_manual_deliveries ORDER BY id'),
                'events': rows('SELECT * FROM workflow_event_receipts ORDER BY workflow_id,event_id'),
                'metadata_target': {'id': self.refs['literal_proof'],
                    'events': len(rows('SELECT 1 FROM workflow_run_events WHERE run_id=?', (self.refs['literal_proof'],))),
                    'authority': len(rows('SELECT 1 FROM workflow_run_authority WHERE run_id=?', (self.refs['literal_proof'],)))},
                'snapshots': {row['id']: row['digest'] for row in self.store.query('SELECT id,digest FROM workflow_runs')},
                'calls': len(self.transport.calls),
                'tombstones': {table: rows(queries['inactive']) for table, queries in GRANT_QUERIES.items()},
                'retention_now': self.retention_now}

    def verify_compaction(self, baseline):
        from .workflow_comparison import Comparison
        after = self.capture(); archives = self.store.query('SELECT * FROM workflow_run_archives')
        signed = bool(archives)
        for archive in archives:
            payload = json.loads(archive['payload'])
            signed = signed and (payload['audience'] == 'workflow-retention-v1' and payload['run_id'] == archive['run_id']
                and payload['snapshot_sha256'] == baseline['snapshots'][archive['run_id']]
                and hmac.compare_digest(archive['signature'], self.runtime.authority.signature(payload)))
        def denied(action):
            try: action()
            except ValueError: return True
            return False
        literal = self.refs['literal_workflow']
        with Comparison(self.runtime).reader() as store:
            no_comparison = denied(lambda: Comparison(self.runtime).load(store, self.refs['literal_proof'], 'news.search.v1'))
        return {'replay_tombstones_retained': after['replay'] == baseline['replay'],
                'attempt_tombstones_retained': after['attempts'] == baseline['attempts'],
                'unknown_outcomes_unchanged': after['unknown'] == baseline['unknown'],
                'invalid_checkpoint_held': after['tampered'] == baseline['tampered'],
                'pending_delivery_bodies_held': after['held'] == baseline['held'] and after['outbox'] == baseline['outbox'] and after['manual'] == baseline['manual'],
                'event_replay_receipts_retained': after['events'] == baseline['events'],
                'withdrawal_tombstones_retained': all(baseline['tombstones'].values()) and after['tombstones'] == baseline['tombstones'],
                'archive_signatures_valid': bool(signed),
                'archived_checkpoints_removed': all(not self.store.query('SELECT 1 FROM workflow_checkpoints WHERE run_id=?', (row['run_id'],)) for row in archives),
                'archived_literal_cannot_certify_publication': denied(lambda: self.runtime.composer.validate_publish(literal, self.refs['literal_proof'])),
                'archived_source_cannot_reauthorize_public_connection': denied(lambda: self.runtime.publication.proof(self.refs['publication_test'], str(self.refs['owner']))),
                'archived_source_cannot_prepare_sdk13_run': denied(lambda: self.runtime.connection_deployments.prepare_run(self.refs['sdk13']['app_id'], ORIGIN)),
                'archived_source_cannot_supply_comparison': no_comparison,
                'expired_metadata_removed_without_replay_reset': baseline['metadata_target']['events'] > 0
                    and baseline['metadata_target']['authority'] == 1
                    and not self.store.query('SELECT 1 FROM workflow_run_events WHERE run_id=?', (baseline['metadata_target']['id'],))
                    and not self.store.query('SELECT 1 FROM workflow_run_authority WHERE run_id=?', (baseline['metadata_target']['id'],)),
                'no_external_or_fixture_agent_calls': after['calls'] == baseline['calls']}

    def prepare_restore(self):
        """Arm new queued/prepared synthetic tasks after idle maintenance."""
        rt = self.runtime; workflow = self.refs['literal_workflow']; pending = []
        # Status capability checks deliberately survive detail retention. Prove
        # that the precise old capabilities work here, before restore revokes
        # them, rather than attributing a pre-existing refusal to quarantine.
        self.expected['restore_access'] = {
            'sdk12': rt.deployment_consent.read_access(self.refs['sdk12']['app_id'], ORIGIN)['app']['active'] == 1,
            'sdk13': rt.connection_deployments.authorize(self.refs['sdk13']['app_id'], self.refs['sdk13']['publish_key'], ORIGIN, read=True)['id'] == self.refs['sdk13']['app_id']
                and rt.connection_deployments.read_run(self.refs['sdk13']['app_id'], self.refs['sdk13_run']['run_id'], self.refs['sdk13_run']['run_key'], ORIGIN)['status'] == 'succeeded',
            'public': rt.publication.read_run(self.refs['publication']['id'], self.refs['public_run']['run_id'], self.refs['public_run']['run_key'])['status'] == 'succeeded'}
        def denied(action):
            try: action()
            except ValueError: return True
            return False
        # These old invocation tickets already lack reusable detailed proof
        # after retention. Preserve that refusal; do not mislabel it as a new
        # revocation caused by restore. The three read capabilities above are
        # the separate, valid-before-DR authorization preconditions.
        self.expected['retained_ticket_refusals'] = {
            'public': denied(lambda: rt.publication.execute_run(self.refs['publication']['id'], self.refs['public_body'])),
            'sdk13': denied(lambda: rt.connection_deployments.execute_run(self.refs['sdk13']['app_id'], self.refs['sdk13_body'], ORIGIN))}
        for kind in ('queued', 'prepared'):
            job = rt.submit(workflow, actor='storage-fixture:restore', idempotency='restore-' + kind,
                principal=rt.principal('admin', self.refs['owner'], workflow['id'], role='superadmin'))
            if kind == 'prepared':
                row = rt.persistence.claim(job['run_id'], 'synthetic-restore-owner', 25)
                rt.persistence.prepare(job['run_id'], 'synthetic-restore-owner', row['fence'], 'search-1', 'b' * 64)
            pending.append(job['run_id'])
        self.refs['restore_unfinished'] = pending
        return {'synthetic_queued': 1, 'synthetic_prepared': 1, 'fixture_agent_calls': 0}

    def verify_restore(self, restored_path, inventory):
        """Use a read-only handle and original synthetic capabilities after DR."""
        from .workflow_comparison import ReadStore
        db = sqlite3.connect(Path(restored_path).resolve().as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row; db.execute('PRAGMA query_only=ON')
        try:
            store = ReadStore(db); runtime = SimpleNamespace(store=store, key=self.runtime.key)
            runtime.authority = Authority(store, runtime.key)
            for cls, name in ((Publication, 'publication'), (DeploymentConsent, 'deployment_consent'),
                              (ConnectionDeployments, 'connection_deployments'), (ConnectionAutomation, 'automation')):
                instance = cls.__new__(cls); instance.runtime, instance.store = runtime, store
                if name in ('connection_deployments', 'automation'): instance.publication = runtime.publication
                setattr(runtime, name, instance)
            def denied(action):
                try: action()
                except ValueError: return True
                return False
            active = {'workflow_apps': db.execute('SELECT COUNT(*) FROM workflow_apps WHERE active=1').fetchone()[0],
                      **{table: db.execute(queries['active']).fetchone()[0] for table, queries in GRANT_QUERIES.items()}}
            controls = tuple(db.execute('SELECT invoke_enabled,workflow_enabled,delivery_enabled FROM execution_controls').fetchone())
            rendered = json.dumps(inventory)
            secrets = [self.refs['sdk12']['publish_key'], self.refs['sdk13']['publish_key'], self.refs['session'],
                       self.refs['public_run']['run_key'], self.refs['sdk13_run']['run_key'], 'synthetic-sealed-value']
            old_replay = [tuple(row) for row in self.store.query('SELECT id,actor,idempotency_key FROM workflow_runs ORDER BY id')]
            restored_replay = [tuple(row) for row in db.execute('SELECT id,actor,idempotency_key FROM workflow_runs ORDER BY id')]
            archives = db.execute('SELECT payload,signature FROM workflow_run_archives').fetchall()
            archive_valid = bool(archives) and all(hmac.compare_digest(row['signature'], runtime.authority.signature(json.loads(row['payload']))) for row in archives)
            new_event = {**self.refs['event_body'], 'event_id': hashlib.sha256(('restored-new-event:' + str(self.seed)).encode()).hexdigest()[:32]}
            revisions = all([tuple(row) for row in db.execute(queries['revisions'])] ==
                            [(row['id'], row['revision'] + 1) for row in self.store.query(queries['revisions'])]
                            for queries in GRANT_QUERIES.values())
            pending = self.refs.get('restore_unfinished', [])
            quarantined = len(pending) == 2 and all((lambda row: row is not None and row['status'] == 'failed' and row['execution_outcome'] == 'unknown'
                and row['owner'] is None and row['lease_until'] == 0 and row['fence'] > self.store.query('SELECT fence FROM workflow_runs WHERE id=?', (identity,))[0][0])
                (db.execute('SELECT * FROM workflow_runs WHERE id=?', (identity,)).fetchone()) for identity in pending)
            return {'all_execution_controls_paused': controls == (0, 0, 0),
                    'all_purpose_grants_inactive': all(count == 0 for count in active.values()),
                    'all_grant_revisions_advanced': revisions,
                    'sdk12_old_capability_rejected': self.expected.get('restore_access', {}).get('sdk12') is True and denied(lambda: runtime.deployment_consent.read_access(self.refs['sdk12']['app_id'], ORIGIN)),
                    'sdk13_old_key_rejected': self.expected.get('restore_access', {}).get('sdk13') is True and denied(lambda: runtime.connection_deployments.authorize(self.refs['sdk13']['app_id'], self.refs['sdk13']['publish_key'], ORIGIN, read=True)),
                    'public_old_run_key_rejected': self.expected.get('restore_access', {}).get('public') is True and denied(lambda: runtime.publication.read_run(self.refs['publication']['id'], self.refs['public_run']['run_id'], self.refs['public_run']['run_key'])),
                    'retained_public_ticket_not_replayed': self.expected.get('retained_ticket_refusals', {}).get('public') is True and denied(lambda: runtime.publication.execute_run(self.refs['publication']['id'], self.refs['public_body'])),
                    'retained_sdk13_ticket_not_replayed': self.expected.get('retained_ticket_refusals', {}).get('sdk13') is True and denied(lambda: runtime.connection_deployments.execute_run(self.refs['sdk13']['app_id'], self.refs['sdk13_body'], ORIGIN)),
                    'automation_new_event_rejected': denied(lambda: runtime.automation.trigger(self.refs['publication']['id'], self.refs['automation'][0]['id'], new_event, self.refs['owner'])),
                    'queued_and_prepared_quarantined_unknown': quarantined,
                    'automation_grants_unscheduled': not db.execute('SELECT 1 FROM workflow_connection_automation WHERE active=1 OR next_run IS NOT NULL').fetchone(),
                    'pending_deliveries_quarantined': db.execute('SELECT status FROM workflow_result_outbox WHERE id=?', (self.refs['outbox'],)).fetchone()[0] == 'unknown' and db.execute('SELECT status FROM workflow_manual_deliveries WHERE id=?', (self.refs['manual_delivery'],)).fetchone()[0] == 'unknown',
                    'verified_destination_revoked': not db.execute("SELECT 1 FROM workflow_destinations WHERE state IN ('verified','pending') OR sealed IS NOT NULL").fetchone(),
                    'old_admin_sessions_removed': db.execute('SELECT COUNT(*) FROM admin_sessions').fetchone()[0] == 0,
                    'replay_tombstones_retained': old_replay == restored_replay,
                    'signed_archives_retained': archive_valid,
                    'private_inventory_bounded_without_secrets': inventory.get('automatic_reactivation') is False and all(secret not in rendered for secret in secrets)
                        and all(len(item['records']) <= 1000 for item in inventory['items'].values()),
                    'verification_read_only': db.total_changes == 0}
        finally: db.close()

    def populate(self):
        # Store's ordinary bootstrap may use configured administrator secrets.
        # Seed a synthetic sadmin in a fresh private file before that initializer
        # sees the schema, so it never reads an operating bootstrap credential.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(ADMIN_SCHEMA)
            with db:
                owner = create_admin_user(db, 'sadmin', 'Synthetic-storage-fixture-password-42', 'Synthetic reviewer', 'superadmin')['id']
        self.store = Store(str(self.path))
        key_path = Path(str(self.path) + '.updates-key')
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as target: target.write(self.key)
        self.client = httpx.Client(transport=self.transport)
        self.runtime = rt = runtime_context(self.store, self.key, McpProxy(self.store, allow_private=True, http=self.client))
        with self.store._lock: self.store._db.executescript(ADMIN_SCHEMA)
        with self.store.tx() as db:
            session = create_session(db, owner, 'sadmin', 'superadmin', 'Synthetic reviewer')
        self.refs.update(owner=owner, session=session)
        registry = Registry(self.store)
        for host, (contract, spec) in self.transport.specs.items():
            identity = self.store.upsert_resource({'key': 'mcp:https://' + host + '/mcp', 'kind': 'mcp',
                'source': 'synthetic-storage-fixture', 'name': 'Synthetic ' + contract, 'description': 'Synthetic fixture only',
                'category': 'data_utility', 'url': 'https://' + host + '/mcp', 'price_usdc': 0, 'details': {}})
            compact = usage.compact_tools([spec])
            self.store.record_usage(identity, compact, usage.tools_hash(compact), {}, None, {'ok': True}, full_tools=[spec])
            with self.store.tx() as db: db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (identity,))
            registry.approve(self.store.resource(identity), contract, spec['name'])
            args = {'query': 'Synthetic storage news documentation', 'language': 'en', 'limit': 3}
            if contract == 'news.search.v1': args['from_utc'] = utc(time.time() - 86400)
            if contract == 'products.compare.v2': args['criteria'] = [{'criterion_id': 'mass', 'dimension': 'mass'}]
            first = rt.proxy.execute(identity, spec['name'], args)
            if first.get('ok') is not True: raise ValueError('Synthetic MCP transport failed its fixture precondition.')
            async def runner(rid, **kwargs):
                result = rt.proxy.execute(rid, kwargs['tool'], kwargs['arguments'])
                return {'execution_succeeded': result.get('ok') is True, 'simulated': False, 'output': result.get('result')}
            tested = asyncio.run(run_test(registry, self.store.resource(identity), contract, args, runner))
            if not tested['ok']: raise ValueError('Synthetic contract fixture failed its precondition.')
            self.refs[contract] = identity
        draft = rt.composer.generate({'prompt': 'Synthetic news and documentation storage search'}, owner)
        saved = rt.composer.save({k: draft[k] for k in ('proposal', 'signature')} | {'authority': True, 'notice': SAVE}, owner)
        literal = self.store.get_workflow(saved['id'])
        principal = rt.principal('admin', owner, literal['id'], role='superadmin')
        proof = self.execute(rt.submit(literal, actor='storage-fixture:literal', idempotency='literal-proof', principal=principal))
        rt.composer.validate_publish(literal, proof['run_id'])
        with self.store.tx() as db: db.execute('UPDATE agent_workflows SET is_template=1 WHERE id=?', (literal['id'],))
        literal = self.store.get_workflow(literal['id'])
        self.refs.update(literal_workflow=literal, literal_proof=proof['run_id'])
        self._authorities(owner, literal)
        self._scenarios(owner, literal)
        self.expected['replay_rows'] = [tuple(row) for row in self.store.query('SELECT id,actor,idempotency_key FROM workflow_runs ORDER BY id')]
        self.expected['attempt_rows'] = [tuple(row) for row in self.store.query('SELECT run_id,node_id,input_hash,status FROM workflow_execution_attempts ORDER BY run_id,node_id')]
        return self

    def _authorities(self, owner, literal):
        from .workflow_apps_v12 import WorkflowAppsV12
        from .workflow_deployment_consent import GRANT_NOTICE as SDK12_GRANT, SHARE_NOTICE as SDK12_SHARE, RUN_NOTICE as SDK12_RUN
        from .workflow_publication import TEST_SHARE_NOTICE, TEST_RUN_NOTICE, PUBLISH_NOTICE, SHARE_NOTICE, RUN_NOTICE
        from .workflow_connection_deployment import GRANT_NOTICE as SDK13_GRANT, SHARE_NOTICE as SDK13_SHARE, RUN_NOTICE as SDK13_RUN
        from .workflow_connection_automation import SHARE_NOTICE as AUTO_SHARE, GRANT_NOTICE as AUTO_GRANT, EVENT_NOTICE
        rt = self.runtime
        request = {'allowed_origins': [ORIGIN], 'minute_limit': 10, 'day_limit': 100, 'ttl_seconds': 3600}
        service = WorkflowAppsV12(rt)
        plan = service.prepare_admin(literal['id'], request, owner)
        exported = service.export_admin(literal['id'], {k: plan[k] for k in ('proposal', 'signature')} |
                                        {'grant_authority': True, 'grant_notice': SDK12_GRANT}, owner)
        app12 = exported['deployment']; prepared = rt.deployment_consent.prepare(app12['app_id'], ORIGIN)
        context = {'ticket': prepared['ticket'], 'signature': prepared['signature'], 'sharing_authority': True,
                   'sharing_notice': SDK12_SHARE, 'run_authority': True, 'run_notice': SDK12_RUN, 'origin': ORIGIN}
        job = rt.submit(literal, actor='webapp-v12:' + app12['app_id'], source='webapp', idempotency=context['ticket']['nonce'],
                        principal=rt.principal('deployment', app12['app_id'], literal['id']), deployment_consent=context)
        self.execute(job)
        self.refs.update(sdk12=app12, sdk12_context=context, sdk12_run=job['run_id'])
        options = rt.publication.options(owner)
        candidate = rt.publication.candidate({'source_id': options['news'][0]['id'], 'target_id': options['docs'][0]['id'],
            'query': 'Synthetic storage news documentation', 'from_utc': utc(time.time() - 86400), 'limit': 3}, owner)
        declaration = {k: candidate[k] for k in ('proposal', 'signature')} | {'sharing_authority': True,
            'sharing_notice': TEST_SHARE_NOTICE, 'run_authority': True, 'run_notice': TEST_RUN_NOTICE}
        proof = self.execute(rt.publication.test(declaration, owner))
        plan = rt.publication.publication_candidate({'run_id': proof['run_id'], 'ttl_seconds': 3600}, owner)
        release = rt.publication.publish({k: plan[k] for k in ('proposal', 'signature')} |
                                        {'publication_authority': True, 'publication_notice': PUBLISH_NOTICE}, owner)
        public_plan = rt.publication.prepare_run(release['id'])
        body = {k: public_plan[k] for k in ('proposal', 'signature')} | {'sharing_authority': True,
            'sharing_notice': SHARE_NOTICE, 'run_authority': True, 'run_notice': RUN_NOTICE}
        public_job = rt.publication.execute_run(release['id'], body); self.execute(public_job)
        plan = rt.connection_deployments.prepare_admin(release['id'], request, owner)
        app13 = rt.connection_deployments.issue(release['id'], {k: plan[k] for k in ('proposal', 'signature')} |
            {'deployment_authority': True, 'deployment_notice': SDK13_GRANT}, owner)['deployment']
        prepared = rt.connection_deployments.prepare_run(app13['app_id'], ORIGIN)
        body13 = {k: prepared[k] for k in ('proposal', 'signature')} | {'sharing_authority': True,
            'sharing_notice': SDK13_SHARE, 'run_authority': True, 'run_notice': SDK13_RUN}
        job13 = rt.connection_deployments.execute_run(app13['app_id'], body13, ORIGIN); self.execute(job13)
        grants = []
        for trigger in ('event', 'scheduled'):
            plan = rt.automation.prepare(release['id'], {'trigger': trigger, 'interval_seconds': 300 if trigger == 'scheduled' else 0,
                'max_runs': 3, 'ttl_seconds': 1800}, owner)
            grant = rt.automation.issue(release['id'], {k: plan[k] for k in ('proposal', 'signature')} |
                {'sharing_authority': True, 'sharing_notice': AUTO_SHARE, 'trigger_authority': True, 'trigger_notice': AUTO_GRANT}, owner)['grant']
            grants.append(grant)
        event_id = hashlib.sha256(('event:' + str(self.seed)).encode()).hexdigest()[:32]
        event_body = {'event_id': event_id, 'authority': True, 'notice': EVENT_NOTICE}
        event_job = rt.automation.trigger(release['id'], grants[0]['id'], event_body, owner); self.execute(event_job)
        # Withdrawn purpose rows remain present as replay/revocation tombstones.
        plan = service.prepare_admin(literal['id'], request, owner)
        retired12 = service.export_admin(literal['id'], {k: plan[k] for k in ('proposal', 'signature')} |
            {'grant_authority': True, 'grant_notice': SDK12_GRANT}, owner)['deployment']
        rt.deployment_consent.revoke(retired12['app_id'], retired12['revision'])
        plan = rt.connection_deployments.prepare_admin(release['id'], request, owner)
        retired13 = rt.connection_deployments.issue(release['id'], {k: plan[k] for k in ('proposal', 'signature')} |
            {'deployment_authority': True, 'deployment_notice': SDK13_GRANT}, owner)['deployment']
        rt.connection_deployments.revoke(release['id'], retired13['app_id'], retired13['revision'], owner)
        retired_candidate = rt.publication.candidate({'source_id': options['news'][0]['id'], 'target_id': options['docs'][0]['id'],
            'query': 'Synthetic withdrawn storage news documentation', 'from_utc': utc(time.time() - 86400), 'limit': 3}, owner)
        retired_proof = self.execute(rt.publication.test({k: retired_candidate[k] for k in ('proposal', 'signature')} |
            {'sharing_authority': True, 'sharing_notice': TEST_SHARE_NOTICE, 'run_authority': True, 'run_notice': TEST_RUN_NOTICE}, owner))
        plan = rt.publication.publication_candidate({'run_id': retired_proof['run_id'], 'ttl_seconds': 3600}, owner)
        retired_release = rt.publication.publish({k: plan[k] for k in ('proposal', 'signature')} |
            {'publication_authority': True, 'publication_notice': PUBLISH_NOTICE}, owner)
        rt.publication.revoke(retired_release['id'], retired_release['revision'], owner)
        plan = rt.automation.prepare(release['id'], {'trigger': 'event', 'interval_seconds': 0, 'max_runs': 1, 'ttl_seconds': 1800}, owner)
        retired_auto = rt.automation.issue(release['id'], {k: plan[k] for k in ('proposal', 'signature')} |
            {'sharing_authority': True, 'sharing_notice': AUTO_SHARE, 'trigger_authority': True, 'trigger_notice': AUTO_GRANT}, owner)['grant']
        rt.automation.revoke(release['id'], retired_auto['id'], retired_auto['revision'], owner)
        self.refs.update(publication=release, publication_test=proof['run_id'], public_run=public_job,
            public_body=body, sdk13=app13, sdk13_body=body13, sdk13_run=job13,
            automation=grants, event_body=event_body, automation_run=event_job,
            withdrawn_sdk12=retired12, withdrawn_sdk13=retired13, withdrawn_publication=retired_release, withdrawn_automation=retired_auto)

    def _scenarios(self, owner, workflow):
        rt = self.runtime; completed = []
        for index in range(self.completed):
            job = rt.submit(workflow, actor='storage-fixture:completed', idempotency='completed-' + str(index),
                            principal=rt.principal('admin', owner, workflow['id'], role='superadmin'))
            self.execute(job); completed.append(job['run_id'])
        tampered = completed[-1]
        with self.store.tx() as db: db.execute("UPDATE workflow_checkpoints SET signature=? WHERE run_id=? AND node_id='search-1'", ('0' * 64, tampered))
        job = rt.submit(workflow, actor='storage-fixture:unknown', idempotency='unknown-once',
                        principal=rt.principal('admin', owner, workflow['id'], role='superadmin'))
        # Inject the durable unknown boundary directly. This exercises the
        # real recovery policy without a provider timeout or diagnostic log.
        row = rt.persistence.claim(job['run_id'], 'synthetic-uncertain-owner', 25)
        input_hash = rt.authority.signature({'audience': 'workflow-input-v1', 'digest': row['digest'],
                                            'node_id': 'search-1', 'input': workflow['nodes'][1]['data']['input']})
        rt.persistence.prepare(job['run_id'], 'synthetic-uncertain-owner', row['fence'], 'search-1', input_hash)
        rt.persistence.dispatch(job['run_id'], 'synthetic-uncertain-owner', row['fence'], 'search-1')
        with self.store.tx() as db: db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?', (job['run_id'],))
        rt.persistence.recover()
        held = completed[-2]
        destination = 'wd_' + hashlib.sha256(('destination:' + str(self.seed)).encode()).hexdigest()[:32]
        outbox = 'we_' + hashlib.sha256(('outbox:' + str(self.seed)).encode()).hexdigest()[:32]
        manual = 'wm_' + hashlib.sha256(('manual:' + str(self.seed)).encode()).hexdigest()[:32]
        now = time.time()
        payload = {'audience': 'synthetic-pending-delivery-v1', 'run_id': held, 'fixture_only': True}
        with self.store.tx() as db:
            db.execute('INSERT INTO workflow_destinations VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (destination, workflow['id'], 'webhook', 'synthetic-sealed-value', 'verified', None, now + 3600, 0, now, now, 'synthetic-fixture-only'))
            db.execute("INSERT INTO workflow_result_outbox(id,run_id,destination_id,status,created) VALUES (?,?,?,'pending',?)", (outbox, held, destination, now))
            db.execute("INSERT INTO workflow_manual_deliveries VALUES (?,?,?,?,?,'pending',NULL,0,0,?,NULL)",
                       (manual, held, outbox, canonical(payload), rt.authority.signature(payload), now))
            db.execute('INSERT INTO workflow_event_receipts VALUES (?,?,?)', (workflow['id'], 'synthetic-retained-event', now))
        # Production delivery authority points only to a deliberately nonusable
        # synthetic sealed destination. No courier exists and no drain is run.
        rt.authority.issue(workflow['id'], self.store.query('SELECT digest FROM workflow_runs WHERE id=?', (held,))[0][0],
                           dict(self.store.query('SELECT * FROM workflow_destinations WHERE id=?', (destination,))[0]), ['admin'],
                           rt.principal('admin', owner, workflow['id'], role='superadmin')['payload'])
        active = rt.submit(workflow, actor='storage-fixture:queued', idempotency='queued-no-launch',
                           principal=rt.principal('admin', owner, workflow['id'], role='superadmin'))
        self.refs.update(completed_runs=completed, tampered_run=tampered, held_run=held, unknown_run=job['run_id'],
                         active_run=active['run_id'], outbox=outbox, manual_delivery=manual, destination=destination)


def synthetic_fixture(directory, *, seed=20261018, completed=8):
    """Create a new bounded synthetic directory; never accept an existing DB."""
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1 or type(completed) is not int or not 2 <= completed <= MAX_COMPLETED:
        raise ValueError('Choose bounded synthetic fixture parameters.')
    if 'AGENT_UPDATES_KEY' in os.environ:
        raise ValueError('Run synthetic storage fixtures without a configured operating update key.')
    directory = Path(directory)
    if not directory.is_absolute() or directory.exists() or directory.is_symlink() or not directory.parent.is_dir():
        raise ValueError('A new absolute synthetic fixture directory is required.')
    directory.mkdir(mode=0o700, exist_ok=False)
    fixture = SyntheticFixture(directory, seed, completed)
    try: return fixture.populate()
    except BaseException:
        fixture.close()
        raise
