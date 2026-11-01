"""Independent RedisHub races and real Lua on a disposable private instance."""
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import redis

import agent_market.infra.redis_hub as module
from agent_market.infra.redis_hub import RedisHub


@pytest.fixture(scope='module')
def private_redis(tmp_path_factory):
    """Launch no inherited configuration, persistence, credentials or default port."""
    executable = Path('/opt/homebrew/bin/redis-server')
    assert executable.is_file(), 'The trusted private Redis test binary is required.'
    directory = tmp_path_factory.mktemp('redis-hub-review')
    directory.chmod(0o700)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    assert port != 6379
    process = subprocess.Popen([
        str(executable), '--bind', '127.0.0.1', '--port', str(port),
        '--protected-mode', 'yes', '--save', '', '--appendonly', 'no',
        '--dir', str(directory), '--dbfilename', 'synthetic.rdb',
        '--daemonize', 'no', '--loglevel', 'warning',
    ], cwd=directory, env={'PATH': '/usr/bin:/bin', 'HOME': str(directory)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    client = redis.Redis(host='127.0.0.1', port=port, decode_responses=True,
                         socket_timeout=0.1, socket_connect_timeout=0.1)
    ready = False
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and process.poll() is None:
            try:
                ready = client.ping()
                if ready:
                    break
            except redis.RedisError:
                time.sleep(0.01)
        assert ready, 'Disposable private Redis did not become ready.'
        yield port
    finally:
        client.close()
        client.connection_pool.disconnect()
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


@pytest.fixture
def native_hub(private_redis):
    hub = RedisHub(host='127.0.0.1', port=private_redis,
                   socket_timeout=0.1, socket_connect_timeout=0.1)
    assert hub.initialize()
    try:
        yield hub
    finally:
        hub._close()


def frozen_time(monkeypatch, value=1700000000.125):
    # Avoid changing the redis client's own clocks or global process time.
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda: value,
                                                       monotonic=time.monotonic))


def test_native_sliding_window_counts_each_request_at_the_same_timestamp(native_hub, monkeypatch):
    frozen_time(monkeypatch)
    key = 'synthetic:review:rate:same-time'
    native_hub.raw_client.delete(key)
    actual = [native_hub.check_sliding_window(key, limit=3, window=60) for _ in range(5)]
    assert actual == [True, True, True, False, False]
    assert native_hub.raw_client.zcard(key) == 3


def test_native_violation_threshold_counts_each_same_timestamp_event(native_hub, monkeypatch):
    frozen_time(monkeypatch)
    prefix, ip = 'synthetic:review:', '192.0.2.111'
    key = prefix + 'jail:violations:' + ip
    native_hub.raw_client.delete(key)
    actual = [native_hub.record_violation(ip, threshold=3, window=60, prefix=prefix)
              for _ in range(4)]
    assert actual == [(False, 1), (False, 2), (True, 3), (True, 4)]
    assert native_hub.raw_client.zcard(key) == 4


def test_native_script_reload_and_boundary_expiration_keep_logical_counts(native_hub, monkeypatch):
    clock = [1700000100.0]
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda: clock[0], monotonic=time.monotonic))
    key = 'synthetic:review:rate:reload'
    native_hub.raw_client.delete(key)
    assert native_hub.check_sliding_window(key, 2, 60) is True
    native_hub.raw_client.script_flush()
    assert native_hub.check_sliding_window(key, 2, 60) is True
    assert native_hub.check_sliding_window(key, 2, 60) is False
    clock[0] += 60
    assert native_hub.check_sliding_window(key, 2, 60) is True
    assert native_hub.raw_client.zcard(key) == 1


class ControlledClient:
    """No network; events make publication, operation and disposal order exact."""
    def __init__(self, *, delayed_probe=False, probe_fails=False, delayed_get=False,
                 get_fails=False, delayed_close=False):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.get_entered = threading.Event()
        self.get_release = threading.Event()
        self.close_entered = threading.Event()
        self.close_release = threading.Event()
        self.delayed_probe, self.probe_fails = delayed_probe, probe_fails
        self.delayed_get, self.get_fails = delayed_get, get_fails
        self.delayed_close = delayed_close
        self.closed = 0
        self.disconnected = 0
        self.registered = 0
        self.connection_pool = SimpleNamespace(disconnect=self.disconnect)

    def ping(self):
        self.entered.set()
        if self.delayed_probe:
            assert self.release.wait(3), 'Controlled probe release was not supplied.'
        if self.probe_fails:
            raise redis.ConnectionError('synthetic controlled probe failure')
        return True

    def register_script(self, _script):
        self.registered += 1
        return lambda **_kwargs: 1

    def get(self, _key):
        self.get_entered.set()
        if self.delayed_get:
            assert self.get_release.wait(3), 'Controlled old operation was not released.'
        if self.get_fails:
            raise redis.ConnectionError('synthetic controlled stale operation')
        return '{"synthetic":true}'

    def close(self):
        self.closed += 1
        self.close_entered.set()
        if self.delayed_close:
            assert self.close_release.wait(3), 'Controlled close was not released.'

    def disconnect(self):
        self.disconnected += 1


