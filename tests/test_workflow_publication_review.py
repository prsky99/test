"""Independent isolated reviews of public release authority and projection."""
import json
import os
from pathlib import Path
import sqlite3

import pytest

from tests.test_workflow_fallback import routing  # noqa: F401
from tests.test_workflow_typed_flow import typed_routing  # noqa: F401
from tests.test_workflow_publication import publication, published, declaration, candidate  # noqa: F401
from tests.test_workflow_runtime import wait


def test_public_status_cannot_forward_private_provider_wrapper_fields(publication, monkeypatch):
    rt, owner, routing_data = publication
    release, *_ = published(rt, owner)
    original = rt._call

    def wrapped(*args, **kwargs):
        value = original(*args, **kwargs)
        return {**value, 'private_debug_url': 'https://primary.example/private-provider-endpoint',
                'content': [{'type': 'text', 'text': 'PROVIDER_INTERNAL_DIAGNOSTIC'}]}

    monkeypatch.setattr(rt, '_call', wrapped)
    prepared = rt.publication.prepare_run(release['id'])
    job = rt.publication.execute_run(release['id'], declaration(prepared))
    assert wait(rt, job)['status'] == 'succeeded'
    status = rt.publication.read_run(release['id'], job['run_id'], job['run_key'])
    encoded = json.dumps(status)
    for forbidden in ('private_debug_url', 'private-provider-endpoint', 'PROVIDER_INTERNAL_DIAGNOSTIC',
                      'resource_id', 'definition_hash', 'workflow_id', 'correlation_id'):
        assert forbidden not in encoded
    assert len(routing_data[3]) == 4


def test_provider_connection_address_cannot_be_presented_as_a_source_citation(publication, monkeypatch):
    rt, owner, _ = publication
    release, *_ = published(rt, owner)
    original = rt._call
    addresses = []

    def endpoint_as_source(node, *args, **kwargs):
        value = original(node, *args, **kwargs)
        address = rt.store.resource(node['resource_id'])['url']
        addresses.append(address)
        item = value['structuredContent']['items'][0]
        item['url'] = address
        item['summary' if 'summary' in item else 'excerpt'] = 'Connection address: ' + address
        return value

    monkeypatch.setattr(rt, '_call', endpoint_as_source)
    job = rt.publication.execute_run(release['id'], declaration(rt.publication.prepare_run(release['id'])))
    assert wait(rt, job)['status'] == 'succeeded'
    status = rt.publication.read_run(release['id'], job['run_id'], job['run_key'])
    encoded = json.dumps(status)
    assert all(address not in encoded for address in addresses)
    for node in status['node_results']:
        assert 'url' not in node['data']['structuredContent']['items'][0]


def test_historical_test_expiry_is_checked_at_its_original_admission(publication):
    rt, owner, _ = publication
    prepared = candidate(rt, owner)
    tested = wait(rt, rt.publication.test(declaration(prepared, test=True), owner))
    row = rt.store.query('SELECT created FROM workflow_runs WHERE id=?', (tested['run_id'],))[0]
    proof = rt.store.query('SELECT payload FROM workflow_run_authority WHERE run_id=?', (tested['run_id'],))[0]
    value = json.loads(proof['payload'])
    value['principal']['payload']['expires'] = row['created'] - 1
    value['principal']['signature'] = rt.authority.signature(value['principal']['payload'])
    with rt.store.tx() as db:
        db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',
                   (json.dumps(value), rt.authority.signature(value), tested['run_id']))
    with pytest.raises(ValueError):
        rt.publication.publication_candidate({'run_id': tested['run_id'], 'ttl_seconds': 3600}, owner)
    assert not rt.store.query('SELECT id FROM workflow_publication_grants')


@pytest.mark.parametrize('column', ['actor', 'idempotency_key'])
def test_worker_refuses_changed_durable_public_admission_metadata(publication, monkeypatch, column):
    rt, owner, routing_data = publication
    release, *_ = published(rt, owner)
    routing_data[3].clear()
    prepared = rt.publication.prepare_run(release['id'])
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    job = rt.publication.execute_run(release['id'], declaration(prepared))
    with rt.store.tx() as db:
        if column == 'actor':
            db.execute('UPDATE workflow_runs SET actor=? WHERE id=?', ('another-actor', job['run_id']))
        else:
            db.execute('UPDATE workflow_runs SET idempotency_key=? WHERE id=?', ('another-nonce', job['run_id']))
    rt._execute(job['run_id'])
    assert rt.get(job['run_id'])['status'] == 'failed'
    assert not routing_data[3]


def test_same_title_checkpoint_change_cannot_reuse_old_derived_provenance(publication, monkeypatch):
    rt, owner, routing_data = publication
    release, *_ = published(rt, owner)
    routing_data[3].clear()
    original = rt.persistence.prepare
    changed = []

    def change_source_after_docs_preparation(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[3] == 'search-2' and not changed:
            changed.append(True)
            with rt.store.tx() as db:
                row = db.execute("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'", (args[0],)).fetchone()
                checkpoint = json.loads(row[0])
                for value in (checkpoint['record']['data'], checkpoint['flow_output']):
                    value.get('structuredContent', value)['items'][0]['summary'] = 'A different retained source summary'
                db.execute("UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id='search-1'",
                           (json.dumps(checkpoint), rt.authority.signature(checkpoint), args[0]))
        return result

    monkeypatch.setattr(rt.persistence, 'prepare', change_source_after_docs_preparation)
    job = rt.publication.execute_run(release['id'], declaration(rt.publication.prepare_run(release['id'])))
    assert wait(rt, job)['status'] == 'failed'
    assert changed and routing_data[3] == ['primary.example']


def test_restore_copy_revokes_publication_without_altering_the_original(publication):
    from agent_market.workflow_backup import quarantine

    rt, owner, _ = publication
    release, *_ = published(rt, owner)
    copy_db = sqlite3.connect(':memory:')
    try:
        with rt.store._lock:
            rt.store._db.backup(copy_db)
        with copy_db:
            quarantine(copy_db)
        row = copy_db.execute('SELECT active,revision,payload FROM workflow_publication_grants').fetchone()
        assert row[0] == 0 and row[1] == release['revision'] + 1
        assert json.loads(row[2])['revision'] == release['revision']
        assert copy_db.execute('SELECT invoke_enabled,workflow_enabled,delivery_enabled FROM execution_controls').fetchone() == (0, 0, 0)
    finally:
        copy_db.close()
    assert rt.publication.metadata(release['id'])['revision'] == release['revision']


def test_populated_publication_and_public_run_round_trip_postgres_state(publication, monkeypatch):
    from scripts.rehearse_workflow_postgres import rehearse,TABLES

    rt, owner, _ = publication
    release, *_ = published(rt, owner)
    job = rt.publication.execute_run(release['id'], declaration(rt.publication.prepare_run(release['id'])))
    assert wait(rt, job)['status'] == 'succeeded'
    monkeypatch.setenv('PATH', '/opt/homebrew/opt/postgresql@14/bin:' + os.environ.get('PATH', ''))
    result = rehearse(rt.store._path)
    assert result['round_trip_equal'] and set(result['tables']) == set(TABLES)
    assert result['tables']['workflow_publication_grants'] == 1
    assert result['tables']['workflow_run_authority'] >= 2
    assert result['tables']['workflow_execution_attempts'] >= 4
    Path('reports/advancement-public-release-2026-10-18/postgres-publication.json').write_text(json.dumps(result, indent=2) + '\n')
