"""Field Core Web Vitals beacon: bounded numbers, no identifiers stored, p75 summary, quiet endpoint."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge import rum

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc)


def beacon(**fields):
    body = {'page': 'home', 'device': 'phone', 'lcp': 1800, 'inp': 120, 'cls': 0.02}
    body.update(fields)
    return json.dumps(body).encode()


def test_record_keeps_only_bounded_metrics(tmp_path):
    entry = rum.record(beacon(ip='1.2.3.4', ua='x', page='Explore?q=secret'), now=NOW, root=tmp_path)
    assert entry == {'page': 'other', 'device': 'phone', 'lcp': 1800, 'inp': 120, 'cls': 0.02, 'hour': '2026-11-04T15'}
    line = (tmp_path / '2026-11-04.jsonl').read_text()
    assert 'secret' not in line and '1.2.3.4' not in line and (tmp_path / '2026-11-04.jsonl').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('raw', [b'{', b'[]', beacon(lcp=None), beacon(lcp=-1), beacon(inp=10**9), beacon(cls='0.1'),
                                 b'{"lcp": NaN}', b'x' * 600])
def test_bad_beacons_are_refused(raw, tmp_path):
    with pytest.raises(rum.RumError):
        rum.record(raw, now=NOW, root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_summary_reports_p75_against_the_thresholds(tmp_path):
    for lcp in (1000, 2000, 2400, 4000):
        rum.record(beacon(lcp=lcp, device='desktop'), now=NOW, root=tmp_path)
    rum.record(beacon(lcp=1500, inp=None), now=NOW, root=tmp_path)
    out = rum.summary(tmp_path, days=7, today=date(2026, 11, 4))
    assert out['all']['loads'] == 5 and out['all']['lcp'] == 2400 and out['all']['lcp_good'] is True
    assert out['groups']['home/desktop']['lcp'] == 2400 and out['groups']['home/phone']['inp'] is None


def test_endpoint_answers_204_and_records(monkeypatch, tmp_path):
    from agent_market.concierge.front import create_front_app
    from tests.test_gateway import populated
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    client = TestClient(create_front_app(populated().app.state.front))
    assert client.post('/api/rum', content=beacon(), headers={'content-type': 'text/plain'}).status_code == 204
    assert client.post('/api/rum', content=b'nope', headers={'content-type': 'text/plain'}).status_code == 204
    files = list((tmp_path / 'rum').iterdir())
    assert len(files) == 1 and len(files[0].read_text().splitlines()) == 1


def test_pages_mark_the_leading_number_and_label_the_close_button():
    css = (ROOT / 'new/en/assets/pearl-live.css').read_text()
    assert '.metric-card:nth-child(2)' not in css and '.metric-card[data-primary] .metric-value' in css
    assert 'content:"Essential only"' in css
    html = (ROOT / 'new/en/index.html').read_text()
    assert html.count('data-primary') == 1 and 'data-primary>\n<span class="pearl small" aria-hidden="true">\n</span>\n<strong class="metric-value" data-metric="reachable">' in html
    assert 'aria-label="Close and keep essential cookies only"' in html
    script = (ROOT / 'new/en/assets/panels-bootstrap.js').read_text()
    assert 'navigator.globalPrivacyControl' in script and 'sendBeacon("/api/rum"' in script
    assert 'document.cookie' not in script and 'localStorage' not in script.split('five-point step 3')[1]


def test_page_signals_do_not_use_up_the_test_run_limit(monkeypatch, tmp_path):
    """11-11 PM: 12 RUM beacons then Run test answered 429 (one 'probe' bucket per IP for both).

    Beacons, workflow events and workflow web apps now have buckets of their own; the execution routes still
    share one, and every limit number is unchanged."""
    from agent_market.concierge.front import create_front_app
    from tests.test_gateway import populated
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    front = populated().app.state.front
    monkeypatch.setattr(front.security.redis, 'is_available', lambda: False)   # in-process windows only
    client = TestClient(create_front_app(front))
    for _ in range(30):                                                      # a visitor browsing a few pages
        assert client.post('/api/rum', content=beacon(), headers={'content-type': 'text/plain'}).status_code == 204
    statuses = [client.post('/api/test/execute', json={}).status_code for _ in range(11)]
    assert statuses[:10] == [400] * 10          # reached the handler: not limited by the beacons
    assert statuses[10] == 429                  # the test-run limit itself is still 10 a minute


def test_a_caller_that_hangs_up_mid_body_is_not_a_server_error(monkeypatch, tmp_path, caplog):
    """11-10 06:32 and 18:29: ClientDisconnect while reading a POST body was logged as an ERROR with a traceback."""
    import asyncio
    import logging
    from agent_market.concierge.front import create_front_app
    from tests.test_gateway import populated
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    app = create_front_app(populated().app.state.front)
    sent = []

    async def receive():
        return {'type': 'http.disconnect'}

    async def send(message):
        sent.append(message)

    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
             'path': '/api/rum', 'raw_path': b'/api/rum', 'query_string': b'', 'root_path': '',
             'headers': [(b'host', b'testserver'), (b'content-type', b'text/plain'), (b'content-length', b'40')],
             'client': ('127.0.0.1', 5000), 'server': ('testserver', 80)}

    async def run():
        async with app.router.lifespan_context(app):
            await app(scope, receive, send)
    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    status = next(m['status'] for m in sent if m['type'] == 'http.response.start')
    assert status == 400
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR and 'request failed' in r.getMessage()]