def test_delayed_reconnect_is_single_flight_and_request_callers_return_without_probe(monkeypatch):
    candidate = ControlledClient(delayed_probe=True)
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return candidate

    monkeypatch.setattr(redis, 'Redis', factory)
    hub = RedisHub(host='127.0.0.1', port=16389)
    assert hub.is_available() is False
    assert candidate.entered.wait(1)
    results = []
    threads = [threading.Thread(target=lambda: results.append(hub.is_available())) for _ in range(24)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
        assert all(not thread.is_alive() for thread in threads)
        assert results == [False] * 24
        assert len(calls) == 1
        assert hub.raw_client is None and hub._probing
        assert calls[0]['retry'].get_retries() == 0
        assert 'retry_on_timeout' not in calls[0]
        assert calls[0]['retry_on_error'] == []
    finally:
        candidate.release.set()
        hub._reconnect_thread.join(timeout=2)
        hub._close()
    assert not hub._reconnect_thread.is_alive()
    assert candidate.closed and candidate.disconnected


@pytest.mark.parametrize('probe_fails', [False, True])
def test_reset_invalidates_delayed_probe_before_waiting_for_pool_disposal(monkeypatch, probe_fails):
    candidate = ControlledClient(delayed_probe=True, probe_fails=probe_fails, delayed_close=True)
    monkeypatch.setattr(redis, 'Redis', lambda **_kwargs: candidate)
    hub = RedisHub(host='127.0.0.1', port=16389)
    monkeypatch.setattr(RedisHub, '_instance', hub)
    assert hub.is_available() is False and candidate.entered.wait(1)
    before_epoch = hub._probe_epoch
    reset = threading.Thread(target=RedisHub.reset_instance_for_testing)
    try:
        reset.start()
        assert candidate.close_entered.wait(1)
        assert RedisHub._instance is None
        assert hub._closed and hub._probe_epoch > before_epoch
        assert not hub._is_alive and hub.raw_client is None
        candidate.release.set()
        assert hub.is_available() is False
    finally:
        candidate.release.set()
        candidate.close_release.set()
        reset.join(timeout=2)
        hub._reconnect_thread.join(timeout=2)
    assert not reset.is_alive() and not hub._reconnect_thread.is_alive()
    assert hub.raw_client is None and not hub._is_alive and hub._closed
    assert hub._consecutive_failures == 0
    assert candidate.closed and candidate.disconnected


@pytest.mark.parametrize('old_fails', [False, True])
def test_late_old_operation_cannot_revive_or_trip_a_replacement_client(monkeypatch, old_fails):
    old = ControlledClient(delayed_get=True, get_fails=old_fails)
    new = ControlledClient()
    sequence = iter((old, new))
    monkeypatch.setattr(redis, 'Redis', lambda **_kwargs: next(sequence))
    hub = RedisHub(host='127.0.0.1', port=16389)
    assert hub.initialize()
    result = []
    operation = threading.Thread(target=lambda: result.append(hub.get_json('synthetic:old-cache')))
    try:
        operation.start()
        assert old.get_entered.wait(1)
        assert hub.initialize() and hub.raw_client is new
        with hub._state_lock:
            hub._is_alive = False
            hub._consecutive_failures = 2
            hub._circuit_open_until = time.monotonic() + 60
        old.get_release.set()
        operation.join(timeout=2)
        assert not operation.is_alive()
        assert hub.raw_client is new
        assert hub._consecutive_failures == 2 and not hub._is_alive
        assert result == ([None] if old_fails else [{'synthetic': True}])
    finally:
        old.get_release.set()
        operation.join(timeout=2)
        hub._close()
    assert old.closed and new.closed
