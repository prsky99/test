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


def test_r04_tests_never_sign_into_the_production_folder(monkeypatch):
    """Precision review R04: a test run points at a temporary folder, and the production folder is refused."""
    import os
    assert V.signing_dir() != V.PRODUCTION_SIGNING and os.environ.get('AGENTCON_SIGNING_DIR')
    assert not V.signing_allowed(V.PRODUCTION_SIGNING)
    monkeypatch.delenv('AGENTCON_SIGNING_DIR')
    assert V.signing_dir() == V.PRODUCTION_SIGNING and V.signing_key() is None   # refused under pytest


def test_r09_results_without_a_start_time_are_separate_attempts():
    """Precision review R09: two connection failures without 'started' were one attempt id; only the first was stored."""
    base = {'id': 21, 'role': 'fx.rate', 'tool': 'convert', 'outcome': 'failed', 'host': 'fx.example', 'reason': 'connect'}
    first = V.save_version(dict(base), now=NOW)
    second = V.save_version(dict(base), now=NOW + 60)
    assert first['attempt_id'] != second['attempt_id']
    assert len(list(V.version_dir(21, 'fx.rate.v1').glob('*.json'))) == 2


def test_r09_a_provisional_pearl_needs_one_success_day(monkeypatch):
    monkeypatch.setattr(V, 'success_days', lambda *a, **k: 0)
    v = {'resource_id': 31, 'role': 'fx.rate.v1', 'tool': 'convert', 'outcome': 'succeeded', 'registrable_domain': 'fx.example',
         'quality': {'score': 90}, 'domain': 'finance', 'tested': NOW, 'data_quality': {'accuracy': {'points': 25}}}
    assert V.rank([v])['fx.rate.v1']['provisional_pearl'] is None


def test_r08_our_side_skips_are_not_stored_and_failures_come_back(monkeypatch, tmp_path):
    """Precision review R08: a provider-limit skip stays in the queue; a failure is retried after 1, 2 then 4 days."""
    import pearl_batch as PB
    import role_tool_test as RT
    monkeypatch.setattr(PB, 'STATE_DIR', tmp_path / 'state')
    monkeypatch.setattr(V, 'quiet_now', lambda: True)
    monkeypatch.setattr(RT, 'resources', lambda ids: {})
    monkeypatch.setattr(RT, 'test_one', lambda http, c, r, p: {**c, 'host': 'fx.example', 'outcome': 'skipped',
                                                              'reason': 'provider limit for today', 'started': time.time()})
    V.run([{'id': 41, 'role': 'fx.rate', 'kind': 'new'}])
    assert not V.version_dir(41, 'fx.rate.v1').exists()
    base = {'id': 42, 'role': 'fx.rate', 'tool': 'convert', 'outcome': 'failed', 'host': 'fx.example', 'reason': 'HTTP 500'}
    V.save_version({**base, 'started': NOW - 30 * 3600})
    latest = V.latest_versions()
    assert [c['id'] for c in V.retest_queue(latest, day=1, now=NOW)] == [42]            # one failure: back after a day
    V.save_version({**base, 'started': NOW - 30 * 3600 + 60})                           # two in a row: wait two days
    assert V.retest_queue(V.latest_versions(), day=1, now=NOW) == []
    assert [c['id'] for c in V.retest_queue(V.latest_versions(), day=1, now=NOW + 24 * 3600)] == [42]


