"""Discovery documents and their permanent aliases stay cacheable at the edge (2026-11-11)."""
from agent_market.concierge.public_http_contract import EDGE_DOCUMENTS, EDGE_REDIRECTS, shared_path


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
    assert spec.status_code == 200 and 's-maxage=3600' in spec.headers['cache-control']
    alias = client.get('/.well-known/mcp/server-card.json', follow_redirects=False)
    assert alias.status_code == 301 and 's-maxage=3600' in alias.headers['cache-control']
    for path in ('/llms.txt', '/skill.md', '/.well-known/agent-card.json'):
        assert 's-maxage=3600' in client.get(path).headers['cache-control'], path
    assert 's-maxage=600' in client.get('/robots.txt').headers['cache-control']  # changes more often
