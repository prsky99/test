"""Required real owned-PostgreSQL proof for the asynchronous frontend delta."""

import json
from pathlib import Path


def test_actual_anonymous_hit_worker_and_front_startup_on_owned_postgres(monkeypatch):
    from scripts.rehearse_front_performance_postgres import rehearse
    monkeypatch.setenv('PGHOSTADDR', '127.0.0.1')
    monkeypatch.setenv('PGSERVICE', 'synthetic-absent-service')
    result = rehearse()
    assert len(result['checks']) >= 8 and all(result['checks'].values())
    assert result['source_unchanged'] and result['temporary_cluster_removed']
    assert not result['backend_path_faked'] and not result['full_application_ready']
    assert result['operating_database_writes'] == result['external_provider_calls'] == 0
    folder = Path('reports/advancement-phase2-core-2026-10-19/performance')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'owned-postgres.json').write_text(json.dumps(result, indent=2) + '\n')
