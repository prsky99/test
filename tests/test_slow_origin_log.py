"""R1 (PM 11-18): an origin request slower than a second leaves one INFO line per route shape per ten minutes."""
import logging
from types import SimpleNamespace

import pytest

from agent_market.concierge import front


def _request(path, method='GET'):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


@pytest.fixture(autouse=True)
def clean():
    front._slow_logged.clear()
    yield
    front._slow_logged.clear()


@pytest.mark.parametrize('path,shape', [
    ('/agent/275038', 'GET /agent/{id}'),
    ('/agents/compare/130314-vs-130467', 'GET /agents/compare/{id}'),
    ('/customer/sign-in', 'GET /customer/sign-in'),
    ('/new/en/test.html', 'GET /new/en/test.html'),
    ('/api/gateway/mcp/241601', 'GET /api/gateway/mcp/{id}'),
    ('/', 'GET /')])
def test_route_shapes_fold_the_numbers(path, shape):
    assert request_shape(path) == shape


def request_shape(path):
    return 'GET ' + front._slow_shape(path)


def test_only_slow_requests_log_and_each_shape_once_per_ten_minutes(caplog):
    caplog.set_level(logging.INFO, logger=front.__name__)
    ok = SimpleNamespace(status_code=200)
    assert not front._note_slow(_request('/agent/1'), ok, 0.99, now=0.0)                 # under a second: nothing
    assert front._note_slow(_request('/agent/1'), ok, 1.2, now=100.0)
    assert not front._note_slow(_request('/agent/2'), ok, 4.0, now=200.0)                # same shape within 10 minutes
    assert front._note_slow(_request('/customer/sign-in'), ok, 3.9, now=210.0)           # another shape logs
    assert front._note_slow(_request('/agent/3'), ok, 1.1, now=100.0 + front.SLOW_LOG_EVERY_S)   # a new window
    lines = [r.getMessage() for r in caplog.records if 'Slow origin request' in r.getMessage()]
    assert len(lines) == 3 and 'GET /agent/{id} 1.20s status 200' in lines[0]
    assert all('agent/1' not in line and '275038' not in line for line in lines)        # no id, no visitor data


def test_the_log_stays_bounded():
    ok = SimpleNamespace(status_code=200)
    for i in range(600):
        front._note_slow(_request(f'/p{i}x'), ok, 2.0, now=float(i))
    assert len(front._slow_logged) <= 501
