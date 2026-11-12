"""The app's public check and scripts/net_path.py judge the public path the same way (PM 11-12, net-path item 3)."""
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx

from agent_market import public_availability as pa

ROOT = Path(__file__).resolve().parents[1]


def _net_path():
    spec = importlib.util.spec_from_file_location('net_path_for_alignment', ROOT / 'scripts/net_path.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_limits_match_net_path():
    net_path = _net_path()
    assert pa.SLOW_S == net_path.SLOW_S
    # net_path's public and edge requests give up after the same time as the app's check
    assert "'-m', '%d', '-H', 'X-Agentcon-QA: net_path'" % pa.TIMEOUT_S in (ROOT / 'scripts/net_path.py').read_text()


def test_phase_trace_names_the_step_a_request_stopped_in():
    trace = pa.PhaseTrace()
    assert trace.stalled_at() == 'before_connect'
    for event in ('connection.connect_tcp.started', 'connection.connect_tcp.complete', 'connection.start_tls.started'):
        trace(event, {})
    assert trace.stalled_at() == 'tls'
    for event in ('connection.start_tls.complete', 'http11.send_request_headers.started',
                  'http11.send_request_headers.complete', 'http11.receive_response_headers.started'):
        trace(event, {})
    assert trace.stalled_at() == 'first_byte'
    trace('http11.receive_response_headers.complete', {})
    trace('http11.response_closed.started', {})          # not a phase: ignored
    assert trace.stalled_at() == 'after_first_byte'


class _Store:
    def __init__(self):
        self.rows = []

    def tx(self):
        store = self

        class Tx:
            def __enter__(self):
                return SimpleNamespace(execute=lambda sql, args: store.rows.append((sql.split()[0], args)))

            def __exit__(self, *exc):
                return False
        return Tx()


def _monitor(public, local=None):
    front = SimpleNamespace(store=_Store(), public_url='https://agentconcierge.biz')
    local = local or httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'service': 'Agent Concierge'})))
    return pa.AvailabilityMonitor(front, http=public, local_http=local, clock=lambda: 1794200000.0), front


def test_a_timeout_logs_the_phase_it_stopped_in(caplog):
    def stall(request):
        trace = request.extensions['trace']
        trace('connection.connect_tcp.started', {})
        trace('connection.connect_tcp.complete', {})
        trace('connection.start_tls.started', {})
        raise httpx.ConnectTimeout('handshake', request=request)
    with httpx.Client(transport=httpx.MockTransport(stall)) as public:
        monitor, front = _monitor(public)
        with caplog.at_level(logging.WARNING):
            monitor.run()
    assert 'status None' in caplog.text and 'stopped at tls' in caplog.text and '-> path problem' in caplog.text
    assert front.store.rows[0][1][1:3] == (0, None)       # the public row: still a failed observation


def test_a_403_is_a_block_not_a_path_stall(caplog):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as public:
        monitor, front = _monitor(public)
        with caplog.at_level(logging.WARNING):
            monitor.run()
    assert 'status 403' in caplog.text and '-> blocked problem' in caplog.text and 'stopped at' not in caplog.text
    assert front.store.rows[0][1][1:3] == (0, 403)


def test_a_slow_success_is_logged_by_the_net_path_rule_and_still_counts(caplog, monkeypatch):
    ticks = iter([100.0, 104.5])
    # only the module's clock: patching time.monotonic itself would stall httpx and threading
    monkeypatch.setattr(pa, 'time', SimpleNamespace(time=pa.time.time, monotonic=lambda: next(ticks)))
    with httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={'service': 'Agent Concierge'}))) as public:
        monitor, front = _monitor(public)
        with caplog.at_level(logging.INFO, logger=pa.__name__):
            monitor.run()
    assert 'Public availability check slow (4500 ms' in caplog.text and 'failed' not in caplog.text
    assert front.store.rows[0][1][1:3] == (1, 200)
