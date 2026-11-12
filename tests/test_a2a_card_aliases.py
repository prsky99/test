"""11-12 (PM, funnel review): the A2A card is also served beside the /a2a endpoint.

Cloudflare showed /a2a/agent-card.json and /a2a/.well-known/agent-card.json answering 404 about 28 times a day
each: some A2A clients look for the card next to the endpoint. Both now return the same card as
/.well-known/agent-card.json, with the same edge cache policy and HEAD support; POST /a2a is unchanged.
"""
import pytest

from agent_market.concierge.public_http_contract import DISCOVERY_CACHE
from tests.test_security_txt_and_audience import client

ALIASES = ('/a2a/agent-card.json', '/a2a/.well-known/agent-card.json')


@pytest.mark.parametrize('path', ALIASES)
def test_the_alias_is_the_same_card_with_the_same_cache_policy(path):
    c = client()
    card, alias = c.get('/.well-known/agent-card.json'), c.get(path)
    assert alias.status_code == 200 and alias.headers['content-type'].startswith('application/json')
    assert alias.json() == card.json() and alias.json()['url'].endswith('/a2a')
    assert alias.headers['cache-control'] == card.headers['cache-control'] == DISCOVERY_CACHE
    head = c.head(path)
    assert head.status_code == 200 and not head.content


def test_the_a2a_endpoint_itself_is_unchanged():
    c = client()
    assert c.get('/a2a').status_code == 405
    assert c.get('/a2a/other.json').status_code == 404
