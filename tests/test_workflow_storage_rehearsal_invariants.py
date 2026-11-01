"""Synthetic retention/recovery invariants, not operating throughput or quality."""
import copy
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.task_updates import TaskUpdates
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.admin_auth import verify_password
from agent_market.workflow_backup import backup, restore
from agent_market.workflow_storage_fixtures import synthetic_fixture, ORIGIN
from agent_market.workflows import WorkflowRuntime

REPORT = Path('reports/advancement-storage-rehearsal-2026-10-18')


@pytest.fixture
def fixture(tmp_path):
    with synthetic_fixture(tmp_path / 'synthetic', completed=4) as value:
        yield value


def compact(fixture):
    fixture.prepare_idle(); baseline = fixture.capture()
    result = fixture.runtime.maintenance.run(apply=True, now=fixture.retention_now)
    assert 1 <= result['bodies_compacted'] <= 20
    metadata = fixture.runtime.maintenance.run(apply=True, limit=1, now=fixture.retention_now)
    assert metadata['metadata_pruned'] == 1
    return baseline, result


def restored(fixture, tmp_path):
    compact(fixture); fixture.prepare_restore()
    backup(fixture.path, tmp_path / 'backup')
    target = tmp_path / 'restored.sqlite3'
    restore(tmp_path / 'backup', target)
    return target, json.loads(Path(str(target) + '.restored-inventory.json').read_text())


def test_fixture_uses_explicit_synthetic_key_and_transport_without_operating_initializer(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs): raise AssertionError('Operating initialization or background work is forbidden.')
    monkeypatch.setattr(TaskUpdates, '_load_key', forbidden)
    monkeypatch.setattr(WorkflowRuntime, '__init__', forbidden)
    monkeypatch.setattr(WorkflowRuntime, 'launch', forbidden)
    monkeypatch.setattr(WorkflowRuntime, 'run_due', forbidden)
    with synthetic_fixture(tmp_path / 'synthetic', completed=2) as value:
        summary = value.safe_summary()
        assert summary['valid'] is True and summary['synthetic'] is True
        assert not any(summary['claims'].values())
        assert summary['fixture_effects']['provider_network_calls'] == summary['fixture_effects']['worker_starts'] == 0
        assert summary['counts']['sdk12_grants'] == summary['counts']['sdk13_grants'] == summary['counts']['publication_grants'] == 2
        assert summary['counts']['automation_grants'] == 3 and summary['counts']['product_approvals'] == 1
        key = Path(str(value.path) + '.updates-key')
        assert key.read_bytes() == value.key and key.stat().st_mode & 0o077 == 0
        assert value.directory.stat().st_mode & 0o077 == 0
        encoded = json.dumps(summary)
        for secret in (str(value.directory), value.refs['sdk12']['publish_key'], value.refs['sdk13']['publish_key'], value.refs['session']):
            assert secret not in encoded
        assert value.runtime.publication.proof(value.refs['publication_test'], str(value.refs['owner']))


def test_fixed_seed_repeats_scenario_layout_but_does_not_claim_byte_identical_grants(tmp_path):
    with synthetic_fixture(tmp_path / 'first', completed=2, seed=7) as first:
        first_counts = first.safe_summary()['counts']; title = first.transport.title
    with synthetic_fixture(tmp_path / 'second', completed=2, seed=7) as second:
        assert second.safe_summary()['counts'] == first_counts and second.transport.title == title


def test_fixture_admin_bootstrap_never_reads_operating_configuration(tmp_path, monkeypatch):
    original = os.environ.get
    def refuse_operating_credentials(key, default=None):
        if key in ('ADMIN_BOOTSTRAP_PASSWORD', 'DEPLOYMENT_MODE'):
            raise AssertionError('An operating bootstrap value was requested.')
        return original(key, default)
    monkeypatch.setattr(os.environ, 'get', refuse_operating_credentials)
    with synthetic_fixture(tmp_path / 'synthetic', completed=2) as value:
        row = value.store.query("SELECT password_hash,salt FROM admin_users WHERE username='sadmin'")[0]
        assert verify_password('Synthetic-storage-fixture-password-42', row['salt'], row['password_hash'])
        assert value.safe_summary()['valid'] is True


