"""PM 11-14 supplement 2: verify_agent / best_for_role answer from a snapshot built after the daily funnel."""
import time

import pytest

from scripts import verify_snapshot as S

V = S.V          # the report_v2 module the snapshot itself uses


@pytest.fixture(autouse=True)
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'OUT', tmp_path)


def save(rid, role='fx.rate', host=None, days_ago=0, accurate=True, monkeypatch=None):
    return V.save_version({'id': rid, 'role': role, 'tool': 'convert', 'outcome': 'succeeded', 'excerpt': '1 USD = 0.92 EUR on 2026-11-14',
                           'host': host or f'h{rid}.p{rid}.com', 'latency_ms': 200, 'arguments': {'from': 'USD', 'to': 'EUR'},
                           'started': time.time() - days_ago * V.DAY})


def test_snapshot_marks_verified_final_and_alternatives(monkeypatch):
    monkeypatch.setattr(V.DQ, 'accuracy', lambda *a, **k: (25, 'answer set test', []))
    monkeypatch.setattr(V.DQ, 'freshness', lambda role, text, now=None: (10, 'test', '2026-11-14T09:00'))
    for rid in (1, 2):
        save(rid, days_ago=1)
        save(rid)
    save(3)                                                    # one day only: not verified
    necklaces = {'fx.rate.v1': [{'necklace': 'trip-brief', 'status': 'draft', 'slot': 'fx', 'members': [1, 3]}]}
    facts = {1: {'name': 'A', 'kind': 'mcp', 'grade': 'A', 'tool_fingerprint': 'h1'}}
    data = S.build(facts=facts, necklaces=necklaces)
    role = data['roles']['fx.rate.v1']
    assert set(role['verified']) == {1, 2} and role['final_pearl'] in (1, 2) and role['necklaces'][0]['necklace'] == 'trip-brief'
    three = data['agents']['3']['roles'][0]
    assert three['verified_pearl'] is False and {m['id'] for m in three['better_alternatives']} == {1, 2}
    one = data['agents']['1']
    assert one['grade'] == 'A' and one['tool_fingerprint'] == 'h1' and one['roles'][0]['data_time'] == '2026-11-14T09:00'


def test_no_accuracy_is_never_verified():
    save(7, days_ago=1)
    save(7)
    data = S.build(facts={}, necklaces={})
    assert data['roles']['fx.rate.v1']['verified'] == [] and data['agents']['7']['roles'][0]['verified_pearl'] is False
