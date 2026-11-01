"""Public document errors and optimized images retain machine/security contracts."""
from pathlib import Path

import pytest
from tests.test_pearl_frontend import client


def test_document_not_found_is_html_but_api_not_found_remains_json(client):
    response=client.get('/missing-public-page',headers={'Accept':'text/html'})
    assert response.status_code==404
    assert response.headers['content-type'].startswith('text/html')
    assert 'Find your next connection.' in response.text
    assert 'href="/"' in response.text and 'noindex' in response.headers['x-robots-tag']
    assert 'missing-public-page' not in response.text
    for path in ('/api/missing-public-page','/internal/missing','/.well-known/missing','/mcp/missing'):
        reply=client.get(path,headers={'Accept':'text/html'})
        assert reply.status_code in (403,404)
        # API errors stay JSON: plain JSON or RFC 9457 problem details.
        assert reply.headers['content-type'].startswith(('application/json','application/problem+json'))
    assert client.get('/missing-public-page',headers={'Accept':'application/json'}).headers['content-type'].startswith(('application/json','application/problem+json'))


def test_optimized_pearl_has_a_budget_and_conditional_cache(client):
    path='/new/en/assets/pearl.webp'
    response=client.get(path)
    assert response.status_code==200
    assert response.headers['content-type']=='image/webp'
    assert len(response.content)<30000
    assert response.content.startswith(b'RIFF')
    tag=response.headers['etag']
    for value in (tag,'W/'+tag,'"other", '+tag,'*'):
        cached=client.get(path,headers={'If-None-Match':value})
        assert cached.status_code==304 and not cached.content
    assert client.get(path,headers={'If-None-Match':'"different"'}).status_code==200
    assert client.get('/new/en/assets/../private.webp').status_code==404


def test_build_keeps_runtime_html_synchronized_and_operating_art_small(client):
    import ast
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'agent_market/concierge/front.py').read_text())
    html=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HTML' for t in n.targets))
    assert html==(root/'extracted_html.txt').read_text()
    for name in ('index.html','explore.html','test.html','list-agent.html','about.html'):
        value=(root/'new/en'/name).read_text()
        assert 'pearl.png' not in value
    for name in ('styles.css','pearl-live.css','pearl-ui.js'):
        assert 'pearl.png' not in (root/'new/en/assets'/name).read_text()
