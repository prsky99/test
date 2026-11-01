"""Required real desktop admin/collector query-family API proof."""
import json
from pathlib import Path


def test_actual_native_desktop_admin_collector_queries_and_security(monkeypatch):
    from scripts.rehearse_application_admin_postgres import rehearse
    monkeypatch.setenv('PGHOSTADDR','127.0.0.1')
    monkeypatch.setenv('PGSERVICE','synthetic-absent-service')
    result=rehearse()
    assert len(result['checks'])>=13 and all(result['checks'].values())
    assert result['source_unchanged'] and result['temporary_cluster_removed']
    assert not result['backend_path_faked'] and not result['full_application_ready']
    assert result['operating_database_writes']==result['external_provider_calls']==0
    folder=Path('reports/advancement-batch7-2026-10-19/pg');folder.mkdir(parents=True,exist_ok=True)
    (folder/'admin-native.json').write_text(json.dumps(result,indent=2)+'\n')
