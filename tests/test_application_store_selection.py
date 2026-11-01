"""Controlled current-source Chat and URL duplicate parity, no provider access."""
import json
from pathlib import Path


def test_actual_native_selection_and_duplicate_contracts():
    from scripts.rehearse_application_selection_postgres import rehearse
    result = rehearse()
    assert len(result['checks']) >= 35 and all(result['checks'].values())
    assert result['external_provider_calls'] == result['operating_actions'] == 0
    assert result['synthetic'] and result['temporary_cluster_removed'] and not result['public_activation']
    path = Path('reports/advancement-batch7-2026-10-19/pg/selection-native.json')
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(result,indent=2)+'\n')
