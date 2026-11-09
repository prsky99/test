"""Security and audit records keep only an IPv4 /24 (IPv6 /48) network and a client family (2026-11-10)."""
import collections
import threading

import pytest

from agent_market.privacy import coarse_ip, ua_family
from tests.test_fast_single_recommendation import catalog  # noqa: F401


@pytest.mark.parametrize('raw, coarse', [
    ('203.0.113.77', '203.0.113.0/24'),
    ('2001:db8:1234:5678::9', '2001:db8:1234::/48'),
    ('::ffff:198.51.100.23', '198.51.100.0/24'),
    ('fe80::1%en0', 'fe80::/48'),
    ('unknown', None), ('', None), (None, None), ('1.2.3.4; DROP', None),
])
def test_addresses_are_reduced_to_networks(raw, coarse):
    assert coarse_ip(raw) == coarse


@pytest.mark.parametrize('raw, family', [
    ('Mozilla/5.0 (Macintosh) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36', 'Chrome'),
    ('Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36 Edg/141.0', 'Edge'),
    ('Mozilla/5.0 (X11; Linux) Gecko/20100101 Firefox/133.0', 'Firefox'),
    ('Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)', 'ClaudeBot'),
    ('curl/8.7.1', 'curl'), ('python-httpx/0.28.1', 'python-httpx'),
    ('ops-check/1 (site owner test)', 'internal'), ('Mozilla/5.0 HeadlessChrome/141.0', 'headless'),
    ('something unusual', 'other'), ('', None), (None, None),
])
def test_user_agents_are_reduced_to_a_family(raw, family):
    assert ua_family(raw) == family


def test_security_events_store_networks_and_families(catalog):
    from agent_market.concierge.security import SecurityManager
    store = catalog[0]
    security = object.__new__(SecurityManager)
    security.store, security._lock, security._recent_events = store, threading.Lock(), collections.deque(maxlen=10)
    evt = security.log_event('probe', '203.0.113.77', '/wp-admin', 'GET',
                             'Mozilla/5.0 (X11; Linux) Gecko/20100101 Firefox/133.0', 'scan')
    assert evt['ip'] == '203.0.113.0/24' and evt['user_agent'] == 'Firefox'
    row = store.query("SELECT ip, user_agent FROM security_events WHERE event_type='probe'")[0]
    assert (row['ip'], row['user_agent']) == ('203.0.113.0/24', 'Firefox')
    assert '203.0.113.77' not in str(list(security._recent_events))


def test_admin_audit_logs_store_a_network(catalog):
    from agent_market.gateway import admin_auth
    store = catalog[0]
    with store.tx() as db:
        admin_auth.record_audit(db, 'staff', 'admin', 'LOGIN', 'login', '/admin', '198.51.100.23', 'SUCCESS')
    row = store.query("SELECT ip FROM admin_audit_logs WHERE username='staff' AND action='LOGIN'")[0]
    assert row['ip'] == '198.51.100.0/24'


def test_registration_consent_event_stores_a_network():
    import inspect
    from agent_market.concierge import registration_service
    assert 'coarse_ip(client_ip)' in inspect.getsource(registration_service)
