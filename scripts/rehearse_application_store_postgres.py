"""Actual application Store contracts on disposable Unix-socket PostgreSQL.

Only --run is accepted. No operating path, DSN, credentials, server, provider or
output destination can be supplied. This exercises source behavior; it neither
authorizes a cutover nor measures operating workload, HA or disaster recovery.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster, PORT

PROFILE = 'application-store-postgres-contracts-v1'


def require(value, label):
    if value is not True: raise AssertionError(label)


def _contracts(connect, *, store_factory=None, require_private_cluster=True):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.storage_adapter import open_store
    from agent_market.gateway.store import Store
    from agent_market.gateway import admin_auth
    from agent_market.workspace_access import WorkspaceAccess, SessionActor, WorkspaceDenied
    from agent_market.customer_identity import CustomerIdentity, GitHubConfig
    from agent_market.customer_identity_service import router_for as customer_router, COOKIE
    from agent_market.customer_organizations import CustomerOrganizations
    from agent_market.gateway.rag import RagEngine
    from agent_market.legacy_vector_index import ModelDescriptor

    pg = connect()
    # Prove the transport before Store initialization can create any object.
    with pg.cursor() as cursor:
        cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
        transport = cursor.fetchone()
        require(transport == ('', None, None) if require_private_cluster else transport[1:] == (None, None), 'owned Unix transport')
    def make_store(connection, **kwargs):
        return (store_factory(connection, **kwargs) if store_factory else
                open_store('postgresql', connection=connection, **kwargs))
    store = make_store(pg, initialize=True, workflow_key=b'k' * 32)
    sqlite = Store()
    checks = {}
    try:
        with pg.cursor() as cursor:
            cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
            transport = cursor.fetchone()
            checks['unix_socket_only'] = (transport == ('', None, None) if require_private_cluster else transport[1:] == (None, None))
        records = [
            {'key': 'synthetic:news', 'source': 'fixture', 'kind': 'mcp', 'url': 'https://news.example/mcp',
             'name': 'Café market research', 'description': 'Stocks, semiconductor and AI news', 'category': 'news_media', 'networks': [], 'details': {}},
            {'key': 'synthetic:docs', 'source': 'fixture', 'kind': 'a2a', 'url': 'https://docs.example/agent',
             'name': 'Research documentation', 'description': 'Market reports and developer documents', 'category': 'developer_tools', 'networks': [], 'details': {}},
            {'key': 'synthetic:security', 'source': 'fixture', 'kind': 'mcp', 'url': 'https://quarantine.example/mcp',
             'name': 'Market news', 'description': 'Stocks news feeds', 'category': 'news_media', 'networks': [], 'details': {}},
        ]
        for index, record in enumerate(records):
            require(store.upsert_resource(record, now=10 + index) == sqlite.upsert_resource(record, now=10 + index), 'stable ids')
        checks['catalog_scalar_null_json_id_parity'] = all(store.resource(i) == sqlite.resource(i) for i in (1, 2, 3))
        for current in (store, sqlite):
            current.record_evaluation(3, {'security': 'quarantine', 'score': 1, 'grade': 'F', 'at': 20})
        for query in ('cafe', 'stocks', 'market research', 'documents', 'nothing-matches'):
            for kinds in (['mcp'], ['a2a'], ['mcp', 'a2a']):
                left = [r['id'] for r in store.search(query, 'news_media', None, [], kinds)]
                right = [r['id'] for r in sqlite.search(query, 'news_media', None, [], kinds)]
                require(left == right, 'native FTS ordering')
        checks['fts5_unicode_bm25_filter_parity'] = True
        checks['idf_exact_parity'] = store.idf(['cafe', 'stocks', 'absent']) == sqlite.idf(['cafe', 'stocks', 'absent'])
        changed = records[0] | {'name': 'Changed search corpus', 'description': 'Quantum photonics'}
        for current in (store, sqlite): current.upsert_resource(changed, now=30)
        checks['fts_epoch_invalidates_previous_projection'] = (
            [r['id'] for r in store.search('photonics', 'none', None, [], ['mcp'])] == [1]
            and store.idf(['cafe']) == sqlite.idf(['cafe']))
        store.set_meta('synthetic', {'snowman': '\u2603', 'quotes': "O'Reilly; --", 'zero': 0})
        checks['metadata_named_upsert_round_trip'] = store.get_meta('synthetic')['zero'] == 0
        before = store.resource(1)['category']
        try:
            with store.tx():
                store.set_category(1, 'rolled_back')
                try: store._db.execute('SELECT synthetic_unregistered_statement')
                except ApplicationStoreError: pass
        except ApplicationStoreError: pass
        checks['caught_unsupported_sql_rolls_back_whole_transaction'] = store.resource(1)['category'] == before
        try:
            with store.tx(readonly=True): store._db.execute('UPDATE resources SET category=? WHERE id=?', ('forbidden', 1))
        except ApplicationStoreError: pass
        checks['native_readonly_rejects_writer'] = store.resource(1)['category'] == before
        with store.tx() as db:
            user = admin_auth.create_admin_user(db, 'fixture-owner', 'Synthetic-application-password-42', 'Fixture owner', 'superadmin')
            token = admin_auth.create_session(db, user['id'], user['username'], user['role'], user['name'])
            authenticated = admin_auth.authenticate_user(db, user['username'], 'Synthetic-application-password-42')
        checks['current_staff_auth_session_repositories'] = authenticated['id'] == user['id']
        access = WorkspaceAccess(store, b'k' * 32)
        staff = SessionActor(user['id'], admin_auth.session_reference(token))
        ws = access.provision({'name': 'Native PostgreSQL team', 'owner_id': user['id']}, staff)
        draft = access.save_draft(ws['id'], {'name': 'Draft', 'description': 'Private draft', 'definition': {'nodes': [], 'edges': []}}, staff)
        snapshot = access.create_snapshot(ws['id'], draft['id'], {'draft_revision': 1}, staff)
        checks['staff_signed_draft_snapshot_native_transactions'] = snapshot['snapshot']['name'] == 'Draft'
        state = {'subject': 4001}
        config = GitHubConfig('synthetic-app', 'https://agentconcierge.biz/api/customer-auth/github/callback', 'synthetic-server-secret')
        def identity_provider(request):
            if str(request.url) == config.token_endpoint:
                return httpx.Response(200, json={'access_token': 'synthetic-provider-access-token-42', 'token_type': 'bearer'})
            if str(request.url) == config.user_endpoint:
                return httpx.Response(200, json={'id': state['subject'], 'email': 'ignored@example.invalid'})
            raise AssertionError('Unconfigured identity destination')
        http = httpx.Client(transport=httpx.MockTransport(identity_provider))
        identity = CustomerIdentity(store, b'synthetic-customer-session-key-32!', http=http, github_config=config)
        def login(subject):
            state['subject'] = subject
            prepared = identity.begin('b' * 64, 'github')
            query = parse_qs(urlsplit(prepared['authorization_url']).query)
            return identity.complete(query['state'][0], 'synthetic-one-use-code', 'b' * 64, 'github')
        first, second = login(4001), login(4002)
        owner, recipient = identity.actor(first['session_token']), identity.actor(second['session_token'])
        orgs = CustomerOrganizations(identity, access)
        organization = orgs.create({'name': 'Customer-owned organization'}, owner)
        invite = orgs.invite(organization['id'], {'customer_id': recipient.customer_id, 'role': 'editor', 'revision': 1}, owner)
        orgs.resolve_invitation(invite['id'], {'decision': 'accept', 'revision': 1}, recipient)
        actor = orgs.runtime_actor(organization['id'], recipient)
        private = orgs.drafts.save_draft(organization['id'], {'name': 'Customer draft', 'description': '', 'definition': {'nodes': [], 'edges': []}}, actor)
        saved = orgs.drafts.create_snapshot(organization['id'], private['id'], {'draft_revision': 1}, actor)
        checks['customer_oidc_storage_org_invite_snapshot_parity'] = (
            saved['snapshot']['name'] == 'Customer draft' and orgs.detail(organization['id'], recipient)['can_edit'])
        app = FastAPI(); app.include_router(customer_router(store, b'synthetic-customer-session-key-32!', identity=identity, admin=False))
        with TestClient(app, base_url='https://agentconcierge.biz') as client:
            client.cookies.set(COOKIE, first['session_token'])
            get = client.get('/api/customer-organizations')
            create = client.post('/api/customer-organizations', headers={'Origin': 'https://agentconcierge.biz', 'X-Customer-CSRF': first['csrf_token']}, json={'name': 'Created through API'})
            require(get.status_code == create.status_code == 200, 'customer API')
            checks['customer_http_api_no_store_native_pg'] = ('no-store' in get.headers['cache-control'] and len(get.json()['account']['organizations']) == 1)
        from agent_market.customer_authoring import CustomerAuthoringAccess
        from agent_market.workspace_provider_connections import ProviderConnections, NOTICE as CONNECTION_NOTICE
        connections = ProviderConnections(CustomerAuthoringAccess(access, identity))
        connection_actor = orgs.runtime_actor(organization['id'], owner)
        store.record_auth(1, {'method':'bearer','autonomy':'human_once','info':{}}, None)
        connection_profile = connections.inspect(organization['id'], connection_actor, 1)['agent']
        saved_connection = connections.save_key(organization['id'], connection_actor, 1, {
            'authorized':True,'notice':CONNECTION_NOTICE,'fingerprint':connection_profile['fingerprint'],
            'revision':0,'key':'synthetic-native-provider-key-1234'})
        require(saved_connection['status']=='saved_unverified','native provider key save')
        listed_connections = connections.listing(organization['id'],connection_actor)
        require(len(listed_connections['connections'])==1,'native provider connection listing')
        require(connections.search(organization['id'],connection_actor,'NEWS')['agents'][0]['resource_id']==1,
                'native provider catalog search and case folding')
        require('synthetic-native-provider-key-1234' not in store.get_meta(connections._key(organization['id'])),
                'native provider key encrypted at rest')
        connections.disconnect(organization['id'],connection_actor,1,{'revision':1})
        checks['native_customer_provider_connection_encryption_search_and_disconnect'] = not connections.listing(organization['id'],connection_actor)['connections']
        checks['customer_logout_revokes_current_authority'] = identity.logout(second['session_token'])['signed_out'] is True
        try: orgs.detail(organization['id'], recipient)
        except WorkspaceDenied: checks['customer_logout_revokes_current_authority'] &= True
        else: checks['customer_logout_revokes_current_authority'] = False
        inquiry = store.record_customer_inquiry('general', '<b>Fixture</b>', 'fixture@example.invalid', 'Subject', 'Private inquiry', visitor_token='opaque-synthetic')
        privacy = store.record_privacy_request('ccpa_opt_out', details='Synthetic privacy request')
        require(store.update_customer_inquiry(inquiry, 'resolved', 'Resolved'), 'inquiry update')
        checks['footer_inquiry_privacy_repository_round_trip'] = (store.get_customer_inquiry(inquiry)['status'] == 'resolved'
            and store.list_privacy_requests(search=privacy)[1] == 1)
        from agent_market.workflows import runtime_for
        from agent_market.workspace_platform import platform_for
        runtime = runtime_for(store, None)
        graph = platform_for(None, store=store, runtime=runtime)
        checks['current_runtime_and_private_graph_boot'] = graph.access.store is store and graph.app_execution.access.identity.store is store
        from agent_market.observability import journal_for
        operation = journal_for(store).begin('execution', 'managed', resource_id=1, proto='mcp')
        operation.finish('succeeded')
        checks['observability_uses_native_pg_transaction'] = bool(operation.id and journal_for(store).write_failures == 0)
        from agent_market.concierge.task_updates import TaskUpdates
        checks['explicit_workflow_key_and_pg_heartbeat'] = TaskUpdates._load_key(runtime) == b'k' * 32
        with runtime.persistence.heartbeat_connection() as connection:
            checks['explicit_workflow_key_and_pg_heartbeat'] &= connection is None
            checks['explicit_workflow_key_and_pg_heartbeat'] &= runtime.persistence.pulse('absent-fixture-run', 'fixture-worker', 1, connection) is False
        # Real MCP protocol parsing against a controlled in-process responder,
        # followed by current registry contract evidence and whole-graph consent.
        import asyncio
        import copy
        from tests.test_workflow_fallback import tool, output
        from tests.test_mcp_proxy import MockRemoteMcp
        from agent_market.collector import usage
        from agent_market.concierge.proxy import McpProxy
        from agent_market.capability_registry import Registry
        from agent_market.capability_contracts import run_test
        from agent_market.workspace_typed_flows import NOTICE as TYPED_NOTICE
        from agent_market.workspace_metering import NOTICE as METER_NOTICE
        tools = [tool()]
        mock_remote = MockRemoteMcp(tools, call_result=output())
        provider_http = httpx.Client(transport=mock_remote)
        proxy = McpProxy(store, allow_private=True, http=provider_http)
        runtime.proxy = graph.execution.proxy = graph.app_execution.proxy = proxy
        registry, typed_ids = Registry(store), []
        for number in range(2):
            rid = store.upsert_resource({'key': 'synthetic:typed:' + str(number), 'source': 'mcp-registry', 'kind': 'mcp',
                'url': 'https://typed-' + str(number) + '.example/mcp', 'name': 'Typed documentation',
                'description': 'Public documents', 'category': 'dev_tools', 'networks': [], 'price_usdc': 0, 'details': {}})
            store.record_usage(rid, usage.compact_tools(tools), usage.tools_hash(usage.compact_tools(tools)), {}, None, {'ok': True}, full_tools=tools)
            store.record_health(rid, 'healthy', 200, 1, None, time.time() + 3600)
            registry.approve(store.resource(rid), 'docs.search.v1', 'search_docs')
            async def contract_runner(identity, **kwargs):
                value = proxy.execute(identity, kwargs['tool'], kwargs['arguments'])
                require(value.get('ok') is True, 'synthetic MCP transport: ' + str(value))
                from agent_market.capability_contracts import validate
                validate('docs.search.v1', kwargs['arguments'], value['result']['structuredContent'])
                return {'execution_succeeded': value.get('ok') is True, 'simulated': False, 'output': value.get('result')}
            with ThreadPoolExecutor(max_workers=1) as pool:
                evaluated = pool.submit(lambda: asyncio.run(run_test(registry, store.resource(rid), 'docs.search.v1',
                    {'query': 'documentation', 'language': 'en', 'limit': 2}, contract_runner))).result(timeout=10)
            require(evaluated['ok'], 'native MCP contract evidence: ' + str(evaluated))
            typed_ids.append(rid)
        graph.meter.configure(ws['id'], {'revision': 0, 'enabled': True, 'units_per_success': 7,
            'max_runs': 10, 'ttl_seconds': 3600, 'authorized': True, 'notice': METER_NOTICE}, staff)
        flow = graph.typed_flows.save(ws['id'], {'flow_id': None, 'revision': 0, 'name': 'Native typed graph',
            'definition': {'nodes': [
                {'id': 'first', 'resource_id': typed_ids[0], 'contract_id': 'docs.search.v1',
                 'input': {'query': 'documentation', 'language': 'en', 'limit': 2}, 'bindings': {}, 'after': [], 'when': None},
                {'id': 'second', 'resource_id': typed_ids[1], 'contract_id': 'docs.search.v1',
                 'input': {'language': 'en', 'limit': 2}, 'bindings': {'query': {'node_id': 'first', 'path': ['items', 0, 'title']}},
                 'after': ['first'], 'when': {'node_id': 'first', 'path': ['partial'], 'equals': False}},
            ]}}, staff)
        checks['typed_library_reports_actual_agent_steps'] = next(
            item for item in graph.typed_flows.listing(ws['id'], staff) if item['id'] == flow['id'])['step_count'] == 2
        ticket = graph.typed_flows.prepare(ws['id'], flow['id'], {'revision': flow['revision']}, staff)
        typed_result = graph.typed_flows.execute(ws['id'], flow['id'], {'ticket_id': ticket['ticket_id'],
            'authorized': True, 'notice': TYPED_NOTICE}, staff)
        require(typed_result['run']['status'] == 'succeeded', 'native typed graph')
        replay = graph.typed_flows.execute(ws['id'], flow['id'], {'ticket_id': ticket['ticket_id'],
            'authorized': True, 'notice': TYPED_NOTICE}, staff)
        meter = graph.meter.summary(ws['id'], staff)
        checks['typed_graph_and_meter_native_pg_transactions'] = (replay['replayed'] and meter['operations'] == 1
            and meter['attempts'] == 2 and meter['balanced'] and meter['simulated_units'] == 7)
        from agent_market.provider_claims import NOTICE as PROOF_NOTICE
        from agent_market.workspace_agreements import WorkspaceAgreements, NOTICE as AGREEMENT_NOTICE
        from tests.test_workspace_agreements import contract
        proof = {'value': None}
        claim_http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=proof['value'])))
        claims = graph.claims
        claims.http = claim_http
        prepared = claims.prepare(ws['id'], {'resource_id': typed_ids[0]}, staff)
        proof['value'] = copy.deepcopy(prepared['challenge'])
        verified = claims.verify(ws['id'], {'claim_id': prepared['claim']['id'], 'revision': prepared['claim']['revision'],
            'authorized': True, 'notice': PROOF_NOTICE}, staff)
        agreements = WorkspaceAgreements(graph.access, claims)
        agreement = agreements.create(ws['id'], {'resource_id': typed_ids[0], 'claim_id': verified['id'],
            'claim_revision': verified['revision'], 'revision': 0, 'expires': time.time() + 3600,
            'terms': contract(), 'authorized': True, 'notice': AGREEMENT_NOTICE}, staff)
        quote = agreements.quote(ws['id'], agreement['id'], {'gross_units': 101}, staff)
        settlement = agreements.settle(ws['id'], agreement['id'], {'event_reference': 'sim_native_capture', 'gross_units': 101,
            'quote_hash': quote['quote_hash'], 'revision': agreement['revision'], 'authorized': True, 'notice': AGREEMENT_NOTICE}, staff)
        refunded = agreements.refund(ws['id'], settlement['id'], {'event_reference': 'sim_native_full_refund', 'units': 101,
            'revision': settlement['revision'], 'authorized': True, 'notice': AGREEMENT_NOTICE}, staff)
        checks['provider_proof_agreement_conserved_simulation_native_pg'] = (
            refunded['status'] == 'refunded' and agreements.summary(ws['id'], staff)['balanced']
            and agreement['actual_money'] is False)
        from tests.test_workflow_runtime import node
        template_id = store.create_workflow({'name': 'Native Documentation Search', 'is_template': 1,
            'nodes': [node('search', resource_id=typed_ids[0], tool='search_docs',
                input={'query': 'documentation', 'language': 'en', 'limit': 2})], 'edges': []})
        review_id = store.add_workflow_review(template_id, 'Synthetic reviewer', 4, 'Useful documentation')
        reports = store.create_test_report({'resource_id': typed_ids[0], 'title': 'Native documentation check',
            'slug': 'native-documentation-check', 'kind': 'mcp', 'agent_name': store.resource(typed_ids[0])['name'],
            'is_success': True, 'pros': ['Current evidence'], 'cons': []})
        checks['current_workflow_reports_reviews_store_methods'] = (
            store.list_workflows(is_template=1, q='Native')[1] == 1
            and store.list_test_reports(q='documentation', is_success=True)[1] == 1
            and store.list_workflow_reviews(template_id)[0]['id'] == review_id
            and store.get_test_report(reports)['title'] == 'Native documentation check')
        from agent_market.concierge.front import Front, create_front_app
        public = Front(store, public_url='https://agentconcierge.biz')
        with TestClient(create_front_app(public), base_url='https://agentconcierge.biz') as client:
            response = client.get('/api/workflows/templates')
            require(response.status_code == 200 and response.json()['count'] == 1, 'current public workflow listing')
            exported = client.get('/api/workflows/' + str(template_id) + '/webapp')
            require(exported.status_code == 200 and exported.content.startswith(b'PK'), 'current public workflow export')
            checks['current_public_workflow_templates_and_webapp_http'] = True
            landing = client.get('/', headers={'Accept': 'text/html'})
            checks['native_public_workspace_access_remains_closed_by_default'] = (
                client.get('/customer/sign-in').status_code == client.get('/api/customer-auth/options').status_code == 404
                and landing.status_code == 200 and 'href="/customer/sign-in"' not in landing.text
                and 'Workspace access' not in landing.text)
        from scripts.rehearse_customer_postgres_runtime import run_private_customer_contracts
        checks.update(run_private_customer_contracts(store, graph, identity, first, ws, staff, typed_ids[0]))
        from scripts.rehearse_typed_sdk2_postgres import run_typed_customer_contracts
        checks.update(run_typed_customer_contracts(store, graph, identity, first, ws, staff, flow, typed_result))
        # The public Front above installs its own proxy on the shared runtime.
        # Restore the explicitly controlled in-process MCP transport before any
        # private reliability fixture exercises that runtime.
        runtime.proxy = graph.execution.proxy = graph.app_execution.proxy = proxy
        from scripts.rehearse_reliability_postgres import run_reliability_contracts
        checks.update(run_reliability_contracts(store, graph, ws, staff, typed_ids[0], token))
        from scripts.rehearse_reliability_completion_postgres import run_reliability_completion_contracts
        checks.update(run_reliability_completion_contracts(store, graph, staff, typed_ids[0], token))
        from scripts.rehearse_reliability_controls_postgres import run_reliability_control_contracts
        checks.update(run_reliability_control_contracts(store, graph, ws, staff, typed_ids[0], token))
        from scripts.rehearse_machine_updates_postgres import run_machine_update_contracts
        checks.update(run_machine_update_contracts(store, graph, ws, staff, typed_ids[0], token))
        from scripts.rehearse_workspace_growth_postgres import run_growth_contracts
        checks.update(run_growth_contracts(store, graph, ws, staff, typed_ids, flow, typed_result))
        from scripts.rehearse_typed_evidence_postgres import run_typed_evidence_contracts
        checks.update(run_typed_evidence_contracts(store, graph, ws, staff, typed_ids, session_token=token))
        from scripts.rehearse_rnd_postgres import run_research_contracts
        checks.update(run_research_contracts(store, graph, ws, staff, typed_ids[0]))
        from scripts.rehearse_rnd_controls_postgres import run_rnd_control_contracts
        checks.update(run_rnd_control_contracts(store, graph, ws, staff, typed_ids, template_id, agreement))
        from scripts.rehearse_circuit_postgres import run_circuit_contracts
        checks.update(run_circuit_contracts(store, graph, ws, staff, typed_ids[0]))
        from scripts.rehearse_completion_private_postgres import run_completion_private_contracts
        checks.update(run_completion_private_contracts(store, graph, identity, first, ws, staff, typed_ids[0], token))
        provider_http.close(); claim_http.close()
        # Existing source/claim/model/fence checks execute unchanged on PG.
        descriptor = ModelDescriptor('synthetic-embedding', revision='fixture-v1')
        index = store._vector_index
        index.ensure_jobs(descriptor, limit=1, resource_ids=(1,))
        claim = index.claim_batch(descriptor, limit=1, resource_ids=(1,))[0]
        vector = [1.0] + [0.0] * 767
        require(index.publish(claim, vector, descriptor) == 'indexed', 'native vector publication')
        checks['fenced_vector_current_provenance'] = index.current_ids([1], descriptor) == {1}
        from agent_market.application_store_vector import cosine
        import struct
        same = struct.pack('<768f', *vector)
        perpendicular = struct.pack('<768f', *([0.0, 1.0] + [0.0] * 766))
        checks['cosine_float32_metric'] = cosine(same, same) == 0 and cosine(same, perpendicular) == 1
        engine = RagEngine(embed_model='synthetic-embedding', embed_revision='fixture-v1')
        result = engine.hybrid_search(store._db, 'photonics', query_embedding=vector, query_descriptor=descriptor)
        checks['hybrid_rrf_current_published_vector'] = bool(result and result[0]['id'] == 1 and result[0]['dense_match'])
        checks['native_vector_stats_current_projection'] = store.vec_stats(descriptor)['vector_count'] == 1
        with store.tx():
            cursor = store._native('UPDATE vec_resources SET embedding=%s WHERE rowid=1',
                (struct.pack('<768f', *([float('nan')] + [0.0] * 767)),))
            cursor.close()
        lexical = engine.hybrid_search(store._db, 'photonics', query_embedding=vector, query_descriptor=descriptor)
        checks['native_vector_stats_rejects_tampered_bytes'] = store.vec_stats(descriptor)['vector_count'] == 0
        checks['invalid_dense_vector_retains_lexical_results'] = bool(lexical and lexical[0]['id'] == 1
            and lexical[0]['bm25_match'] and not lexical[0]['dense_match'])
        with store.tx(): store._native('UPDATE vec_resources SET embedding=%s WHERE rowid=1', (same,)).close()
        pending = records[0] | {'description': 'Changed after claim'}
        store.upsert_resource(pending, now=40)
        checks['changed_source_invalidates_vector_and_old_publish'] = (index.current_ids([1], descriptor) == set()
            and index.publish(claim, vector, descriptor) == 'stale')
        import threading
        workers = 4 if require_private_cluster else 2
        barrier = threading.Barrier(workers)
        def write(number):
            owned = connect()
            current = make_store(owned, workflow_key=b'k' * 32)
            try:
                barrier.wait(timeout=5)
                return current.upsert_resource(records[0] | {'key': 'synthetic:concurrent', 'name': 'Concurrent ' + str(number)}, now=50 + number)
            finally: current.close(); owned.close()
        with ThreadPoolExecutor(max_workers=workers) as pool: ids = list(pool.map(write, range(workers)))
        checks['concurrent_same_key_single_persistent_identity'] = len(set(ids)) == 1
        with store.tx() as db: admin_auth.delete_session(db, token)
        try: access.workspace(ws['id'], staff)
        except WorkspaceDenied: checks['staff_session_revocation_is_current'] = True
        else: checks['staff_session_revocation_is_current'] = False
        coverage = store.coverage()
        engine.http.close(); http.close()
        store.close()
        checks['close_detaches_caller_owned_connection'] = pg.closed is False
        require(all(checks.values()), 'application contracts')
        return {'checks': checks, 'coverage': coverage, 'concurrent_workers': workers}
    finally:
        store.close(); pg.close(); sqlite._db.close()


def _worker():
    cluster = json.loads(sys.stdin.read(4096))
    root = Path(cluster['root'])
    require(root.parent == Path('/private/tmp') and root.name.startswith('a2a-adapter-pg-')
        and cluster['socket'] == str(root / 'socket'), 'owned cluster descriptor')
    require(not any(key.startswith('PG') and key not in ('PGPASSFILE', 'PGSERVICEFILE', 'PGSYSCONFDIR')
        for key in os.environ), 'clean libpq environment')
    driver = _driver()
    # In-process HTTP transports are the only allowed fixture providers. Native
    # libpq transport is checked separately before initialization below. Retain
    # attempted Python TCP socket creation even if application fallback catches
    # the exception, so silent Redis/model probes cannot count as isolation.
    import socket
    forbidden_network = []
    def deny_network(event, arguments):
        if event == 'socket.__new__' and arguments[1] in (socket.AF_INET, socket.AF_INET6):
            forbidden_network.append(True)
            raise AssertionError('Only controlled HTTP and native Unix transport are allowed.')
    sys.addaudithook(deny_network)
    # urllib3 otherwise opens a TCP socket for an import-time IPv6 capability
    # probe. Controlled HTTP fixtures need no network capability detection.
    ipv6 = socket.has_ipv6
    try:
        socket.has_ipv6 = False
        import urllib3
    finally: socket.has_ipv6 = ipv6
    from agent_market.infra.redis_hub import RedisHub
    offline_cache = RedisHub(); offline_cache._closed = True
    RedisHub._instance = offline_cache
    def connect():
        connection = driver.connect(host=cluster['socket'], hostaddr='', port=PORT,
            dbname='postgres', user='postgres', password='synthetic-unused-password',
            connect_timeout=3, passfile=str(root / 'no-password-file'), autocommit=True,
            sslmode='disable', gssencmode='disable')
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
                require(cursor.fetchone() == ('', None, None) and connection.info.host == cluster['socket'], 'owned Unix transport')
            return connection
        except BaseException:
            connection.close(); raise
    result = _contracts(connect)
    require(not forbidden_network, 'no unexpected Python TCP socket attempts')
    result['checks']['python_tcp_network_creation_blocked_and_unused'] = True
    print(json.dumps(result, sort_keys=True, allow_nan=False))


def rehearse():
    driver = _driver()
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable, '-B', '-c',
            'from scripts.rehearse_application_store_postgres import _worker; _worker()'],
            env=environment, input=json.dumps({'socket': cluster['socket'], 'root': cluster['root']}),
            text=True, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError('Synthetic application contract failed: ' + result.stderr[-5000:])
        result = json.loads(result.stdout)
    return {'profile': PROFILE, **result, 'synthetic': True, 'external_provider_calls': 0,
            'production_actions': 0, 'temporary_cluster_removed': True, 'production_cutover': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if not args.run: parser.error('--run is required')
    result = rehearse()
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__': raise SystemExit(main())
