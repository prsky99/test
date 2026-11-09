"""The crawler's User-Agent names a reachable contact (2026-11-10): a2a-discovery.org has no MX record,
and the project does not use GitHub as a public channel."""
from pathlib import Path

from agent_market.gateway import crawler


def test_user_agent_points_to_the_service_and_a_mailbox_that_receives_mail():
    source = Path(crawler.__file__).read_text(encoding='utf-8')
    assert 'contact: contact@agentconcierge.biz' in source
    assert '+https://agentconcierge.biz/' in source
    assert 'a2a-discovery.org' not in source and 'github.com/a2a-discovery' not in source
