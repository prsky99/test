"""scripts/post_deploy_check.py: the before/after comparison the PM asked for (11-11 22시)."""
from scripts import post_deploy_check as check


def sample(s, cache, wire=40000):
    return {'s': s, 'status': 200, 'wire_bytes': wire, 'cache': cache, 'colo': 'LAX'}


def test_summary_keeps_the_first_visit_and_every_sample():
    rows = {'/': [sample(2.4, 'EXPIRED', 43600), sample(0.9, 'HIT'), sample(0.8, 'HIT')]}
    out = check.summary(rows)['/']
    assert out['first_s'] == 2.4 and out['median_s'] == 0.9 and out['within_1s'] == 2
    assert out['wire_kb'] == 42.6 and out['caches'] == ['EXPIRED', 'HIT', 'HIT'] and out['colos'] == ['LAX']


def test_a_failed_download_is_counted_not_dropped():
    rows = {'/': [{'s': 30.0, 'status': 'ReadTimeout'}, sample(1.2, 'MISS'), sample(1.1, 'HIT')]}
    out = check.summary(rows)['/']
    assert out['runs'] == 3 and out['first_s'] == 30.0 and out['median_s'] == 1.2


def test_compare_lists_every_page():
    before = {'summary': {p: check.summary({p: [sample(2.0, 'EXPIRED')]})[p] for p in check.PAGES}}
    after = {'summary': {p: check.summary({p: [sample(0.9, 'HIT', 20000)]})[p] for p in check.PAGES}}
    table = check.compare(before, after)
    assert len(table.splitlines()) == 1 + len(check.PAGES) and '39.1→19.5' in table


def test_every_run_keeps_its_own_file_and_after_compares_with_the_latest_before(tmp_path, monkeypatch):
    # PM 11-12: after results must stay comparable across deploys, so nothing is overwritten.
    import os
    monkeypatch.setattr(check, 'OUT', tmp_path)
    first = check.result_path('2026-11-12', 'after', 'noon')
    first.write_text('{}')
    second = check.result_path('2026-11-12', 'after', 'noon')
    assert first.name.startswith('2026-11-12-after-noon-') and second != first and not second.exists()
    old, new = tmp_path / '2026-11-12-before-0735.json', tmp_path / '2026-11-12-before-1130.json'
    old.write_text('{}'); new.write_text('{}')
    os.utime(old, (1, 1))
    assert check.latest_before('2026-11-12') == new and check.latest_before('2026-11-13') is None


def test_chat_check_asks_a_task_and_an_information_question_never_seen_before():
    # 11-12 검색과 RAG: 'send email with history <n>' and 'weather forecast for <city> <n>', 5 s target.
    import random
    first, second = check.chat_questions(random.Random(1)), check.chat_questions(random.Random(2))
    assert first[0].startswith('send email with history ') and first[1].startswith('weather forecast for ')
    assert first != second and check.CHAT_S == 5.0


def test_chat_once_records_time_server_timing_and_the_connection_line(monkeypatch):
    class Reply:
        status_code, text, headers = 200, '... Connection: This tool performs an action ...', {'server-timing': 'chat;dur=900'}

    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def post(self, url, json): assert url.endswith('/chat') and json['protocol'] == 'auto'; return Reply()
    monkeypatch.setattr(check.httpx, 'Client', Client)
    row = check.chat_once('send email with history 123')
    assert row['ok'] and row['status'] == 200 and row['connection_line'] and row['server_timing'] == 'chat;dur=900'
