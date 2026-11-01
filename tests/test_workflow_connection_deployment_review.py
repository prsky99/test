"""Independent review of connected deployment proof, privacy and recovery scope."""
import copy
import json
import os
from pathlib import Path

import pytest

from agent_market.workflow_connection_deployment import GRANT_NOTICE, SHARE_NOTICE, RUN_NOTICE
from tests.test_workflow_fallback import routing  # noqa: F401
from tests.test_workflow_typed_flow import typed_routing  # noqa: F401
from tests.test_workflow_publication import publication, published  # noqa: F401
from tests.test_workflow_runtime import wait


ORIGIN = 'https://connected-review.example'


def run_declaration(prepared):
    return {'proposal': copy.deepcopy(prepared['proposal']), 'signature': prepared['signature'],
            'sharing_authority': True, 'sharing_notice': SHARE_NOTICE,
            'run_authority': True, 'run_notice': RUN_NOTICE}


@pytest.fixture
def connected_deployment(publication):
    rt, owner, routed = publication
    release, tested, *_ = published(rt, owner)
    core = rt.connection_deployments
    prepared = core.prepare_admin(release['id'], {'allowed_origins': [ORIGIN], 'minute_limit': 10,
                                                'day_limit': 500, 'ttl_seconds': 1800}, owner)
    issued = core.issue(release['id'], {'proposal': prepared['proposal'], 'signature': prepared['signature'],
                                     'deployment_authority': True, 'deployment_notice': GRANT_NOTICE}, owner)
    routed[3].clear()
    return rt, owner, routed, release, tested, issued['deployment']


def test_same_title_changed_source_checkpoint_stops_deployed_docs_dispatch(connected_deployment, monkeypatch):
    rt, _, routed, _, _, deployment = connected_deployment
    original = rt.persistence.prepare
    changed = []

    def mutate_after_target_preparation(*args, **kwargs):
        value = original(*args, **kwargs)
        if args[3] == 'search-2' and not changed:
            changed.append(True)
            with rt.store.tx() as db:
                stored = db.execute("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'", (args[0],)).fetchone()
                cp = json.loads(stored[0])
                for result in (cp['record']['data'], cp['flow_output']):
                    result.get('structuredContent', result)['items'][0]['summary'] = 'A different source observation with the same title'
                db.execute("UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id='search-1'",
                           (json.dumps(cp), rt.authority.signature(cp), args[0]))
        return value

    monkeypatch.setattr(rt.persistence, 'prepare', mutate_after_target_preparation)
    job = rt.connection_deployments.execute_run(deployment['app_id'], run_declaration(rt.connection_deployments.prepare_run(deployment['app_id'], ORIGIN)), ORIGIN)
    assert wait(rt, job)['status'] == 'failed'
    assert changed and routed[3] == ['primary.example']


@pytest.mark.parametrize('column', ['actor', 'idempotency_key'])
def test_queued_deployment_metadata_cannot_be_rebound(connected_deployment, monkeypatch, column):
    rt, _, routed, _, _, deployment = connected_deployment
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    core = rt.connection_deployments
    job = core.execute_run(deployment['app_id'], run_declaration(core.prepare_run(deployment['app_id'], ORIGIN)), ORIGIN)
    with rt.store.tx() as db:
        if column == 'actor':
            db.execute("UPDATE workflow_runs SET actor='public-flow:forged' WHERE id=?", (job['run_id'],))
        else:
            db.execute("UPDATE workflow_runs SET idempotency_key='another-reviewed-nonce' WHERE id=?", (job['run_id'],))
    rt._execute(job['run_id'])
    assert rt.get(job['run_id'])['status'] == 'failed'
    assert not routed[3]


@pytest.mark.parametrize('leak', ['wrapper', 'citation'])
def test_connected_deployment_projects_only_safe_semantic_results(connected_deployment, monkeypatch, leak):
    rt, _, _, _, _, deployment = connected_deployment
    original = rt._call
    endpoints = []

    def inject(node, *args, **kwargs):
        value = original(node, *args, **kwargs)
        address = rt.store.resource(node['resource_id'])['url']
        endpoints.append(address)
        if leak == 'wrapper':
            value['content'] = [{'type': 'text', 'text': 'PRIVATE_PROVIDER_DIAGNOSTIC'}]
            value['private_debug_url'] = address
        else:
            row = value['structuredContent']['items'][0]
            row['url'] = address
            row['summary' if 'summary' in row else 'excerpt'] = 'Execution address ' + address
        return value

    monkeypatch.setattr(rt, '_call', inject)
    core = rt.connection_deployments
    job = core.execute_run(deployment['app_id'], run_declaration(core.prepare_run(deployment['app_id'], ORIGIN)), ORIGIN)
    assert wait(rt, job)['status'] == 'succeeded'
    result = core.read_run(deployment['app_id'], job['run_id'], job['run_key'], ORIGIN)
    encoded = json.dumps(result)
    assert all(address not in encoded for address in endpoints)
    assert 'PRIVATE_PROVIDER_DIAGNOSTIC' not in encoded and 'private_debug_url' not in encoded
    assert 'workflow_id' not in encoded and 'resource_id' not in encoded
    if leak == 'citation':
        for node in result['node_results']:
            assert 'url' not in node['data']['structuredContent']['items'][0]