def test_r15_one_storage_error_never_stops_the_run(monkeypatch, tmp_path):
    """Precision review R15: a candidate whose result cannot be stored is retried once and then skipped."""
    import pearl_batch as PB
    import role_tool_test as RT
    monkeypatch.setattr(PB, 'STATE_DIR', tmp_path / 'state')
    monkeypatch.setattr(V, 'quiet_now', lambda: True)
    monkeypatch.setattr(V.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(RT, 'resources', lambda ids: {})
    monkeypatch.setattr(RT, 'test_one', lambda http, c, r, p: {**c, 'tool': 'convert', 'host': 'fx.example',
                                                              'outcome': 'failed', 'reason': 'HTTP 500', 'started': time.time()})
    real, tries = V.save_version, []

    def flaky(result, **k):
        tries.append(result['id'])
        if result['id'] == 51:
            raise OSError('disk')
        return real(result, **k)
    monkeypatch.setattr(V, 'save_version', flaky)
    errors = V.run([{'id': 51, 'role': 'fx.rate', 'kind': 'new'}, {'id': 52, 'role': 'fx.rate', 'kind': 'new'}])
    assert errors == {'our_errors': 0, 'save_errors': 1} and tries == [51, 51, 52]
    assert V.version_dir(52, 'fx.rate.v1').exists() and not V.version_dir(51, 'fx.rate.v1').exists()


def test_r15_a_failed_daily_stage_is_retried_and_said(monkeypatch, out):
    import pearl_daily as PD
    monkeypatch.setattr(PD.V, 'OUT', out)            # pearl_daily imports report_v2 by its plain name: another module
    said, calls = [], []
    monkeypatch.setattr(PD, 'RETRY_WAIT', 0)
    monkeypatch.setattr(PD, 'alert', said.append)
    monkeypatch.setitem(__import__('sys').modules, 'health_tiers', type('M', (), {'main': staticmethod(lambda: None)}))
    monkeypatch.setitem(__import__('sys').modules, 'verify_snapshot', type('M', (), {'main': staticmethod(lambda: None)}))
    monkeypatch.setattr(PD.V, 'import_fallbacks', lambda: 0)

    def queue():
        calls.append('queue')
        if len(calls) == 1:
            raise RuntimeError('first try')
        return []
    monkeypatch.setattr(PD.V, 'build_queue', queue)
    monkeypatch.setattr(PD.V, 'run', lambda q: {'our_errors': 0, 'save_errors': 0})
    monkeypatch.setattr(PD.V, 'publish', lambda board: (_ for _ in ()).throw(OSError('board')))
    assert PD.main([]) == 1 and calls == ['queue', 'queue']
    assert said and 'publish OSError' in said[0] and '전날 결과' in said[0]
    assert not list(out.glob('done-*'))


def test_r11_rescore_judges_the_kept_answer_and_never_flips_a_verdict_from_the_excerpt(monkeypatch):
    """Precision review R11: 158 of 280 versions were judged again on the 1,000-character excerpt, both ways."""
    verdict = {'points': 25}
    monkeypatch.setattr(V.DQ, 'accuracy', lambda *a, **k: (verdict['points'], 'answer set test', []))
    common = {'role': 'fx.rate', 'tool': 'convert', 'outcome': 'succeeded', 'host': 'fx.example',
              'arguments': {'from': 'USD', 'to': 'EUR'}, 'latency_ms': 300}
    kept = V.save_version({**common, 'id': 61, 'excerpt': 'x' * 1000, 'full_text': 'x' * 1500 + ' 1 USD = 0.92 EUR',
                           'structured': {'base': 'USD', 'target': 'EUR', 'rate': 0.92}, 'started': time.time()})
    old = V.save_version({**common, 'id': 62, 'excerpt': '1 USD = 0.92 EUR', 'started': time.time()})
    folder = V.version_dir(61, 'fx.rate.v1')
    answer = folder / kept['answer_file']
    assert answer.exists() and json.loads(answer.read_text())['full_text'].endswith('0.92 EUR') and 'answer_file' not in old
    verdict['points'] = 0                                    # the new evaluator finds the answer not accurate
    assert V.rescore() == 2
    by_id = {v['resource_id']: v for v in V.latest_versions()}
    assert by_id[61]['content_verdict'] == 'not accurate' and by_id[61]['verdict_basis'].startswith('judged again')
    assert by_id[62]['content_verdict'] == 'accurate' and by_id[62]['verdict_basis'].startswith('carried')
    assert by_id[62]['evaluator_version'] == V.EVALUATOR_VERSION
    answer.write_text(answer.read_text().replace('0.92', '9.99'))   # a changed answer file is not trusted
    verdict['points'] = 25
    V.rescore()
    assert {v['resource_id']: v for v in V.latest_versions()}[61]['verdict_basis'].startswith('carried')


def test_r10_accuracy_asks_for_facts_beyond_the_input_as_whole_words():
    """Precision review R10: "MIT" matched inside "commits"; an answer repeating its input scored 25; one link passed news."""
    from agent_market.necklaces import role_tasks as RT
    lic = {'case_id': 'lic', 'role': 'package.license.v1', 'input': {'name': 'left-pad'}, 'expect': {'must_include_any': ['MIT']}}
    assert DQ.accuracy(lic, '42 commits since 2016', None, role_tasks=RT)[0] == 0
    assert DQ.accuracy(lic, 'License: MIT', None, role_tasks=RT)[0] == DQ.WEIGHTS['accuracy']
    site = {'case_id': 'site', 'role': 'website.ai_readiness.v1', 'input': {'url': 'python.org'},
            'expect': {'must_include_any': ['python.org']}}
    echo = DQ.accuracy(site, 'python.org looks fine', None, role_tasks=RT)
    assert echo[0] == 0 and 'nothing beyond the input' in echo[1]
    cve = {'case_id': 'cve', 'role': 'cve.record.v1', 'input': {'cve': 'CVE-2023-4863'},
           'expect': {'must_include_all': ['CVE-2023-4863'], 'must_include_any': ['libwebp', 'WebP']}}
    assert DQ.accuracy(cve, 'CVE-2023-4863: details unavailable', None, role_tasks=RT)[0] == 0
    assert DQ.accuracy(cve, 'CVE-2023-4863 heap overflow in libwebp', None, role_tasks=RT)[0] == DQ.WEIGHTS['accuracy']
    news = {'case_id': 'news', 'role': 'news.search.v1', 'input': {'q': 'cybersecurity', 'limit': 5},
            'expect': {'must_include_https_url': True, 'published_within_days': 14}}
    today = time.strftime('%Y-%m-%d')
    assert DQ.accuracy(news, 'See https://example.com/a', None, role_tasks=RT)[0] == 0
    assert DQ.accuracy(news, f'Breach at X, published {today} https://example.com/a', None,
                       role_tasks=RT)[0] == DQ.WEIGHTS['accuracy']
    assert DQ.accuracy(news, 'Old story, published 2019-01-02 https://example.com/a', None, role_tasks=RT)[0] == 0


def test_r12_nested_scores_and_negated_kev_are_read():
    """Precision review R12: a nested CVSS score and "KEV: Not listed" scored 0 although right."""
    from agent_market.necklaces import role_tasks as RT
    record = {'case_id': 'r', 'input': {'cve': 'CVE-2021-44228'}, 'expect': {'numeric': {'cvss_score': {'equals': 10.0}}}}
    assert RT.score(record, '', {'metrics': {'cvssMetricV31': [{'cvssData': {'baseScore': 10.0}}]}})[0]
    assert RT.score(record, 'Log4Shell, CVSS 10.0 (critical)')[0]
    assert not RT.score(record, 'CVSS:3.1/AV:N/AC:L')[0]                     # a vector string is not a score
    kev = {'case_id': 'k', 'input': {'cve': 'CVE-2024-3094'}, 'expect': {'kev': False}}
    for text in ('KEV: Not listed', 'not in the CISA KEV catalog', '"in_kev": false', 'KEV status: not listed'):
        assert RT.score(kev, text)[0], text
    assert not RT.score(kev, 'Listed in CISA KEV (known exploited)')[0]


def test_r12_a_member_is_ranked_on_its_recent_tasks_not_one_days_case(monkeypatch):
    monkeypatch.setattr(V, 'success_days', lambda *a, **k: 2)
    def version(rid, case, score, accurate, days_ago, domain='x.example'):
        return {'resource_id': rid, 'role': 'cve.record.v1', 'tool': 'lookup', 'case_id': case, 'evaluator_version': 'e',
                'outcome': 'succeeded', 'registrable_domain': domain, 'domain': 'security', 'tested': NOW - days_ago * V.DAY,
                'quality': {'score': score}, 'data_quality': {'accuracy': {'points': 25 if accurate else 0}}}
    steady = [version(1, 'a', 90, True, 2), version(1, 'b', 91, True, 1), version(1, 'c', 60, False, 0)]
    lucky = [version(2, 'a', 50, False, 2), version(2, 'b', 55, False, 1), version(2, 'c', 95, True, 0)]
    steady = [{**v, 'registrable_domain': 's.example'} for v in steady]
    lucky = [{**v, 'registrable_domain': 'l.example'} for v in lucky]
    stored = {1: steady, 2: lucky}
    monkeypatch.setattr(V, 'versions_of', lambda rid, role: stored[rid])
    monkeypatch.setattr(V.time, 'time', lambda: NOW)
    role = V.rank([steady[-1], lucky[-1]])['cve.record.v1']
    assert [m['resource_id'] for m in role['members']] == [1, 2]
    assert role['final_pearl'] == 1 and role['members'][0]['recent_pass_rate'] == 0.67


def test_r13_clean_fails_only_what_is_certainly_not_an_answer_and_retrieval_times_do_not_count():
    """Precision review R13: "truncated": false, Spanish "todo" and a quoted 500 error failed answers; "Retrieved on
    <now>" gave full freshness."""
    assert DQ.clean_issues('{"truncated": false, "items": [1]}') == [] and DQ.clean_issues('Lista: todo el día') == []
    assert DQ.clean_issues('The API returned 500 Internal Server Error to users', role='software.incident.v1') == []
    assert DQ.clean_review('The API returned 500 Internal Server Error') == ['error text inside the answer']
    assert DQ.clean_issues('{"error": null, "rate": 0.92}') == []
    assert DQ.clean_issues('Error: upstream timeout') == ['error text'] and DQ.clean_issues('{"error": "bad key"}')
    assert DQ.clean_review('TODO: fill in') == ['placeholder word'] and DQ.clean_issues('TODO: fill in') == []
    now = NOW
    stamp = time.strftime('%Y-%m-%dT%H:%M', time.localtime(now))
    assert DQ.freshness('fx.rate.v1', f'Retrieved on {stamp}', now)[0] == 0
    assert DQ.freshness('fx.rate.v1', f'Rate as of {stamp}', now)[0] == 10
    assert DQ.freshness('timezone.time.v1', f'Retrieved on {stamp}', now, args={'tz': 'Asia/Seoul'})[0] == 0
