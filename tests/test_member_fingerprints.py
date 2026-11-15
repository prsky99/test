"""Members' fingerprints every 6 hours, in the form the necklace watch and the verified registry read (PM 11-15 11:5x)."""
import json
from datetime import datetime

import httpx
import pytest

from agent_market import member_fingerprints as mf
from agent_market.necklaces.watch import fingerprint_status
from agent_market.tool_fingerprint import server_fp

WEATHER = {'name': 'get_weather', 'description': 'Forecast for 3 days', 'annotations': {'readOnlyHint': True},
           'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}


def tools(description='Forecast for 3 days', extra=()):
    return [{**WEATHER, 'description': description}, *extra]


def at(hour):
    return datetime(2026, 11, 16, hour, 15).timestamp()


@pytest.fixture
def site(tmp_path):
    data = tmp_path / 'fingerprints'
    data.mkdir()
    (data / 'pearls.json').write_text(json.dumps({'generated': '2026-11-14T04:21:40+0900', 'pearls': {
        '501': {'server_fp': server_fp(tools()), 'baseline_at': '2026-11-14T04:21:40+0900', 'tools': {}}}}))
    rows = {501: {'id': 501, 'kind': 'mcp', 'url': 'https://weather.example/mcp'},
            502: {'id': 502, 'kind': 'a2a', 'url': 'https://agent.example/'}}
    calls, notes = [], []
    state = {'tools': tools()}

    def fetch(url):
        calls.append(url)
        if isinstance(state['tools'], Exception):
            raise state['tools']
        return state['tools']

    def run(hour, ids=(501, 502), reserve=lambda url: (True, 'ok')):
        return mf.refresh(rows.get, fetch, data=data, now=at(hour), ids=list(ids), reserve=reserve,
                          note=lambda url, status: notes.append(status), sleep=lambda s: None)

    def entry():
        return json.loads((data / 'pearls.json').read_text())['resources']['501']

    return data, state, run, entry, calls, notes


def test_the_first_measure_keeps_the_qualified_baseline_and_both_readers_see_it(site, monkeypatch):
    data, state, run, entry, calls, _ = site
    assert run(10) == {'measured': 1, 'changed': 0, 'risk': 0, 'skipped': 1, 'failed': 0}   # the A2A row is skipped
    saved = json.loads((data / 'pearls.json').read_text())
    assert saved['generated'].startswith('2026-11-16T10:15') and '501' in saved['pearls']   # earlier entries kept
    e = entry()
    assert e['baseline'] == e['current'] == e['last_server_fp'] == server_fp(tools()) and e['classification'] == 'same'
    assert e['unchanged_since'] == '2026-11-14T04:21:40+0900'
    assert fingerprint_status(saved, 501) == 'same' and calls == ['https://weather.example/mcp']
    monkeypatch.setenv('FINGERPRINT_DATA', str(data))
    from agent_market.verified_registry import load_fingerprints
    assert load_fingerprints()[0][501]['server_fp'] == e['current']


def test_a_number_in_a_description_is_dynamic_and_a_new_text_is_a_change_with_its_line(site):
    data, state, run, entry, _, _ = site
    run(10)
    state['tools'] = tools('Forecast for 5 days')
    run(16)
    e = entry()
    assert e['classification'] == 'dynamic' and e['unchanged_since'] == '2026-11-14T04:21:40+0900'
    assert fingerprint_status({'resources': {'501': e}}, 501) == 'dynamic'
    state['tools'] = tools('Hourly forecast and alerts')
    run(22)
    e = entry()
    assert e['classification'] == 'general' and e['unchanged_since'].startswith('2026-11-16T22:15')
    assert fingerprint_status({'resources': {'501': e}}, 501) == 'changed'
    lines = [json.loads(x) for x in (data / 'changes-20261116.jsonl').read_text().splitlines()]
    assert [x['classification'] for x in lines] == ['dynamic', 'general']
    assert lines[-1]['changed'] == [{'name': 'get_weather'}] and 'description' not in json.dumps(lines)   # names only


def test_a_new_writing_tool_or_a_flipped_hint_is_a_risk(site):
    data, state, run, entry, _, _ = site
    run(10)
    state['tools'] = tools(extra=[{'name': 'delete_city', 'description': 'Deletes a saved city',
                                   'annotations': {'destructiveHint': True}, 'inputSchema': {'type': 'object'}}])
    run(16)
    e = entry()
    assert e['classification'] == 'risk' and e['risk'] == ['new_unsafe_tool:delete_city']
    assert fingerprint_status({'resources': {'501': e}}, 501) == 'risk'
    state['tools'] = [{**WEATHER, 'annotations': {'readOnlyHint': False}}]
    run(22)
    assert 'annotation_flip:get_weather' in entry()['risk']


def test_a_refused_budget_or_a_failed_call_keeps_the_last_values_and_a_429_is_noted(site):
    data, state, run, entry, calls, notes = site
    run(10)
    before = entry()
    assert run(16, reserve=lambda url: (False, 'system_share'))['skipped'] == 2
    assert entry()['current'] == before['current'] and entry()['error'] == 'budget:system_share'
    response = httpx.Response(429, request=httpx.Request('POST', 'https://weather.example/mcp'))
    state['tools'] = httpx.HTTPStatusError('busy', request=response.request, response=response)
    assert run(22)['failed'] == 1 and notes == [429] and entry()['current'] == before['current']


def test_the_step_waits_six_hours_and_skips_the_measurement_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, 'DATA', tmp_path)
    ran = []
    step = mf.MemberFingerprintStep(type('S', (), {'resource': None})(), clock=lambda: clock[0],
                                    refresh_fn=lambda *a, **k: ran.append(k['now']) or {'measured': 0},
                                    background=False)
    clock = [at(10)]
    assert step.run_due() == {'member_fingerprints': {'measured': 0}}
    clock[0] = at(15)
    assert step.run_due() is None                                    # five hours later
    clock[0] = datetime(2026, 11, 16, 16, 58).timestamp()
    assert step.run_due() is None                                    # :55-:10 measurement window
    clock[0] = datetime(2026, 11, 16, 17, 20).timestamp()
    assert step.run_due() is not None and len(ran) == 2
