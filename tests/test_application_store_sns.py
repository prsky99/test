"""Actual legacy social read/write parity without operating targets."""
import json
from pathlib import Path


def test_actual_bounded_social_query_families_and_native_named_lists():
    from scripts.rehearse_application_sns_postgres import rehearse
    value=rehearse()
    assert len(value['checks'])>=150 and all(value['checks'].values())
    assert value['temporary_cluster_removed'] and not value['full_application_ready']
    assert value['provider_calls']==value['operating_actions']==0
    output=Path('reports/advancement-batch7-2026-10-19/pg/sns-native.json')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(value,indent=2)+'\n')


import pytest


@pytest.mark.parametrize('value', ['1', '9999999999', 'legacy', True, False, {}, [], None])
def test_legacy_non_numeric_trial_timestamp_never_counts_as_evidence(value, monkeypatch):
    from agent_market.gateway.store import Store
    from agent_market.gateway import sns
    store = Store()
    try:
        rid = store.upsert_resource({'key':'synthetic:bad-at','kind':'mcp','source':'synthetic',
            'url':'https://synthetic.invalid/mcp','name':'Synthetic legacy boundary',
            'description':'Public documentation','category':'research','networks':[],'details':{}})
        store.record_usage(rid, [], 'synthetic-empty-tools', {}, None, {'at':value,'ok':True})
        if value is None:
            # A retained historical JSON null differs from the writer's absent
            # timestamp default, which correctly stamps its current clock.
            store._db.execute('UPDATE resources SET trial_info=? WHERE id=?', (json.dumps({'at':None,'ok':True}),rid))
        monkeypatch.setattr(sns, 'community_notes', lambda: ())
        assert sns._trials(store._db, None, [], 10) == []
        side = sns.sidebar(store._db)
        assert side['activity_24h']['trials'] == 0 and side['mood']['mcp']['trials_7d'] == 0
    finally:
        store._db.close()
