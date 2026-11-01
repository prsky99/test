"""Current collector Store parity on an owned, isolated PostgreSQL fixture.

The fixed worker reuses the application transport guard. No caller database,
provider, path or DSN is accepted. All HTTP responses and catalog rows are fake.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'application-collector-postgres-contracts-v1'


def require(value, label):
    if value is not True: raise AssertionError(label)


def _contracts(connect):
    import httpx
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.storage_adapter import open_store
    from agent_market.gateway.store import Store
    from agent_market.observation_guards import GuardError
    from agent_market.collector.health import HealthChecker
    pg = connect()
    native = open_store('postgresql', connection=pg, initialize=True, workflow_key=b'c' * 32)
    sqlite = Store()
    stores = (native, sqlite)
    checks = {}
    now = time.time()
    fields = ('health_status', 'next_check_at', 'cap_checked_at', 'auth_checked_at', 'auth_declared',
        'auth_scope', 'eval_at', 'eval_score', 'eval_grade', 'eval_security', 'eval_coverage', 'failing_since', 'consecutive_failures', 'trial_ok')
    sqlite_update = 'UPDATE resources SET health_status=?,next_check_at=?,cap_checked_at=?,auth_checked_at=?,auth_declared=?,auth_scope=?,eval_at=?,eval_score=?,eval_grade=?,eval_security=?,eval_coverage=?,failing_since=?,consecutive_failures=?,trial_ok=? WHERE id=?'
    pg_update = 'UPDATE resources SET health_status=%s,next_check_at=%s,cap_checked_at=%s,auth_checked_at=%s,auth_declared=%s,auth_scope=%s,eval_at=%s,eval_score=%s,eval_grade=%s,eval_security=%s,eval_coverage=%s,failing_since=%s,consecutive_failures=%s,trial_ok=%s WHERE id=%s'
    ids = []
    records = []
    def set_state(store, identity, **changes):
        current = store.resource(identity)
        values = tuple(changes.get(name, current[name]) for name in fields) + (identity,)
        with store.tx() as db:
            if store is native: store._execute(pg_update, values)
            else: db.execute(sqlite_update, values)
    def selected(method, *args, **kwargs):
        return [{row['id'] for row in getattr(store, method)(*args, **kwargs)} for store in stores]
    try:
        for index in range(28):
            kind = 'mcp' if index < 24 else 'a2a' if index < 26 else 'x402'
            record = {'key': 'collector:' + str(index), 'source': 'synthetic-collector', 'kind': kind,
                'url': 'https://host-' + str(index) + '.example/endpoint', 'name': 'Synthetic collector ' + str(index),
                'description': 'Public research source', 'category': 'research', 'networks': [], 'details': {}, 'price_usdc': 0}
            current_ids = [store.upsert_resource(record, now=100 + index) for store in stores]
            require(current_ids[0] == current_ids[1], 'collector identity parity')
            ids.append(current_ids[0]); records.append(record)
            for store in stores:
                set_state(store, ids[-1], health_status='healthy', next_check_at=now - index - 1,
                    cap_checked_at=now - index * 1000, auth_checked_at=now - index * 1000,
                    auth_declared=int(index % 2 == 0), auth_scope='connection',
                    eval_at=now - 100, eval_score=float(index), eval_grade='B', eval_security='pass', eval_coverage='full')
        for method, args, options in [
            ('due_for_check', (now, 100), {}), ('due_for_check', (now, 100), {'per_host': 1}),
            ('due_for_check', (now, 100), {'kind': 'mcp'}), ('due_for_check', (now, 100), {'kind': ('mcp', 'a2a')}),
            ('due_for_check', (now, 100), {'kind': 'x402'}),
            ('due_for_capability', (now, 5000, 100), {}), ('due_for_auth', (now, 5000, 100), {}),
            ('due_for_static_evaluation', (now, 10, 100), {})]:
            result = selected(method, *args, **options)
            require(result[0] == result[1], 'collector selection parity: ' + method)
        checks['current_collector_scheduling_filters_match_sqlite'] = True
        ordered = [row['id'] for row in native.due_for_check(now, 100)]
        require(ordered == [row['id'] for row in sqlite.due_for_check(now, 100)], 'oldest schedule ordering')
        checks['oldest_due_order_with_distinct_timestamps'] = True
        checks['score_percentile_and_empty_statistics_parity'] = all(
            native.score_percentile(value) == sqlite.score_percentile(value) for value in (0, 12, 99))
        for store in stores:
            store.postpone(ids[:3], now + 3600)
            set_state(store, ids[4], health_status='retired', next_check_at=now - 1, failing_since=now - 10 * 86400)
            set_state(store, ids[5], health_status='retired', next_check_at=now - 2, failing_since=now - 50 * 86400)
            set_state(store, ids[6], health_status='retired', next_check_at=None, failing_since=now - 100 * 86400)
        require(selected('due_for_scavenge', now)[0] == selected('due_for_scavenge', now)[1], 'scavenge due parity')
        checks['postpone_and_retired_phase_filters'] = native.scavenger_stats() == sqlite.scavenger_stats()
        from agent_market.gateway import store as store_module
        original = store_module.random.uniform
        store_module.random.uniform = lambda *_args: 1.0
        try:
            for store in stores:
                for identity in ids[4:7]: store.record_scavenge_failure(identity, now, 'Synthetic failure')
        finally: store_module.random.uniform = original
        checks['scavenge_backoff_and_tombstone_parity'] = all(
            (native.resource(identity)['next_check_at'], native.resource(identity)['consecutive_failures']) ==
            (sqlite.resource(identity)['next_check_at'], sqlite.resource(identity)['consecutive_failures']) for identity in ids[4:7])
        checks['collector_statistics_and_source_evaluation_groups_match'] = native.collector_stats() == sqlite.collector_stats()
        from agent_market.concierge.front import get_front_explore
        for store in stores:
            set_state(store, ids[9], trial_ok=1)
            set_state(store, ids[23], eval_security='quarantine')
            set_state(store, ids[22], health_status='retired')
            with store.tx() as db:
                if store is native: store._execute('UPDATE resources SET active=0 WHERE id=%s', (ids[21],))
                else: db.execute('UPDATE resources SET active=0 WHERE id=?', (ids[21],))
        # A historical trial flag is deliberately insufficient for verified
        # Explore. Seed current, complete-schema evidence only in these owned
        # synthetic database-state fixtures, never as provider verification.
        checks['verified_explore_refuses_legacy_trial_without_execution_proof'] = all(
            not get_front_explore(store, 'research', 'mcp', None, True, False, 10)['items'] for store in stores)
        from agent_market.capability_registry import Registry
        from agent_market.collector import usage
        schema = {'name': 'search', 'description': 'Search synthetic research and collector sources.',
            'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                            'required': ['query'], 'additionalProperties': False},
            'outputSchema': {'type': 'object', 'properties': {'result': {'type': 'string'}},
                             'required': ['result'], 'additionalProperties': False},
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}}
        for store in stores:
            for identity in (ids[9], *ids[20:24]):
                before_survey = {name: store.resource(identity)[name] for name in fields}
                tools = usage.compact_tools([schema])
                store.record_usage(identity, tools, usage.tools_hash(tools), {}, None, None, full_tools=[schema])
                # Survey invalidation is real. Restore only the explicitly
                # controlled fixture assessment before adding its fixture proof.
                set_state(store, identity, **before_survey)
                registry = Registry(store); version = registry.current(identity)
                observed = time.time()
                registry.record(version, scope='execution', outcome='succeeded', started=observed,
                    finished=observed, dataset='synthetic-native-collector-v1')
        for query, verified, no_auth in [('research', True, False), ('collector', False, True)]:
            projected = [get_front_explore(store, query, 'mcp', None, verified, no_auth, 10) for store in stores]
            diagnostic = json.dumps({'query': query, 'verified': verified,
                'ids': [[row['id'] for row in result['items']] for result in projected],
                'totals': [result['total'] for result in projected],
                'readiness':[Registry(store).projection(store.resource(ids[9])).get('connection_readiness')for store in stores]}, sort_keys=True, separators=(',', ':'))
            require([row['id'] for row in projected[0]['items']] == [row['id'] for row in projected[1]['items']]
                and projected[0]['total'] == projected[1]['total'] and bool(projected[0]['items']),
                'weighted public FTS parity: ' + diagnostic)
            require(projected[0]['items'][0]['id'] == ids[9]
                and not set(ids[21:24]) & {row['id'] for row in projected[0]['items']}, 'current visibility and trial rank')
        checks['current_public_fts_quality_and_trial_weighting_match_sqlite'] = True
        query = "research'); DROP TABLE resources; --"
        hostile = [get_front_explore(store, query, 'mcp', 'research', True, False, 10) for store in stores]
        checks['hostile_public_query_remains_bound_and_catalog_intact'] = (
            [row['id'] for row in hostile[0]['items']] == [row['id'] for row in hostile[1]['items']]
            and native.resource(ids[0])['name'] == sqlite.resource(ids[0])['name'])
        # Positive in-use union includes active needs and pending offers, while
        # unrelated terminal rows do not become a scheduling priority.
        need_sqlite = "INSERT INTO needs(need_id,client,task,category,networks,kinds,status,current_resource,created,updated) VALUES('synthetic-need','fixture','research','research','[]','[]','active',?,0,0)"
        need_pg = "INSERT INTO needs(need_id,client,task,category,networks,kinds,status,current_resource,created,updated) VALUES('synthetic-need','fixture','research','research','[]','[]','active',%s,0,0)"
        offer_sqlite = "INSERT INTO offers(offer_id,need_id,resource_id,score,teaser,fee,free,status,created) VALUES('synthetic-offer','synthetic-need',?,1,'fixture',0,1,'pending',0)"
        offer_pg = "INSERT INTO offers(offer_id,need_id,resource_id,score,teaser,fee,free,status,created) VALUES('synthetic-offer','synthetic-need',%s,1,'fixture',0,1,'pending',0)"
        for store in stores:
            with store.tx() as db:
                if store is native:
                    store._execute(need_pg, (ids[0],)); store._execute(offer_pg, (ids[1],))
                else:
                    db.execute(need_sqlite, (ids[0],)); db.execute(offer_sqlite, (ids[1],))
        checks['current_active_need_and_pending_offer_priority_union'] = native.in_use_ids() == sqlite.in_use_ids() == set(ids[:2])
        # A projection built by an aborted writer must not survive an epoch ABA.
        def lexical_count(text):
            with native.tx(readonly=True):
                return native._fts().execute('SELECT COUNT(*) FROM documents WHERE documents MATCH ?', (text,)).fetchone()[0]
        for mode in ('exception', 'poison', 'direct'):
            stale, current = 'abortedcachetoken' + mode, 'committedcachetoken' + mode
            if mode == 'direct':
                native._db.execute('BEGIN IMMEDIATE')
                native.upsert_resource(records[0] | {'name': stale}, now=501)
                require(lexical_count(stale) == 1, 'uncommitted direct FTS fixture')
                old_epoch = native._search_epoch
                native._db.rollback()
            else:
                try:
                    with native.tx():
                        native.upsert_resource(records[0] | {'name': stale}, now=501)
                        require(lexical_count(stale) == 1, 'uncommitted FTS fixture')
                        old_epoch = native._search_epoch
                        if mode == 'poison':
                            try: native.query('SELECT synthetic_unregistered_cache_statement')
                            except ApplicationStoreError: pass
                        else: raise RuntimeError('Synthetic writer rollback')
                except (RuntimeError, ApplicationStoreError): pass
            native.upsert_resource(records[0] | {'name': current}, now=501)
            sqlite.upsert_resource(records[0] | {'name': current}, now=501)
            require(lexical_count(current) == 1 and lexical_count(stale) == 0
                and old_epoch == native._search_epoch, 'rollback FTS epoch reuse')
            checks['fts_rollback_epoch_aba_blocked_' + mode] = True
        # SQL values remain data and invalid input cannot commit a prefix.
        before = native.resource(ids[0])['next_check_at']
        try: native.postpone([ids[0], 'not-an-id'], now)
        except ApplicationStoreError: pass
        else: raise AssertionError('invalid postpone admitted')
        checks['invalid_postpone_has_no_partial_writes'] = native.resource(ids[0])['next_check_at'] == before
        require(native.due_for_check(now, 100, kind="mcp' OR 1=1 --") == [], 'kind parameter injection')
        checks['kind_selector_is_bound_not_sql'] = True
        # A source rebind after snapshot selection blocks its observation bundle.
        snapshot = native.resource(ids[7]); token = native.observation_guard(ids[7], 'health', expected_resource=snapshot)
        native.upsert_resource(records[7] | {'url': 'https://replacement.example/endpoint'}, now=500)
        sqlite.upsert_resource(records[7] | {'url': 'https://replacement.example/endpoint'}, now=500)
        try:
            with native.observation_transaction(token): native.record_health(ids[7], 'healthy', 200, 1, None, now + 3600)
        except GuardError: checks['rebinding_rejects_stale_observation_bundle'] = True
        else: checks['rebinding_rejects_stale_observation_bundle'] = False
        # Two current native connections reserve one owner sequence; only the
        # latest reservation can consume that sequence, irrespective of threads.
        other_connection = connect()
        other = open_store('postgresql', connection=other_connection, workflow_key=b'c' * 32)
        try:
            import threading
            barrier = threading.Barrier(2)
            def reserve(current):
                snapshot = current.resource(ids[8]); barrier.wait(timeout=5)
                return current.observation_guard(ids[8], 'health', expected_resource=snapshot)
            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = list(pool.map(reserve, (native, other)))
            outcomes = []
            for current, guard in ((native, first), (other, second)):
                try:
                    with current.observation_transaction(guard): current.record_health(ids[8], 'healthy', 200, 1, None, now + 3600)
                    outcomes.append(True)
                except GuardError: outcomes.append(False)
            checks['native_observation_owner_latest_reservation_only'] = outcomes == [first.sequence > second.sequence, second.sequence > first.sequence]
        finally: other.close(); other_connection.close()
        # Current collector HTTP path, without a network socket or provider.
        http_record = {'key': 'collector:http', 'source': 'synthetic-http', 'kind': 'mcp',
            'url': 'https://controlled.example/mcp', 'name': 'Controlled MCP', 'description': 'Research source',
            'category': 'research', 'networks': [], 'details': {}}
        rid = native.upsert_resource(http_record); sqlite.upsert_resource(http_record)
        from tests.test_collector_observation_guards import mcp_response
        http = httpx.Client(transport=httpx.MockTransport(mcp_response))
        checker = HealthChecker(native, http=http, allow_private=True, workers=1, per_host_delay=0)
        result = checker.check_and_record(native.resource(rid))
        checks['current_health_checker_controlled_http_commits_guarded_bundle'] = result['accepted'] and native.resource(rid)['health_status'] == 'healthy'
        native.postpone(ids, now + 3600); set_state(native, rid, next_check_at=None)
        due_result = checker.run_due(10, kind='mcp')
        checks['current_health_checker_batch_lease_and_host_counts'] = due_result['checked'] == due_result['accepted'] == 1
        http.close()
        # Static x402 evaluation does not perform a provider or payment call.
        for store in stores:
            for identity in ids[26:]: set_state(store, identity, eval_at=None)
        checks['x402_static_evaluation_generation_guard_parity'] = native.evaluate_x402_batch() == sqlite.evaluate_x402_batch() == 2
        # Native active-state trigger removes queued/published vector authority.
        require(native.deactivate_unseen('synthetic-collector', 200) == sqlite.deactivate_unseen('synthetic-collector', 200), 'deactivation count parity')
        checks['deactivate_unseen_count_and_visibility_match'] = native.resource_counts() == sqlite.resource_counts()
        # More than the generic row cap: the native consumer projects upper
        # medians in SQL rather than transferring the entire price distribution.
        priced = [{'id': 100000 + index, 'kind': 'mcp', 'price': index, 'active': 1, 'status': 'healthy'}
            for index in range(1, 2003)]
        priced += [{'id': 103000 + index, 'kind': kind, 'price': price, 'active': 1, 'status': 'healthy'}
            for index, (kind, price) in enumerate([('a2a', 3), ('a2a', 5), ('a2a', 9), ('x402', 2), ('x402', 8)])]
        priced += [{'id': 104000, 'kind': 'mcp', 'price': 999999, 'active': 0, 'status': 'healthy'},
            {'id': 104001, 'kind': 'mcp', 'price': 999999, 'active': 1, 'status': 'retired'}]
        with native.tx():
            native._execute('''INSERT INTO resources(id,key,source,kind,url,name,description,category,networks,
                price_usdc,details,first_seen,last_seen,active,health_status,host)
                SELECT (value->>'id')::bigint,'synthetic-price:'||(value->>'id'),'synthetic-median',value->>'kind',
                'https://median.example/'||(value->>'id'),'Synthetic price','Research source','research','',
                (value->>'price')::bigint,'{}',1,1,(value->>'active')::bigint,value->>'status','median.example'
                FROM json_array_elements(%s::json)''', (json.dumps(priced),))
        with sqlite.tx() as db:
            db.executemany('''INSERT INTO resources(id,key,source,kind,url,name,description,category,networks,
                price_usdc,details,first_seen,last_seen,active,health_status,host)
                VALUES(?,?,'synthetic-median',?,?,'Synthetic price','Research source','research','',?,'{}',1,1,?,?, 'median.example')''',
                [(row['id'], 'synthetic-price:' + str(row['id']), row['kind'], 'https://median.example/' + str(row['id']),
                  row['price'], row['active'], row['status']) for row in priced])
        from agent_market.concierge.front import get_front_insights
        insights = [get_front_insights(store) for store in stores]
        checks['native_insights_large_catalog_upper_median_matches_sqlite'] = all(
            insights[0]['kinds'][kind]['stats']['median_price'] == insights[1]['kinds'][kind]['stats']['median_price'] == expected
            for kind, expected in (('mcp', 1002), ('a2a', 5), ('x402', 8)))
        # A provider can legally encode NUL inside JSON strings. Keep that
        # evidence escaped in JSON, but never pass NUL to a PostgreSQL text index.
        from agent_market.collector.capabilities import CapabilityProber
        for store in stores:
            identity = store.upsert_resource({'key': 'synthetic:nul-survey', 'source': 'synthetic', 'kind': 'mcp',
                'url': 'https://nul-survey.example/mcp', 'name': 'NUL survey fixture',
                'description': 'Public documentation', 'category': 'research', 'networks': [], 'details': {}, 'price_usdc': 0})
            store.record_health(identity, 'healthy', 200, 1, None, now + 3600)
            original_due = store.due_for_capability
            store.due_for_capability = lambda *args, store=store, identity=identity: [store.resource(identity)]
            requests = []
            dirty_schema = dict(schema, description='Search public\0documentation', tags=['reference\0lookup'])
            def response(request):
                method = json.loads(request.content)['method']; requests.append(method)
                require(method in ('server/discover', 'tools/list'), 'metadata-only survey')
                result = ({'protocolVersion': '2025-06-18', 'serverInfo': {'name': 'Fixture', 'version': '1'}}
                          if method == 'server/discover' else {'tools': [dirty_schema]})
                return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1, 'result': result})
            try:
                with httpx.Client(transport=httpx.MockTransport(response)) as http:
                    survey = CapabilityProber(store, http=http, allow_private=True, trials=False, per_host_delay=0).run_due()
                row = store.resource(identity)
                require(survey['accepted'] == survey['ok'] == 1 and not survey.get('record_error'), 'NUL survey commits')
                require(json.loads(row['usage_full_tools'])[0]['description'] == dirty_schema['description'], 'original evidence preserved')
                require(bool(row['cap_checked_at']) and bool(row['eval_at']), 'whole capability bundle commits')
                from agent_market.gateway.store import extract_tool_search_text
                require('\0' not in extract_tool_search_text(row['usage_tools']), 'safe derived search text')
                require('tools/call' not in requests, 'no tool execution')
            finally:
                store.due_for_capability = original_due
        checks['nul_provider_metadata_commits_complete_survey_without_changing_evidence'] = True
        require(all(checks.values()), 'collector contracts')
        return {'checks': checks, 'coverage': native.coverage()}
    finally: native.close(); pg.close(); sqlite._db.close()


def _worker():
    from scripts import rehearse_application_store_postgres as application
    application._contracts = _contracts
    application._worker()


def rehearse():
    driver = _driver()
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable, '-B', '-c', 'from scripts.rehearse_application_collector_postgres import _worker; _worker()'],
            env=environment, input=json.dumps({'socket': cluster['socket'], 'root': cluster['root']}),
            text=True, capture_output=True, timeout=120)
        if result.returncode: raise RuntimeError('Synthetic collector contract failed: ' + result.stderr[-5000:])
        result = json.loads(result.stdout)
    return {'profile': PROFILE, **result, 'synthetic': True, 'provider_calls': 0, 'production_actions': 0,
        'temporary_cluster_removed': True, 'full_application_ready': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if not args.run: parser.error('--run is required')
    print(json.dumps(rehearse(), sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__': raise SystemExit(main())
