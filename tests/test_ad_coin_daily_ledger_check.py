"""The daily ledger check runs in a read-only session (PM 12:4x audit): PostgreSQL refuses any write."""
import json
import os

import pytest

from tests.test_ad_coin_postgres import cluster  # noqa: F401


def test_the_check_reads_a_real_database_in_a_read_only_session(cluster, tmp_path, monkeypatch):  # noqa: F811
    import psycopg
    from scripts import ad_coin_daily_ledger_check as check
    from scripts.ad_coin_worker_daemon import build
    from tests.test_ad_coin_postgres import PORT, _store
    monkeypatch.setenv("AD_COIN_V2_POOL_MAXIMUM", "1")
    _store(cluster, "ledger_ro")._connection.close()
    dsn = "host=" + cluster["socket"] + " port=" + str(PORT) + " dbname=ledger_ro user=postgres"
    dsn_file, key_file = tmp_path / "dsn", tmp_path / "key"
    dsn_file.write_text(dsn)
    key_file.write_bytes(b"p" * 32)
    for path in (dsn_file, key_file):
        os.chmod(path, 0o600)
    runtime, store, _, _ = build(str(dsn_file), str(key_file), str(tmp_path / "keys"),
                                 connector=lambda d: psycopg.connect(d, autocommit=True))
    store.migrate_model()                                    # the production database is migrated already
    store.close()
    runtime.close()
    plain = lambda d: psycopg.connect(d, autocommit=True)   # noqa: E731 - the test cluster has no TLS
    connection = check.read_only_connector(plain)(dsn)
    with connection:                                          # every connection the check opens is read-only
        assert connection.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            connection.execute("CREATE TABLE should_not_exist (x int)")
    out = tmp_path / "out"
    code = check.main(["--dsn-file", str(dsn_file), "--key-file", str(key_file), "--out-dir", str(out)], connect=plain)
    result = json.loads(next(out.iterdir()).read_text())
    assert result["status"] != "error", result["issues"]      # the whole check works without writing
    assert code in (0, 1)
