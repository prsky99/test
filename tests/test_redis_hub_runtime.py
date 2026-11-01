"""Isolated Redis retry, reconnect concurrency, and singleton shutdown checks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread, current_thread
import socket
import time

import pytest
import redis
from redis.backoff import NoBackoff

from agent_market.infra.redis_hub import RedisHub


class Pool:
    def __init__(self):
        self.disconnected = 0

    def disconnect(self):
        self.disconnected += 1


class Client:
    def __init__(self, probe=None):
        self.probe = probe or (lambda: True)
        self.connection_pool = Pool()
        self.closed = 0
        self.scripts = []
        self.values = {}

    def ping(self):
        return self.probe()

    def register_script(self, source):
        self.scripts.append(source)
        return lambda **kwargs: [0, 1] if 'return {1, count}' in source else 1

    def close(self):
        self.closed += 1

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, **kwargs):
        self.values[key] = value
        return True


def test_explicit_retry_policy_does_one_attempt_and_failed_candidate_closes(monkeypatch):
    captured = {}
    def fail():
        raise redis.ConnectionError('synthetic failure')
    client = Client(fail)
    monkeypatch.setattr(redis, 'Redis', lambda **kwargs: captured.update(kwargs) or client)
    hub = RedisHub(host='synthetic.invalid', port=16379)
    assert hub.initialize() is False
    retry = captured['retry']
    assert type(retry._backoff) is NoBackoff and retry._retries == 0
    attempts = []
    def failure():
        attempts.append(1)
        raise redis.ConnectionError('synthetic retry probe')
    with pytest.raises(redis.ConnectionError):
        retry.call_with_retry(failure, lambda error: None)
    assert attempts == [1]
    assert captured['socket_timeout'] == captured['socket_connect_timeout'] == .25
    assert 'retry_on_timeout' not in captured and captured['retry_on_error'] == []
    assert client.closed == 1 and client.connection_pool.disconnected == 1
    assert hub.raw_client is None and hub.is_available() is False


def test_blocked_background_probe_never_blocks_callers_or_stampedes(monkeypatch):
    entered, release = Event(), Event()
    calls, threads = [], []
    def probe():
        threads.append(current_thread().name)
        entered.set()
        assert release.wait(3)
        return True
    def factory(**kwargs):
        calls.append(kwargs)
        return Client(probe)
    monkeypatch.setattr(redis, 'Redis', factory)
    hub = RedisHub(host='synthetic.invalid', port=16379)
    try:
        assert hub.is_available() is False
        assert entered.wait(1)
        with ThreadPoolExecutor(max_workers=16) as workers:
            futures = [workers.submit(hub.is_available) for _ in range(100)]
            assert [future.result(timeout=1) for future in futures] == [False] * 100
        assert len(calls) == 1 and threads == ['redis-hub-reconnect']
        assert hub.check_sliding_window('synthetic', 1) is None
        assert hub.get_json('synthetic') is None
        assert hub.set_json('synthetic', {}) is False
        assert not release.is_set()
    finally:
        release.set()
        hub._reconnect_thread.join(2)
        hub._close()
    assert not hub._reconnect_thread.is_alive()


def test_successful_background_probe_publishes_only_after_full_setup(monkeypatch):
    entered, release = Event(), Event()
    def probe():
        entered.set()
        assert release.wait(3)
    client = Client(probe)
    monkeypatch.setattr(redis, 'Redis', lambda **kwargs: client)
    hub = RedisHub(host='synthetic.invalid', port=16379)
    try:
        assert hub.is_available() is False
        assert entered.wait(1) and hub.raw_client is None
        release.set()
        hub._reconnect_thread.join(2)
        assert hub.is_available() and hub.raw_client is client
        assert len(client.scripts) == 2
        assert hub.check_sliding_window('synthetic', 1) is True
        assert hub.record_violation('synthetic') == (False, 1)
        assert hub.set_json('synthetic', {'value': 1})
        assert hub.get_json('synthetic') == {'value': 1}
    finally:
        release.set()
        hub._close()


def test_cooldown_failure_does_not_launch_another_probe(monkeypatch):
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return Client(lambda: (_ for _ in ()).throw(redis.ConnectionError('synthetic')))
    monkeypatch.setattr(redis, 'Redis', factory)
    hub = RedisHub(host='synthetic.invalid', port=16379)
    try:
        assert hub.is_available() is False
        hub._reconnect_thread.join(2)
        assert not hub._probing and hub._circuit_open_until > time.monotonic()
        assert [hub.is_available() for _ in range(100)] == [False] * 100
        assert len(calls) == 1
    finally:
        hub._close()


def test_reset_during_pending_probe_cannot_publish_or_revive_old_singleton(monkeypatch):
    entered, release = Event(), Event()
    def probe():
        entered.set()
        assert release.wait(3)
        return True
    client = Client(probe)
    monkeypatch.setattr(redis, 'Redis', lambda **kwargs: client)
    hub = RedisHub(host='synthetic.invalid', port=16379)
    monkeypatch.setattr(RedisHub, '_instance', hub)
    try:
        assert hub.is_available() is False and entered.wait(1)
        RedisHub.reset_instance_for_testing()
        assert RedisHub._instance is None and hub._closed and hub.raw_client is None
        release.set()
        hub._reconnect_thread.join(2)
        assert hub.is_available() is False and hub.raw_client is None
        hub.mark_success(client)
        hub.mark_success()
        assert not hub._is_alive
        assert client.closed >= 1 and client.connection_pool.disconnected >= 1
    finally:
        release.set()
        hub._reconnect_thread.join(2)
        hub._close()


def test_successful_replacement_closes_old_pool_and_ignores_its_late_results(monkeypatch):
    first, second = Client(), Client()
    clients = iter((first, second))
    monkeypatch.setattr(redis, 'Redis', lambda **kwargs: next(clients))
    hub = RedisHub(host='synthetic.invalid', port=16379)
    try:
        assert hub.initialize() and hub.initialize()
        assert hub.raw_client is second and first.closed == 1 and first.connection_pool.disconnected == 1
        hub.mark_failure(RuntimeError('old response'), first)
        hub.mark_failure(RuntimeError('old response'), first)
        hub.mark_failure(RuntimeError('old response'), first)
        assert hub.is_available() and hub._consecutive_failures == 0
        hub.mark_failure(RuntimeError('current response'), second)
        hub.mark_success(first)
        assert hub._consecutive_failures == 1
    finally:
        hub._close()


def test_operation_uses_its_captured_client_and_cannot_reset_replacement_failures(monkeypatch):
    first, second = Client(), Client()
    clients = iter((first, second))
    monkeypatch.setattr(redis, 'Redis', lambda **kwargs: next(clients))
    hub = RedisHub(host='synthetic.invalid', port=16379)
    try:
        assert hub.initialize()
        def delayed_get(key):
            assert hub.initialize()
            hub.mark_failure(RuntimeError('new failure'), second)
            return '{"synthetic":true}'
        first.get = delayed_get
        assert hub.get_json('synthetic') == {'synthetic': True}
        assert hub.raw_client is second and hub._consecutive_failures == 1
    finally:
        hub._close()


def test_worker_start_failure_returns_fallback_and_sets_cooldown(monkeypatch):
    monkeypatch.setattr(Thread, 'start', lambda self: (_ for _ in ()).throw(RuntimeError('synthetic thread limit')))
    hub = RedisHub(host='synthetic.invalid', port=16379)
    assert hub.is_available() is False
    assert not hub._probing and hub._circuit_open_until > time.monotonic()
    hub._close()


def test_concurrent_singleton_initialization_performs_only_one_initial_probe(monkeypatch):
    calls, clients = [], []
    entered, release = Event(), Event()
    def probe():
        entered.set()
        assert release.wait(3)
    def factory(**kwargs):
        calls.append(kwargs)
        clients.append(Client(probe))
        return clients[-1]
    monkeypatch.setattr(redis, 'Redis', factory)
    monkeypatch.setattr(RedisHub, '_instance', None)
    try:
        with ThreadPoolExecutor(max_workers=8) as workers:
            futures = [workers.submit(RedisHub.get_instance) for _ in range(16)]
            assert entered.wait(1)
            release.set()
            hubs = [future.result(timeout=2) for future in futures]
        assert len(calls) == 1 and all(hub is hubs[0] for hub in hubs)
    finally:
        release.set()
        RedisHub.reset_instance_for_testing()


def test_native_refused_private_port_has_no_backoff_retry():
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        hub = RedisHub(host='127.0.0.1', port=reserved.getsockname()[1], socket_timeout=.05, socket_connect_timeout=.05)
        started = time.monotonic()
        try:
            assert hub.initialize() is False
            assert time.monotonic() - started < 1
        finally:
            hub._close()


def test_native_delayed_private_peer_times_out_once_without_retry():
    accepted, release = Event(), Event()
    connections = []
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(4)
        listener.settimeout(2)
        def peer():
            try:
                connection, _address = listener.accept()
                connections.append(connection)
                accepted.set()
                release.wait(2)
                connection.close()
            except OSError:
                pass
        worker = Thread(target=peer, daemon=True)
        worker.start()
        hub = RedisHub(host='127.0.0.1', port=listener.getsockname()[1], socket_timeout=.05, socket_connect_timeout=.05)
        started = time.monotonic()
        try:
            assert hub.initialize() is False and accepted.is_set()
            assert time.monotonic() - started < 1
            assert len(connections) == 1
        finally:
            hub._close()
            release.set()
            worker.join(2)
        assert not worker.is_alive()
