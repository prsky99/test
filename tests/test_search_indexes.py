"""Catalog search index: non-blocking operator build and a predicate the lexical query can use."""
import inspect
import re

from agent_market.admin_query_indexes import (QUEUE_INDEXES, QUEUE_PREDICATE, SEARCH_INDEXES, SEARCH_PREDICATE,
                                              SEARCH_TABLE_SETTINGS, queue_index_sql, search_index_sql)

TUNED = ['autovacuum_vacuum_scale_factor=0.01', 'autovacuum_vacuum_threshold=1000']


class Connection:
    def __init__(self, index, settings=None):
        self.index, self.settings, self.statements = index, settings, []

    def execute(self, statement, params=()):
        self.statements.append(statement)
        found = (self.settings, 10, 20) if 'reloptions' in statement else self.index
        return type('Cursor', (), {'fetchone': lambda self: found})()


def test_operator_statement_is_concurrent_partial_and_covering():
    statement = search_index_sql(concurrently=True)[0]
    assert statement.startswith('CREATE INDEX CONCURRENTLY IF NOT EXISTS resources_search_lookup ON resources ')
    assert 'INCLUDE (kind, category, last_ok_at)' in statement and statement.endswith('WHERE ' + SEARCH_PREDICATE)
    assert 'CONCURRENTLY' not in search_index_sql()[0]  # fresh stores build inside their install transaction
    assert sorted(k + '=' + v for k, v in SEARCH_TABLE_SETTINGS['resources']) == TUNED


def test_lexical_query_keeps_the_partial_index_predicate():
    # A partial index is used only when the query implies its predicate; keep both in step.
    from agent_market.concierge import discovery
    source = inspect.getsource(discovery.candidates)
    for condition in re.split(r'\s+AND\s+', SEARCH_PREDICATE):
        qualified = condition.replace('COALESCE(', 'COALESCE(r.') if condition.startswith('COALESCE(') else 'r.' + condition
        assert qualified in source


def test_build_creates_missing_rebuilds_invalid_and_skips_valid():
    from scripts import search_indexes
    missing = Connection(None)
    before, built = search_indexes.build(missing)
    assert before['resources_search_lookup']['state'] == 'missing' and 'resources_search_lookup' in built
    assert search_index_sql(concurrently=True)[0] in missing.statements and 'ANALYZE resources' in missing.statements
    assert 'ALTER TABLE resources SET (' + ','.join(TUNED) + ')' in missing.statements
    invalid = Connection((False, 8192), TUNED)
    search_indexes.build(invalid)
    assert 'DROP INDEX CONCURRENTLY IF EXISTS resources_search_lookup' in invalid.statements
    valid = Connection((True, 8192), TUNED + ['fillfactor=90'])
    built = search_indexes.build(valid)[1]
    assert set(built) == {'vacuum:resources'}  # settings already present: only the plain VACUUM
    assert not any(s.startswith(('CREATE', 'DROP', 'ALTER')) for s in valid.statements)
    assert [name for name, *_ in SEARCH_INDEXES] == ['resources_search_lookup']
    assert 'legacy_vector_jobs_open' in search_indexes.build(Connection(None))[1]
    assert queue_index_sql(concurrently=True)[0] in missing.statements
    assert 'ANALYZE legacy_vector_jobs' in missing.statements and 'ANALYZE legacy_vector_heads' in missing.statements


def test_check_only_never_writes():
    from scripts import search_indexes
    connection = Connection(None)
    search_indexes.state(connection)
    assert all(s.lstrip().startswith('SELECT') for s in connection.statements)


def test_queue_index_is_concurrent_partial_and_implied_by_every_unfinished_job_lookup():
    statement = queue_index_sql(concurrently=True)[0]
    assert statement == ("CREATE INDEX CONCURRENTLY IF NOT EXISTS legacy_vector_jobs_open ON legacy_vector_jobs "
                         "(created, job_id) WHERE status IN ('pending','claimed')")
    assert [name for name, *_ in QUEUE_INDEXES] == ['legacy_vector_jobs_open', 'legacy_vector_heads_job']
    assert queue_index_sql()[1] == ('CREATE INDEX IF NOT EXISTS legacy_vector_heads_job ON legacy_vector_heads '
                                    '(job_id, resource_id)')  # same name and columns as the SQLite install
    # The claim lookups must filter on literal unfinished states, or PostgreSQL cannot use the partial index.
    from agent_market import legacy_vector_index
    source = inspect.getsource(legacy_vector_index.VectorIndex.claim_batch)
    assert "j.status='pending' OR (j.status='claimed'" in source and "j.status='claimed' AND j.attempts>=3" in source
    assert QUEUE_PREDICATE == "status IN ('pending','claimed')"
