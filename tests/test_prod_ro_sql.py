"""scripts.prod_ro_sql: the text check that keeps team lookups on the production database read-only (11-15)."""
import io
import types

import pytest

from scripts import prod_ro_sql as RO


@pytest.mark.parametrize('text', [
    "SELECT count(*) FROM ad_coin_v2.adc2_paid_bookings",
    "select state, count(*) from t group by 1 order by 1;",
    "WITH a AS (SELECT 1 AS x) SELECT x FROM a; SELECT 2",
    "SELECT 'insert into; drop -- not code' AS note, count(*) FROM t",
    "-- update the board later\nSELECT count(*) FROM t /* delete */",
    "EXPLAIN SELECT 1",
    "SHOW max_connections",
    "SELECT updated_at, offset_ms FROM t LIMIT 3",
])
def test_reads_are_accepted(text):
    assert RO.statements(text)


@pytest.mark.parametrize('text', [
    "UPDATE t SET a = 1",
    "SELECT 1; DELETE FROM t",
    "WITH x AS (DELETE FROM t RETURNING 1) SELECT count(*) FROM x",
    "SELECT * INTO copy_of_t FROM t",
    "SELECT * FROM t FOR UPDATE",
    "SELECT * FROM t FOR SHARE",
    "SET default_transaction_read_only = off; SELECT 1",
    "COMMIT; SELECT 1",
    "SELECT set_config('transaction_read_only', 'off', true)",
    "SELECT pg_sleep(60)",
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT nextval('s')",
    "SELECT pg_advisory_lock(1)",
    "EXPLAIN ANALYZE SELECT 1",
    "DO $$ BEGIN PERFORM 1; END $$",
    "SELECT $1",
    "\\set x 1\nSELECT 1",
    "SELECT password_hash FROM customers",
    "SELECT api_key FROM t",
    "SELECT 'unterminated",
    "",
    "CALL something()",
    "COPY t TO PROGRAM 'x'",
    "TABLE t",
])
def test_everything_else_is_refused(text):
    with pytest.raises(RO.Refused):
        RO.statements(text)


def test_a_refused_text_never_connects(tmp_path):
    calls = []
    code = RO.run("DELETE FROM t", out=io.StringIO(), err=io.StringIO(), log=tmp_path / 'log.jsonl',
                  psql=lambda *a: calls.append(a))
    assert code == 2 and not calls
    assert '"refused"' in (tmp_path / 'log.jsonl').read_text()


def test_runs_in_one_read_only_transaction_and_caps_the_output(tmp_path):
    seen = []

    def psql(script, timeout):
        seen.append(script)
        if 'pg_stat_activity' in script and 'BEGIN' not in script:
            return types.SimpleNamespace(returncode=0, stdout='12\n', stderr='')
        return types.SimpleNamespace(returncode=0, stdout='\n'.join(str(i) for i in range(500)), stderr='')

    out = io.StringIO()
    assert RO.run("SELECT a FROM t; SELECT b FROM u", out=out, err=io.StringIO(), psql=psql, log=tmp_path / 'l') == 0
    assert seen[1].startswith('BEGIN READ ONLY;\nSELECT 1 WHERE false;\n') and seen[1].rstrip().endswith('ROLLBACK;')
    lines = out.getvalue().splitlines()
    assert len(lines) == RO.MAX_LINES + 1 and '300 more lines' in lines[-1]


def test_a_busy_database_is_left_alone(tmp_path):
    psql = lambda script, timeout: types.SimpleNamespace(returncode=0, stdout=f'{RO.BUSY}\n', stderr='')
    assert RO.run("SELECT 1", out=io.StringIO(), err=io.StringIO(), psql=psql, log=tmp_path / 'l') == 75
