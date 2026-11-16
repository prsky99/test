"""PM 11-16 source review 3.5: the per-request security checks (sync Redis and database calls) leave the event loop,
and the 30-second rule reload never makes a request wait for the database."""
import threading
import time

from tests.test_concierge import w  # noqa: F401 (fixture)


def test_the_checks_run_on_their_own_pool_not_the_event_loop(w, monkeypatch):  # noqa: F811
    world, c, _ = w
    security = world.app.state.front.security
    seen = []
    real = security.is_blocked
    monkeypatch.setattr(security, 'is_blocked', lambda ip: seen.append(threading.current_thread().name) or real(ip))
    r = c.get('/new/en/index.html')
    assert r.status_code == 200 and seen and all(name.startswith('security-check') for name in seen), seen


def test_rate_limit_headers_still_reach_the_response(w):  # noqa: F811
    _, c, _ = w
    r = c.get('/llms.txt')
    assert r.status_code == 200 and 'RateLimit-Policy' in r.headers and 'RateLimit' in r.headers


def test_a_banned_address_is_still_refused(w, monkeypatch):  # noqa: F811
    world, c, _ = w
    security = world.app.state.front.security
    seen = []
    real = security.is_blocked
    monkeypatch.setattr(security, 'is_blocked', lambda ip: seen.append(ip) or real(ip))
    assert c.get('/llms.txt').status_code == 200 and seen   # the address the app resolves for the test client
    with security._lock:
        security._allowed_ips.discard(seen[0])
        security._banned_ips[seen[0]] = None
        security._rules_loaded_at = time.time()
    r = c.get('/llms.txt')
    assert r.status_code == 403 and r.json()['error_code'] == 'ACCESS_BLOCKED'


def test_a_stale_rule_set_reloads_in_the_background_once(w, monkeypatch):  # noqa: F811
    world, _, _ = w
    security = world.app.state.front.security
    started, release, threads = threading.Event(), threading.Event(), []

    def slow_reload():
        threads.append(threading.current_thread().name)
        started.set()
        release.wait(5)
        security._rules_loaded_at = time.time()
    monkeypatch.setattr(security, 'reload_rules', slow_reload)
    security._rules_loaded_at = 0.0
    t = time.perf_counter()
    for _ in range(20):
        assert security.is_blocked('203.0.113.9') == (False, None)
    assert time.perf_counter() - t < 0.5                      # no request waited for the reload
    assert started.wait(2) and threads == ['security-rules-reload']   # one reload at a time, off the request
    release.set()
    for _ in range(50):
        if not security._rules_refreshing:
            break
        time.sleep(0.02)
    assert security._rules_refreshing is False and len(threads) == 1


def test_no_path_lets_a_banned_address_through(w, monkeypatch):  # noqa: F811
    """PM 11-17 fail closed: a banned address is refused when the checks run, when they raise, when the pool is full
    (the request waits for a free worker) and when the wait runs out (503); it never gets the page."""
    import agent_market.concierge.front as front_module
    world, c, _ = w
    security = world.app.state.front.security
    seen = []
    real = security.is_blocked
    monkeypatch.setattr(security, 'is_blocked', lambda ip: seen.append(ip) or real(ip))
    assert c.get('/llms.txt').status_code == 200
    with security._lock:
        security._allowed_ips.discard(seen[0])
        security._banned_ips[seen[0]] = None
        security._rules_loaded_at = time.time()

    assert c.get('/llms.txt').status_code == 403                              # checks run

    def broken(ip):
        raise RuntimeError('redis down')
    monkeypatch.setattr(security, 'is_blocked', broken)
    assert c.get('/llms.txt').status_code == 500                              # an error in the checks refuses
    monkeypatch.setattr(security, 'is_blocked', real)

    hold = threading.Event()
    busy = [front_module._SECURITY_POOL.submit(hold.wait, 10) for _ in range(8)]
    try:
        result = {}
        t = threading.Thread(target=lambda: result.setdefault('r', c.get('/llms.txt')))
        t.start()
        t.join(0.5)
        assert t.is_alive() and 'r' not in result                             # a full pool queues, it does not skip
        hold.set()
        t.join(5)
        assert result['r'].status_code == 403
    finally:
        hold.set()
        for f in busy:
            f.result(5)

    hold = threading.Event()
    monkeypatch.setattr(front_module, 'SECURITY_WAIT_S', 0.2)
    busy = [front_module._SECURITY_POOL.submit(hold.wait, 10) for _ in range(8)]
    try:
        r = c.get('/llms.txt')
        assert r.status_code == 503 and r.headers['Retry-After'] == '5'       # the wait ran out: refused, not served
    finally:
        hold.set()
        for f in busy:
            f.result(5)


def test_a_failed_reload_keeps_the_last_rules(w, monkeypatch):  # noqa: F811
    world, _, _ = w
    security = world.app.state.front.security
    with security._lock:
        security._banned_ips['198.51.100.7'] = None
        security._allowed_ips.add('198.51.100.8')
    loaded_at = security._rules_loaded_at

    def down(*a, **k):
        raise RuntimeError('database down')
    monkeypatch.setattr(security.store, 'query', down)
    security.reload_rules()
    assert '198.51.100.7' in security._banned_ips and '198.51.100.8' in security._allowed_ips
    assert security._rules_loaded_at == loaded_at
    assert security.is_blocked('198.51.100.7')[0] is True


def test_every_reply_splits_its_time_for_measurement(w):  # noqa: F811
    _, c, _ = w
    timing = c.get('/llms.txt').headers['Server-Timing']
    names = [part.split(';')[0].strip() for part in timing.split(',')]
    assert {'secq', 'sec', 'app', 'gc'} <= set(names) and names.count('gc') == 1, timing
    explore = c.get('/api/explore?q=weather').headers.get('Server-Timing', '')
    assert 'secq;' in explore and [p.split(';')[0].strip() for p in explore.split(',')].count('gc') <= 1, explore
