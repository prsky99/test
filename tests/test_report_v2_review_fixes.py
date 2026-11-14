"""Current-state review 11-14 (reports/current-state-review-2026-11-14): F01 repeat qualification, F02 freshness by
the kind of time, F03 completeness against the role's required output, F10 immutable atomic versions."""
import datetime
import json
import time

import pytest

from scripts import data_quality as DQ
from scripts import report_v2 as V

NOW = datetime.datetime(2026, 11, 14, 13, 0).timestamp()


@pytest.fixture(autouse=True)
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'OUT', tmp_path)
    monkeypatch.setattr(V, 'sign_version', lambda *a, **k: None)
    return tmp_path


def _write(folder, name, **v):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{name}.json').write_text(json.dumps({'tool': 'forecast', 'outcome': 'succeeded', **v}))


def _good(tested, fingerprint='new', accuracy=25, evaluator='e1'):
    return dict(tested=tested, tool_fingerprint=fingerprint, endpoint='https://w.example/mcp', evaluator_version=evaluator,
                answer_set='live:met', data_quality={'accuracy': {'points': accuracy}, 'clean': {'points': 10}})


def test_f01_only_the_same_contract_with_accurate_clean_successes_counts():
    folder = V.version_dir(1, 'weather.forecast.v1')
    _write(folder, 'a', **_good(NOW - 2 * V.DAY, fingerprint='old'))           # older tool contract
    _write(folder, 'b', **_good(NOW - 1 * V.DAY, accuracy=0))                  # not accurate
    _write(folder, 'c', **_good(NOW + 3 * V.DAY))                              # a future date
    _write(V.version_dir(1, 'news.search.v1'), 'd', **_good(NOW - V.DAY))      # another role
    _write(folder, 'e', **_good(NOW - V.DAY))
    _write(folder, 'f', **_good(NOW))
    assert V.success_days(1, 'weather.forecast.v1', 'forecast', NOW) == 2
    _write(folder, 'g', **_good(NOW + 60, evaluator='e2'))             # a new evaluator starts again
    assert V.success_days(1, 'weather.forecast.v1', 'forecast', NOW + 120) == 1


def test_f01_the_review_reproduction_counts_one_day():
    folder = V.version_dir(1, 'weather.forecast.v1')
    _write(folder, 'q0', tested=NOW - 86400, tool_fingerprint='old-contract', data_quality={'accuracy': {'points': 0}})
    _write(folder, 'q1', tested=NOW, tool_fingerprint='new-contract', data_quality={'accuracy': {'points': 25}})
    assert V.success_days(1, 'weather.forecast.v1', 'forecast', NOW) == 1


def test_f02_freshness_reads_the_kind_of_time():
    assert DQ.freshness('timezone.time.v1', 'Local time is 00:00', NOW)[0] == 0                        # zone unknown
    assert DQ.freshness('timezone.time.v1', 'Asia/Seoul: 2026-11-14T00:00', NOW)[0] == 0               # 13 hours off
    assert DQ.freshness('timezone.time.v1', 'Asia/Seoul: 2026-11-14T13:02', NOW)[0] == 10
    assert DQ.freshness('news.search.v1', 'Article published 2020-01-01. Retrieved 2026-11-14.', NOW)[0] == 0
    assert DQ.freshness('news.search.v1', 'Article published 2027-03-01', NOW)[0] == 0                  # future
    assert DQ.freshness('news.search.v1', 'Article published 2026-11-13', NOW)[0] == 10
    assert DQ.freshness('news.search.v1', '2026-11-13 headline', NOW)[0] == 0                          # unlabelled
    keyed = {'items': [{'title': 't', 'published_at': '2020-01-01'}], 'retrieved_at': '2026-11-14'}
    assert DQ.freshness('news.search.v1', '', NOW, structured=keyed)[0] == 0