@pytest.mark.parametrize('options', [{'seed': True}, {'seed': -1}, {'seed': 2**31}, {'completed': True}, {'completed': 1}, {'completed': 41}])
def test_fixture_bounds_fail_before_path_creation(tmp_path, options):
    target = tmp_path / 'uncreated'
    with pytest.raises(ValueError): synthetic_fixture(target, **options)
    assert not target.exists()


def test_fixture_refuses_existing_relative_and_symlink_targets_without_modification(tmp_path):
    existing = tmp_path / 'existing'; existing.mkdir(); marker = existing / 'keep'; marker.write_bytes(b'unchanged')
    symlink = tmp_path / 'link'; symlink.symlink_to(existing, target_is_directory=True)
    for target in (existing, symlink, Path('relative-fixture')):
        with pytest.raises(ValueError): synthetic_fixture(target)
    assert marker.read_bytes() == b'unchanged' and list(existing.iterdir()) == [marker]


def test_operating_key_presence_is_refused_without_reading_or_copying_value(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_UPDATES_KEY', 'synthetic-marker-that-must-not-be-read-or-echoed')
    target = tmp_path / 'uncreated'
    with pytest.raises(ValueError) as error: synthetic_fixture(target)
    assert 'synthetic-marker' not in str(error.value) and not target.exists()


def test_real_claim_fence_and_dispatched_recovery_are_separate_from_load_measurement(fixture):
    calls = len(fixture.transport.calls)
    result = fixture.exercise_durable()
    assert result['scope'] == 'claim_fence_recovery_only' and result['recovered_runs'] == 1
    assert len(result['invariants']) == 5 and all(value is True for value in result['invariants'].values())
    assert len(fixture.transport.calls) == calls
    assert fixture.store.query('SELECT status FROM workflow_runs WHERE id=?', (fixture.refs['active_run'],))[0][0] == 'queued'


def test_active_work_blocks_retention_and_preview_is_read_only(fixture):
    baseline = fixture.capture()
    preview = fixture.runtime.maintenance.run(now=fixture.retention_now)
    applied = fixture.runtime.maintenance.run(apply=True, now=fixture.retention_now)
    assert preview['busy'] and applied['busy'] and applied['bodies_compacted'] == 0
    assert fixture.capture() == baseline and not fixture.store.query('SELECT 1 FROM workflow_run_archives')


def test_idle_retention_holds_uncertainty_tampering_deliveries_and_denies_proof_reuse(fixture):
    fixture.exercise_durable()
    baseline, applied = compact(fixture)
    checked = fixture.verify_compaction(baseline)
    assert len(checked) == 15 and all(value is True for value in checked.values()), checked
    assert applied['held_invalid_evidence'] == 1 and applied['metadata_pruned'] == 0
    assert all(baseline['tombstones'].values())
    again = fixture.runtime.maintenance.run(apply=True, limit=1, now=fixture.retention_now)
    assert again['metadata_pruned'] >= 1
    assert fixture.capture()['replay'] == baseline['replay']
    assert fixture.capture()['attempts'] == baseline['attempts']
    assert fixture.capture()['unknown'] == baseline['unknown']


def test_verifiers_are_nonvacuous_and_detect_a_corrupted_signed_archive(fixture):
    fixture.prepare_idle(); before = fixture.capture()
    assert fixture.verify_compaction(before)['archive_signatures_valid'] is False
    fixture.runtime.maintenance.run(apply=True, now=fixture.retention_now)
    with fixture.store.tx() as db: db.execute("UPDATE workflow_run_archives SET signature='corrupt' WHERE run_id=?", (fixture.refs['literal_proof'],))
    assert fixture.verify_compaction(before)['archive_signatures_valid'] is False


def test_restore_quarantines_new_unfinished_work_and_all_purpose_keys_without_reactivation(fixture, tmp_path):
    target, inventory = restored(fixture, tmp_path)
    result = fixture.verify_restore(target, inventory)
    assert len(result) == 18 and all(value is True for value in result.values()), result
    with sqlite3.connect(target) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        for table in ('workflow_deployment_grants', 'workflow_publication_grants', 'workflow_connection_deployments', 'workflow_connection_automation'):
            assert inventory['items'][table]['count'] >= 1
            assert db.execute('SELECT COUNT(*) FROM ' + table + ' WHERE active=1').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM workflow_runs WHERE execution_outcome=\'unknown\'').fetchone()[0] >= 3
        assert db.execute('SELECT COUNT(*) FROM workflow_connection_automation_admissions').fetchone()[0] == 1
    rendered = json.dumps(inventory)
    for forbidden in ('synthetic-sealed-value', 'signature', 'principal', 'payload', 'https://', 'wfpk_', 'cpk_'):
        assert forbidden not in rendered


