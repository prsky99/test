"""Discovery documents and their permanent aliases stay cacheable at the edge (2026-11-11)."""
from agent_market.concierge.public_http_contract import (DISCOVERY_CACHE, EDGE_DOCUMENT_CACHE, EDGE_DOCUMENTS,
                                                          EDGE_REDIRECTS, shared_path)


def test_openapi_and_alias_redirects_are_edge_documents():
    for path in ('/openapi.json', '/.well-known/llms.txt', '/.well-known/mcp/server-card.json', '/llms.txt', '/skill.md'):
        assert shared_path(path) and path in EDGE_DOCUMENTS
    assert EDGE_REDIRECTS == {'/.well-known/llms.txt', '/.well-known/mcp/server-card.json'}


def test_the_served_headers_allow_the_edge_to_keep_them():
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import create_front_app
    from tests.test_gateway import populated
    client = TestClient(create_front_app(populated().app.state.front))
    spec = client.get('/openapi.json')
    assert spec.status_code == 200 and spec.headers['cache-control'] == DISCOVERY_CACHE
    alias = client.get('/.well-known/mcp/server-card.json', follow_redirects=False)
    assert alias.status_code == 301 and alias.headers['cache-control'] == DISCOVERY_CACHE
    for path in ('/llms.txt', '/skill.md', '/.well-known/agent-card.json'):
        assert client.get(path).headers['cache-control'] == DISCOVERY_CACHE, path
    assert client.get('/robots.txt').headers['cache-control'] == EDGE_DOCUMENT_CACHE  # changes more often


def test_no_discovery_policy_turns_stale_while_revalidate_off():
    # 11-12: s-maxage made Cloudflare answer EXPIRED instead of UPDATING (proxy-revalidate semantics).
    for policy in (DISCOVERY_CACHE, EDGE_DOCUMENT_CACHE):
        assert 's-maxage' not in policy and 'revalidate,' not in policy and 'stale-while-revalidate=' in policy