def test_f03_completeness_counts_the_required_output():
    assert DQ.completeness('', {'irrelevant': 'value'})[0] == 0                       # no role: unconfirmed
    assert DQ.completeness('', {'irrelevant': 'value'}, role='fx.rate.v1')[0] == 0
    assert DQ.completeness('', {'base': 'USD', 'target': 'EUR', 'rate': 0.9}, role='fx.rate.v1')[0] == 10
    assert DQ.completeness('', {'results': [], 'total': 0}, role='news.search.v1')[3].startswith('no results')
    assert DQ.completeness('', {'error': 'upstream down', 'results': []}, role='news.search.v1')[0] == 0
    two_of_five = {'items': [{'title': 'a', 'url': 'https://a'}, {'title': 'b', 'url': 'https://b'}]}
    assert DQ.completeness('', two_of_five, role='news.search.v1', args={'limit': 5})[0] == 4.0


def test_f10_versions_are_immutable_and_an_attempt_is_stored_once():
    ts = int(time.time())
    base = {'id': 2, 'role': 'weather.forecast', 'tool': 'forecast', 'outcome': 'failed', 'host': 'audit.example',
            'arguments': {'city': 'Seoul'}, 'latency_ms': 1}
    first = V.save_version({**base, 'started': ts + 0.1})
    second = V.save_version({**base, 'started': ts + 0.2})
    again = V.save_version({**base, 'started': ts + 0.1})
    files = list(V.version_dir(2, 'weather.forecast.v1').glob('*.json'))
    assert (first['version'], second['version'], again['version']) == (1, 2, 1) and len(files) == 2
    with pytest.raises(FileExistsError):
        V.write_new(files[0], '{}')                                                   # never overwritten
    assert not list(files[0].parent.glob('.*.tmp-*'))                               # no partial file left


def test_rescore_writes_score_files_and_keeps_the_versions(monkeypatch):
    monkeypatch.setattr(V.DQ, 'accuracy', lambda *a, **k: (25, 'answer set test', []))
    saved = V.save_version({'id': 3, 'role': 'fx.rate', 'tool': 'convert', 'outcome': 'succeeded',
                            'excerpt': '1 USD = 0.92 EUR on 2026-11-14', 'host': 'fx.example', 'started': time.time(),
                            'arguments': {'from': 'USD', 'to': 'EUR'}, 'latency_ms': 300})
    path = next(V.version_dir(3, 'fx.rate.v1').glob('*.json'))
    before = path.read_text()
    assert V.rescore() == 1 and path.read_text() == before
    score = path.parent / 'scores' / f'{path.stem}.{V.EVALUATOR_VERSION}.json'
    assert score.exists() and V.latest_versions()[0]['quality'] == json.loads(score.read_text())['quality']
    assert saved['evaluator_version'] == V.EVALUATOR_VERSION and saved['attempt_id']


def test_one_official_pearl_count_excludes_own_fallbacks_and_names_its_rules(monkeypatch):
    """PM 11-14 14:2x: the heartbeat counted scores files (15/12) while the board said 12/10."""
    monkeypatch.setattr(V.DQ, 'accuracy', lambda *a, **k: (25, 'answer set test', []))
    common = {'role': 'fx.rate', 'tool': 'convert', 'outcome': 'succeeded', 'excerpt': '1 USD = 0.92 EUR on 2026-11-14',
              'arguments': {'from': 'USD', 'to': 'EUR'}, 'latency_ms': 200}
    V.save_version({**common, 'id': 7, 'host': 'fx.example', 'started': time.time()})
    V.save_version({**common, 'id': 'avc:fx', 'host': 'in-process', 'started': time.time()})
    versions = V.latest_versions()
    s = V.summary(versions, V.rank(versions), 100)
    assert s['reports'] == 1 and s['own_fallbacks']['versions'] == 1
    assert s['rules']['evaluator_version'] == V.EVALUATOR_VERSION and 'avc:' in s['rules']['excluded']
    line = V.funnel_line(json.loads(json.dumps(s)))
    assert 'final/summary.json' in line and 'v2 보고서 1(' in line and V.EVALUATOR_VERSION in line
