"""Required actual PostgreSQL finance proof in an owned disposable cluster."""
import json
import os
from pathlib import Path

from scripts import rehearse_application_finance_postgres as runner


def test_actual_native_finance_credential_concurrency_and_admin_security(monkeypatch):
    for name, value in {'PGHOSTADDR': '127.0.0.1', 'PGSERVICE': 'synthetic-missing-service',
                        'PGOPTIONS': '-c invalid_parent_setting=1',
                        'PGPASSWORD': 'synthetic-parent-password-marker',
                        'GOOGLE_CLIENT_SECRET': 'synthetic-parent-oauth-marker',
                        'AGENT_PRIVATE_ARTIFACT_KEYRING': 'synthetic-parent-artifact-marker'}.items():
        monkeypatch.setenv(name, value)
    before = dict(os.environ)
    result = runner.rehearse()
    assert dict(os.environ) == before
    assert set(result['checks']) == runner.CHECKS
    assert all(value is True for value in result['checks'].values())
    assert result['source_unchanged_during_run'] is True and result['temporary_cluster_removed'] is True
    assert result['operating_database_writes'] == result['external_provider_calls'] == 0
    assert result['payment_submissions'] == result['payout_submissions'] == 0
    assert result['production_cutover'] is False
    encoded = json.dumps(result)
    assert 'synthetic-parent-password-marker' not in encoded
    assert 'synthetic-parent-oauth-marker' not in encoded
    assert 'synthetic-parent-artifact-marker' not in encoded
    folder = Path('reports/advancement-pg-compatibility-2026-10-19')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'finance-native.json').write_text(json.dumps(result, indent=2) + '\n')
