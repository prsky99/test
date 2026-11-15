"""deploy/ops/adcoin-demand-counts.sql runs read-only in psql and prints counts only (PM 11-15 10:37)."""
import subprocess

from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from scripts.rehearse_storage_adapter_postgres import PORT

SQL = 'deploy/ops/adcoin-demand-counts.sql'


def test_the_demand_count_file_runs_read_only_and_prints_only_counts(store, cluster):  # noqa: F811
    from agent_market.ad_coin.sql_registry import unchecked
    from scripts.ad_coin_v2_migrate import migrate_paid
    store.migrate_model()
    migrate_paid(store)
    with unchecked(), store.atomic():
        name = store.database.one("SELECT current_database() AS d")['d']
    run = subprocess.run(['/opt/homebrew/opt/postgresql@18/bin/psql', '-h', cluster['socket'], '-p', str(PORT), '-U',
                          'postgres', '-d', name, '-At', '-F', '|', '-v', 'ON_ERROR_STOP=1', '-f', SQL],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    lines = [line for line in run.stdout.splitlines() if line and line != 'SET']
    assert lines == ['9_rows_ever|all|paid_bookings|0']           # empty tables: nothing but the total
    assert 'ERROR' not in run.stderr