def test_accepted_deployment_history_survives_invocation_pause_and_pruned_test(connected_deployment):
    from agent_market.execution_authority import controls, set_controls

    rt, owner, _, _, tested, deployment = connected_deployment
    core = rt.connection_deployments
    job = core.execute_run(deployment['app_id'], run_declaration(core.prepare_run(deployment['app_id'], ORIGIN)), ORIGIN)
    assert wait(rt, job)['status'] == 'succeeded'
    with rt.store.tx() as db:
        db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?', (tested['run_id'],))
        db.execute('UPDATE capability_evidence SET expires=0')
    current = controls(rt.store)
    set_controls(rt.store, {'invoke_enabled': False, 'workflow_enabled': False,
                           'delivery_enabled': current['delivery_enabled'], 'revision': current['revision']}, owner)
    assert core.read_run(deployment['app_id'], job['run_id'], job['run_key'], ORIGIN)['status'] == 'succeeded'
    assert core.cancel_run(deployment['app_id'], job['run_id'], job['run_key'], ORIGIN)['cancel_requested'] is True
    with pytest.raises(ValueError):
        core.prepare_run(deployment['app_id'], ORIGIN)


def test_late_queued_deployment_ticket_cannot_extend_its_authority(connected_deployment, monkeypatch):
    rt, _, routed, _, _, deployment = connected_deployment
    core = rt.connection_deployments
    prepared = core.prepare_run(deployment['app_id'], ORIGIN)
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    job = core.execute_run(deployment['app_id'], run_declaration(prepared), ORIGIN)
    authority = json.loads(rt.store.query('SELECT payload FROM workflow_run_authority WHERE run_id=?', (job['run_id'],))[0][0])
    assert authority['principal']['payload']['expires'] <= prepared['proposal']['expires']
    monkeypatch.setattr('agent_market.workflow_connection_deployment.time.time', lambda: prepared['proposal']['expires'] + 1)
    rt._execute(job['run_id'])
    assert rt.get(job['run_id'])['status'] == 'failed' and not routed[3]


def test_publication_withdrawal_requests_cancellation_of_dependent_deployment(connected_deployment, monkeypatch):
    rt, owner, routed, release, _, deployment = connected_deployment
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    core = rt.connection_deployments
    job = core.execute_run(deployment['app_id'], run_declaration(core.prepare_run(deployment['app_id'], ORIGIN)), ORIGIN)
    rt.publication.revoke(release['id'], release['revision'], owner)
    row = rt.store.query('SELECT cancel_requested FROM workflow_runs WHERE id=?', (job['run_id'],))[0]
    assert row['cancel_requested'] == 1
    rt._execute(job['run_id'])
    assert rt.get(job['run_id'])['status'] != 'succeeded'
    assert not routed[3]


def test_populated_connected_deployment_and_run_round_trip_postgres(connected_deployment, monkeypatch):
    from scripts.rehearse_workflow_postgres import rehearse,TABLES

    rt, _, _, _, _, deployment = connected_deployment
    core = rt.connection_deployments
    job = core.execute_run(deployment['app_id'], run_declaration(core.prepare_run(deployment['app_id'], ORIGIN)), ORIGIN)
    assert wait(rt, job)['status'] == 'succeeded'
    monkeypatch.setenv('PATH', '/opt/homebrew/opt/postgresql@14/bin:' + os.environ.get('PATH', ''))
    result = rehearse(rt.store._path)
    assert result['round_trip_equal'] and set(result['tables']) == set(TABLES)
    assert result['tables']['workflow_connection_deployments'] == 1
    assert result['tables']['workflow_run_authority'] >= 2
    assert result['tables']['workflow_execution_attempts'] >= 4
    Path('reports/advancement-connected-sdk-2026-10-18/postgres-connected-deployment.json').write_text(json.dumps(result, indent=2) + '\n')