def test_restore_verifier_detects_reactivation_revision_regression_and_inventory_secret(fixture, tmp_path):
    target, inventory = restored(fixture, tmp_path)
    with sqlite3.connect(target) as db:
        db.execute('UPDATE workflow_connection_deployments SET active=1,revision=revision-1')
    result = fixture.verify_restore(target, inventory)
    assert result['all_purpose_grants_inactive'] is False and result['all_grant_revisions_advanced'] is False
    copied = copy.deepcopy(inventory); copied['injected'] = fixture.refs['sdk12']['publish_key']
    assert fixture.verify_restore(target, copied)['private_inventory_bounded_without_secrets'] is False


@pytest.fixture
def maintenance_api(fixture):
    front = SimpleNamespace(store=fixture.store, proxy=fixture.runtime.proxy, courier=SimpleNamespace())
    app = FastAPI(); app.include_router(dashboard_router(fixture.store, str(fixture.path), 'synthetic-admin-token', None, front=front))
    with TestClient(app, base_url='https://admin.example') as client:
        yield fixture, client


def headers(fixture, *, legacy=False):
    return {'X-Dashboard': '1', 'Authorization': 'Bearer ' + ('synthetic-admin-token' if legacy else fixture.refs['session'])}


def test_maintenance_api_preserves_role_csrf_and_explicit_consent_boundaries(maintenance_api):
    value, client = maintenance_api; path = '/admin/api/workflows/maintenance'; calls = len(value.transport.calls)
    assert client.post(path, json={'authority': True, 'notice': 'workflow-retention-v1'}).status_code in (401, 403)
    for cross in ({'Origin': 'https://attacker.example'}, {'Sec-Fetch-Site': 'cross-site'}):
        response = client.post(path, headers=headers(value) | cross, json={'authority': True, 'notice': 'workflow-retention-v1'})
        assert response.status_code == 403
    assert client.post(path, headers=headers(value), json={}).status_code == 409
    preview = client.get(path, headers=headers(value)); assert preview.status_code == 200 and preview.headers['cache-control'] == 'no-store'
    accepted = client.post(path, headers=headers(value), json={'authority': True, 'notice': 'workflow-retention-v1'})
    assert accepted.status_code == 200 and accepted.json()['busy'] is True and accepted.json()['bodies_compacted'] == 0
    assert len(value.transport.calls) == calls


def test_configured_system_token_no_longer_authorizes_maintenance_writes(maintenance_api):
    value, client = maintenance_api; value.prepare_idle(); calls = len(value.transport.calls)
    response = client.post('/admin/api/workflows/maintenance', headers=headers(value, legacy=True),
                           json={'authority': True, 'notice': 'workflow-retention-v1'})
    # The shared machine token reads aggregate monitoring only; writes need an individual session.
    assert response.status_code == 401 and len(value.transport.calls) == calls


@pytest.mark.parametrize('change', ["role='operator'", 'active=0'])
def test_maintenance_session_withdrawal_is_enforced_before_apply(maintenance_api, change):
    value, client = maintenance_api; value.prepare_idle(); original = value.runtime.maintenance.run
    with value.store.tx() as db: db.execute('UPDATE admin_users SET ' + change + ' WHERE id=?', (value.refs['owner'],))
    with patch.object(value.runtime.maintenance, 'run', lambda **kwargs: original(now=value.retention_now, **kwargs)):
        response = client.post('/admin/api/workflows/maintenance', headers=headers(value),
                               json={'authority': True, 'notice': 'workflow-retention-v1'})
    assert response.status_code in (401, 403)
    assert not value.store.query('SELECT 1 FROM workflow_run_archives')
