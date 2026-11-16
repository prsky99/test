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
