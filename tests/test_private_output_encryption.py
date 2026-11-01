"""Actual private-run retention remains authenticated through optional rotation."""
import json
import time

import pytest

from agent_market.workspace_access import WorkspaceConflict
from agent_market.workspace_execution import WorkspaceExecution, NOTICE
from agent_market.workspace_lifecycle import WorkspaceLifecycle
from agent_market.workspace_release import WorkspaceReleases
from agent_market.private_artifact_keys import ArtifactKeys, ArtifactSigner
from tests.test_private_artifact_keys import config, configure
from tests.test_workspace_release_v2 import release_world, release, deployment
from tests.test_workspace_execution_api import private_api


def execute(x, runner):
    prepared = runner.prepare(*x.args, {'snapshot_revision': x.w.snapshot['revision']}, x.actor)
    return runner.execute(*x.args, {'ticket_id': prepared['ticket_id'], 'authorized': True, 'notice': NOTICE}, x.actor)


def test_private_output_is_encrypted_then_decrypted_only_for_current_private_access(release_world, tmp_path, monkeypatch):
    x = release_world; configure(tmp_path, monkeypatch, config('old', legacy=True))
    runner = WorkspaceExecution(x.access, x.staff.proxy)
    result = execute(x, runner)
    row = x.w.store._db.execute('SELECT payload FROM workspace_private_runs WHERE id=?', (result['id'],)).fetchone()
    stored = json.loads(row[0]); assert stored['output'] is None and 'encrypted_output' in stored
    assert json.dumps(result['output'], sort_keys=True) not in row[0]
    with x.w.store.tx() as db:
        assert runner._load_run(db, result['id'], *x.args)[3]['output'] == result['output']


def test_private_output_rotation_and_archive_receipt_hash_bind_original_ciphertext(release_world, tmp_path, monkeypatch):
    x = release_world; path = configure(tmp_path, monkeypatch, config('old', legacy=True))
    old = WorkspaceExecution(x.access, x.staff.proxy); result = execute(x, old)
    original = x.w.store._db.execute('SELECT payload FROM workspace_private_runs WHERE id=?', (result['id'],)).fetchone()[0]
    path.write_text(json.dumps(config(legacy=True)))
    current = WorkspaceExecution(x.access, x.staff.proxy)
    with x.w.store.tx() as db:
        assert current._load_run(db, result['id'], *x.args)[3]['output'] == result['output']
    lifecycle = WorkspaceLifecycle(current)
    import agent_market.workspace_lifecycle as module
    monkeypatch.setattr(module, '_now', lambda: time.time() + 8 * 86400)
    assert lifecycle.maintain(x.args[0], {'limit': 50}, x.actor)['outputs_archived'] >= 1
    from agent_market.workspace_access import _hash
    with x.w.store.tx() as db:
        payload = current._load_run(db, result['id'], *x.args)[3]
        assert payload['output'] is None and payload['output_archived']
        raw = json.loads(db.execute('SELECT payload FROM workspace_private_runs WHERE id=?', (result['id'],)).fetchone()[0])
        assert 'encrypted_output' not in raw
        receipt = lifecycle._open(dict(db.execute('SELECT * FROM workspace_output_archives WHERE run_id=?', (result['id'],)).fetchone()))
        assert receipt['retained_payload_hash'] == _hash(json.loads(original))


def test_resigned_cross_run_ciphertext_swap_is_denied_by_authenticated_identity(release_world, tmp_path, monkeypatch):
    x = release_world; configure(tmp_path, monkeypatch, config('old', legacy=True))
    runner = WorkspaceExecution(x.access, x.staff.proxy); first = execute(x, runner); second = execute(x, runner)
    with x.w.store.tx() as db:
        a = json.loads(db.execute('SELECT payload FROM workspace_private_runs WHERE id=?', (first['id'],)).fetchone()[0])
        b = json.loads(db.execute('SELECT payload FROM workspace_private_runs WHERE id=?', (second['id'],)).fetchone()[0])
        a['encrypted_output'] = b['encrypted_output']
        db.execute('UPDATE workspace_private_runs SET payload=?,signature=? WHERE id=?', (json.dumps(a), runner._signature(a), first['id']))
    with x.w.store.tx() as db:
        with pytest.raises(WorkspaceConflict): runner._load_run(db, first['id'], *x.args)


def test_revoked_previous_signing_key_denies_retained_private_run(release_world, tmp_path, monkeypatch):
    x = release_world; path = configure(tmp_path, monkeypatch, config('old', legacy=True))
    runner = WorkspaceExecution(x.access, x.staff.proxy); result = execute(x, runner)
    path.write_text(json.dumps(config(revoked=('old',), legacy=True)))
    current = WorkspaceExecution(x.access, x.staff.proxy)
    with x.w.store.tx() as db:
        with pytest.raises(WorkspaceConflict): current._load_run(db, result['id'], *x.args)


def test_release_state_and_payload_grace_rotation_do_not_change_grants(release_world, tmp_path, monkeypatch):
    x = release_world; path = configure(tmp_path, monkeypatch, config('old', legacy=True))
    x.releases = WorkspaceReleases(x.staff, customer_identity=x.identity, customer_executor=x.runner)
    issued = release(x); app = deployment(x, issued['id'])
    path.write_text(json.dumps(config(legacy=True)))
    current = WorkspaceReleases(x.staff, customer_identity=x.identity, customer_executor=x.runner)
    assert current.package_config(*x.args, app['app_id'], x.actor)['app_id'] == app['app_id']
    current.revoke_deployment(*x.args, app['app_id'], {'revision': 1}, x.actor)
    path.write_text(json.dumps(config(revoked=('old',), legacy=True)))
    revoked = WorkspaceReleases(x.staff, customer_identity=x.identity, customer_executor=x.runner)
    with pytest.raises(WorkspaceConflict): revoked.package_config(*x.args, app['app_id'], x.actor)


def test_valid_large_encrypted_output_does_not_hit_plaintext_string_limit(release_world, tmp_path, monkeypatch):
    x = release_world; configure(tmp_path, monkeypatch, config('old', legacy=True))
    runner = WorkspaceExecution(x.access, x.staff.proxy)
    x.w.remote.call_result = {'content': [{'type': 'text', 'text': 'Synthetic retained evidence ' * 350},
                                        {'type': 'text', 'text': 'Second retained reference ' * 350}]}
    result = execute(x, runner)
    assert result['status'] == 'succeeded', result
    raw = json.loads(x.w.store._db.execute('SELECT payload FROM workspace_private_runs WHERE id=?', (result['id'],)).fetchone()[0])
    assert len(raw['encrypted_output']['ciphertext']) > 16000
    with x.w.store.tx() as db:
        assert runner._load_run(db, result['id'], *x.args)[3]['output'] == result['output']
