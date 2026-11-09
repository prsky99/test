"""v2 audit trail minimises personal data and old records are deleted on schedule."""
from uuid import uuid4

import pytest

from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES, Access
from agent_market.ad_coin.v2.identity import Kind
from agent_market.ad_coin.v2.live_auth import PersistentCredentialResolver
from agent_market.ad_coin.v2.security_guards import (AUDIT_RETENTION_DAYS, CREDENTIAL_RETENTION_DAYS, AuditLogger,
                                                     EventType, client_class, coarse_ip, prune_credentials)
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

DAY_MS = 86_400_000
NOW = 1_800_000_000_000


@pytest.mark.parametrize('raw, stored', [
    ('203.0.113.77', '203.0.113.0/24'),
    ('2001:db8:abcd:12:1:2:3:4', '2001:db8:abcd::/48'),
    ('not an ip', None), ('', None), (None, None),
])
def test_ip_is_cut_to_the_network(raw, stored):
    assert coarse_ip(raw) == stored


@pytest.mark.parametrize('raw, stored', [
    ('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15', 'browser'),
    ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148', 'mobile_browser'),
    ('python-httpx/0.27', 'automated'), ('Googlebot/2.1', 'automated'), ('SomeClient/1', 'other'), (None, None),
])
def test_user_agent_becomes_a_coarse_class(raw, stored):
    assert client_class(raw) == stored


def test_audit_log_never_stores_raw_ip_or_user_agent(store):  # noqa: F811
    store.migrate_model()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36'
    AuditLogger.log(store, EventType.CAMPAIGN_ACTIVATED, 'succeeded', target_id=str(uuid4()),
                    client_ip='198.51.100.23', user_agent=ua, now_ms=NOW)
    row = AuditLogger.recent(store, limit=1)[0]
    assert row['client_ip'] == '198.51.100.0/24' and row['user_agent'] == 'browser'
    assert '198.51.100.23' not in str(row) and 'Chrome' not in str(row)


def test_audit_entries_older_than_retention_are_deleted(store):  # noqa: F811
    store.migrate_model()
    old, fresh = str(uuid4()), str(uuid4())
    AuditLogger.log(store, EventType.CAMPAIGN_ACTIVATED, 'succeeded', target_id=old,
                    now_ms=NOW - (AUDIT_RETENTION_DAYS + 1) * DAY_MS)
    AuditLogger.log(store, EventType.CAMPAIGN_ACTIVATED, 'succeeded', target_id=fresh,
                    now_ms=NOW - (AUDIT_RETENTION_DAYS - 1) * DAY_MS)
    assert AuditLogger.prune(store, now_ms=NOW, batch=1) >= 1
    targets = {row['target_id'] for row in AuditLogger.recent(store, limit=50)}
    assert old not in targets and fresh in targets


def test_ended_sessions_are_deleted_after_the_grace_period(store):  # noqa: F811
    store.migrate_model()
    access, resolver = Access(store), PersistentCredentialResolver(store)
    now_s = NOW / 1000
    tokens = {}
    for name, expires in (('long_ended', now_s - (CREDENTIAL_RETENTION_DAYS + 1) * 86400),
                          ('recently_ended', now_s - 86400), ('active', now_s + 3600)):
        principal, owner = str(uuid4()), str(uuid4())
        access.provision_principal(principal, Kind.HUMAN, owner_id=owner, capabilities=HUMAN_CAPABILITIES)
        tokens[name] = 'sess-' + str(uuid4())
        resolver.register_human_session(tokens[name], 'csrf-' + str(uuid4()), principal_id=principal,
                                        owner_id=owner, expires_at=expires)
    assert prune_credentials(store, now_ms=NOW) == 1
    for name, kept in (('long_ended', False), ('recently_ended', True), ('active', True)):
        found = store.one('human_session_get', (__import__('hashlib').sha256(tokens[name].encode()).hexdigest(),))
        assert (found is not None) == kept, name


def test_worker_daemon_applies_retention_hourly():
    from scripts.ad_coin_worker_daemon import WorkerDaemon as Daemon
    assert Daemon.PRUNE_INTERVAL_MS == 3_600_000
    assert 'prune_if_due' in Daemon.run_cycle.__code__.co_names
