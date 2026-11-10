"""Search and AI crawlers verified by their operators' published IP lists are not jailed and get a
higher read limit; a copied User-Agent alone changes nothing (2026-11-10, ClaudeBot was jailed)."""
import collections
import json
import threading

import pytest

from agent_market.concierge import crawler_verify
from agent_market.concierge.crawler_verify import Verifier, claimed

LISTS = {
    'https://claude.com/crawling/bots.json': {'prefixes': [{'ipv4Prefix': '216.73.216.0/22'}]},
    'https://openai.com/gptbot.json': {'prefixes': [{'ipv4Prefix': '20.171.206.0/24'}]},
    'https://www.bing.com/toolbox/bingbot.json': {'prefixes': [{'ipv6Prefix': '2a01:111:f100::/48'}]},
}


def fake_fetch(url):
    if url in LISTS:
        return LISTS[url]
    raise OSError('unreachable')


@pytest.fixture
def verifier(tmp_path, monkeypatch):
    v = Verifier(cache=tmp_path / 'ranges.json', fetch=fake_fetch, background=False)
    monkeypatch.setattr(crawler_verify, '_VERIFIER', v)
    return v


CLAUDE_UA = 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)'


def test_names_are_read_from_the_user_agent():
    assert claimed(CLAUDE_UA) == 'ClaudeBot'
    assert claimed('Mozilla/5.0 (compatible; Claude-SearchBot/1.0)') == 'Claude-SearchBot'
    assert claimed('Mozilla/5.0 (compatible; GoogleOther)') == 'GoogleOther'
    assert claimed('Mozilla/5.0 Chrome/141') is None and claimed(None) is None


def test_only_a_listed_address_verifies_the_claimed_crawler(verifier):
    assert verifier.verified('216.73.216.44', CLAUDE_UA) == 'ClaudeBot'
    assert verifier.verified('203.0.113.9', CLAUDE_UA) is None          # copied User-Agent
    assert verifier.verified('216.73.216.44', 'GPTBot/1.1') is None      # another operator's range
    assert verifier.verified('20.171.206.7', 'Mozilla/5.0; GPTBot/1.1') == 'GPTBot'
    assert verifier.verified('2a01:111:f100:1::9', 'bingbot/2.0') == 'bingbot'
    assert verifier.verified('216.73.216.44', 'Mozilla/5.0 Chrome/141') is None


def test_lists_are_cached_in_a_file_and_a_failed_fetch_keeps_them(tmp_path):
    path = tmp_path / 'ranges.json'
    first = Verifier(cache=path, fetch=fake_fetch, background=False)
    assert first.verified('216.73.216.1', CLAUDE_UA) == 'ClaudeBot'
    assert json.loads(path.read_text())['ranges']['ClaudeBot']
    offline = Verifier(cache=path, fetch=lambda url: (_ for _ in ()).throw(OSError()), background=False,
                       clock=lambda: json.loads(path.read_text())['fetched_at'] + 10)
    assert offline.verified('216.73.216.1', CLAUDE_UA) == 'ClaudeBot'


def _manager(tmp_path):
    from agent_market.concierge.security import SecurityManager
    manager = object.__new__(SecurityManager)
    manager._lock = threading.Lock()
    manager._telemetry = collections.defaultdict(int)
    manager._allowed_ips, manager._banned_ips = set(), {}
    manager._violation_hits = collections.defaultdict(collections.deque)
    manager._trusted_proxy_networks = []
    manager.under_attack_mode, manager.auto_jail_enabled = False, True
    manager.auto_jail_threshold, manager.auto_jail_duration = 3, 900.0
    manager.rate_multiplier, manager._rules_loaded_at = 1.0, 1e18
    manager._recent_events = collections.deque(maxlen=50)
    manager.redis = type('NoRedis', (), {'is_available': staticmethod(lambda: False)})()
    manager.store = None
    banned = []
    manager.ban_ip = lambda ip, reason, duration_seconds=None: banned.append(ip)
    manager.log_event = lambda *a, **k: None
    return manager, banned


def test_a_verified_crawler_is_not_jailed_but_a_copied_user_agent_is(verifier, tmp_path):
    manager, banned = _manager(tmp_path)
    for _ in range(5):
        manager.record_violation('216.73.216.44', 'rate_limit_429', '/agent/1', 'GET', CLAUDE_UA, 'Read limit exceeded')
    assert banned == []
    for _ in range(5):
        manager.record_violation('203.0.113.9', 'rate_limit_429', '/agent/1', 'GET', CLAUDE_UA, 'Read limit exceeded')
    assert banned and set(banned) == {'203.0.113.9'}


def test_a_verified_crawler_gets_ten_times_the_read_limit_and_passes_bans(verifier, tmp_path):
    from agent_market.concierge.web_bot_auth import CLIENT_USER_AGENT
    manager, _ = _manager(tmp_path)
    hits = collections.defaultdict(collections.deque)
    token = CLIENT_USER_AGENT.set(CLAUDE_UA)
    try:
        allowed = sum(manager._sliding_check(hits, '216.73.216.44', 3, route='read') for _ in range(30))
        assert allowed == 30
        manager._banned_ips['216.73.216.44'] = None
        assert manager.is_blocked('216.73.216.44') == (False, None)
    finally:
        CLIENT_USER_AGENT.reset(token)
    other = sum(manager._sliding_check(hits, '203.0.113.9', 3, route='read') for _ in range(30))
    assert other == 3
    manager._banned_ips['203.0.113.9'] = None
    assert manager.is_blocked('203.0.113.9')[0] is True
