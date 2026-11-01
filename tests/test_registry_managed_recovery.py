import json
import time

import pytest

from agent_market.gateway.store import Store
from scripts.recover_registry_managed_agents import recover, START
from tests.test_managed_catalog_lifecycle import resource


def test_recovery_preserves_operator_stops_and_failure_evidence(tmp_path):
    path = tmp_path / 'source.sqlite3'
    store = Store(str(path))
    identities = [store.upsert_resource(resource(f'https://r{i}.example/api'), now=START + 100)
                  for i in range(3)]
    with store.tx() as db:
        db.execute("UPDATE resources SET active=0,health_status='healthy',last_check_at=100 WHERE id=?", (identities[0],))
        db.execute("UPDATE resources SET active=0,health_status='down',last_check_at=100,failing_since=10,consecutive_failures=9 WHERE id=?", (identities[1],))
        db.execute("UPDATE resources SET active=0,inactive_reason='operator' WHERE id=?", (identities[2],))
        db.execute("INSERT INTO admin_audit_logs(at,username,role,action,action_name,target,status) VALUES(1,'fixture','admin','AGENT_DEACTIVATE','Stopped',?,'SUCCESS')", ('agent:' + str(identities[2]),))
    plan = recover(path, expected_count=2)
    assert plan['applied'] == 0 and not plan['backup_created']
    applied = recover(path, expected_count=2, apply=True, backup_dir=tmp_path / 'private-backups')
    assert applied['applied'] == 2 and applied['health_evidence_created'] == 0
    a, b, stopped = [store.resource(identity) for identity in identities]
    assert a['active'] == 1 and a['health_status'] == 'unknown' and a['next_check_at'] is None
    assert b['active'] == 1 and b['health_status'] == 'down' and b['consecutive_failures'] == 9 and b['failing_since'] == 10
    assert stopped['active'] == 0
    assert not store.query('SELECT * FROM health_checks')
    backup = next((tmp_path / 'private-backups').glob('*.json'))
    assert backup.stat().st_mode & 0o777 == 0o600
    assert len(json.loads(backup.read_text())['rows']) == 2
    assert recover(path, expected_count=0)['eligible'] == 0


def test_changed_reviewed_count_refuses_before_any_mutation(tmp_path):
    path = tmp_path / 'source.sqlite3'
    store = Store(str(path))
    rid = store.upsert_resource(resource(), now=START + 100)
    with store.tx() as db:
        db.execute('UPDATE resources SET active=0 WHERE id=?', (rid,))
    with pytest.raises(ValueError, match='reviewed_cohort_changed'):
        recover(path, expected_count=2, apply=True, backup_dir=tmp_path / 'backups')
    assert store.resource(rid)['active'] == 0
