"""An obsolete imported queue head must not starve current eligible work."""
import pytest

from tests.test_legacy_vector_index import world, row, insert


@pytest.mark.parametrize('invalid', ['inactive', 'deleted', 'quarantined', 'retired',
                                    'generation', 'source_hash', 'corpus_hash', 'descriptor_hash'])
def test_obsolete_oldest_head_is_retired_before_claiming_eligible_work(world, invalid):
    db, index, descriptor = world
    with db:
        if invalid == 'inactive':
            db.execute('UPDATE resources SET active=0 WHERE id=1')
        elif invalid == 'deleted':
            db.execute('DELETE FROM resources WHERE id=1')
        elif invalid == 'quarantined':
            db.execute("UPDATE resources SET eval_security='quarantine' WHERE id=1")
        elif invalid == 'retired':
            db.execute("UPDATE resources SET health_status='retired' WHERE id=1")
        # Simulate queue intent inherited from a legacy import, including rows
        # that current resource-update triggers would normally invalidate.
        db.execute("INSERT OR REPLACE INTO vec_outbox VALUES(1,1,'backfill')")
        head = db.execute('SELECT job_id FROM legacy_vector_heads WHERE resource_id=1').fetchone()[0]
        db.execute('UPDATE legacy_vector_jobs SET created=1 WHERE job_id=?', (head,))
        if invalid == 'generation':
            db.execute('UPDATE legacy_vector_jobs SET generation=generation-1 WHERE job_id=?', (head,))
        elif invalid in ('source_hash', 'corpus_hash', 'descriptor_hash'):
            from agent_market.legacy_vector_index import source
            prepared = source(dict(db.execute('SELECT * FROM resources WHERE id=1').fetchone()))
            hashes = dict(source_hash=prepared.source_hash, corpus_hash=prepared.corpus_hash,
                          descriptor_hash=descriptor.digest)
            hashes[invalid] = 'f' * 64
            db.execute('UPDATE legacy_vector_jobs SET source_hash=?,corpus_hash=?,descriptor_hash=? WHERE job_id=?',
                       (hashes['source_hash'], hashes['corpus_hash'], hashes['descriptor_hash'], head))
        insert(db, row(2))
        db.execute('UPDATE legacy_vector_jobs SET created=2 WHERE resource_id=2')
    claims = index.claim_batch(descriptor, limit=1)
    assert len(claims) == 1 and claims[0].resource_id == 2
    obsolete = db.execute('SELECT status,attempts,finished FROM legacy_vector_jobs WHERE job_id=?', (head,)).fetchone()
    assert obsolete['status'] == 'superseded' and obsolete['attempts'] == 0
    assert obsolete['finished'] is not None
    assert db.execute('SELECT COUNT(*) FROM legacy_vector_provenance').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM vec_resources').fetchone()[0] == 0


def test_ineligible_rows_are_excluded_before_bounded_cleanup_limit(world):
    from agent_market.legacy_vector_index import MAX_BATCH
    db, index, descriptor = world
    with db:
        db.execute('UPDATE resources SET active=0 WHERE id=1')
        for number in range(1, MAX_BATCH + 11):
            if number > 1:
                insert(db, row(number, active=0))
            db.execute("INSERT OR REPLACE INTO vec_outbox VALUES(?,?, 'backfill')", (number, number))
            db.execute('UPDATE legacy_vector_jobs SET created=? WHERE resource_id=?', (number, number))
        eligible = MAX_BATCH + 11
        insert(db, row(eligible))
        db.execute('UPDATE legacy_vector_jobs SET created=? WHERE resource_id=?', (eligible, eligible))
    claims = index.claim_batch(descriptor, limit=1)
    assert len(claims) == 1 and claims[0].resource_id == eligible
    assert db.execute("SELECT COUNT(*) FROM legacy_vector_jobs WHERE status='pending'").fetchone()[0] > 0


def test_stale_caller_snapshot_does_not_retire_current_otherwise_eligible_head(world):
    db, index, descriptor = world
    with db:
        insert(db, row(2))
        db.execute('UPDATE legacy_vector_jobs SET created=resource_id')
    expected = [row(name='Stale caller value'), row(2)]
    claims = index.claim_batch(descriptor, limit=1, resource_ids=[1, 2], expected_resources=expected)
    assert len(claims) == 1 and claims[0].resource_id == 2
    head = db.execute('SELECT j.status,j.attempts FROM legacy_vector_jobs j JOIN legacy_vector_heads h USING(job_id) '
                      'WHERE h.resource_id=1').fetchone()
    assert head['status'] == 'pending' and head['attempts'] == 0
