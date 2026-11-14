"""Glama connector ownership (PM 11-14): /.well-known/glama.json serves the saved public claim only when it is exactly
{"$schema": "https://glama.ai/mcp/schemas/connector.json", "claim": "glama_claim_<20-64 letters/digits>"}; otherwise 404.
"""
import json

import pytest

from agent_market.concierge import growth_pages as g
from tests.test_pearl_frontend import client  # noqa: F401 - fixture

GOOD = {'$schema': 'https://glama.ai/mcp/schemas/connector.json', 'claim': 'glama_claim_' + 'a1B2' * 8}


@pytest.mark.parametrize('content, ok', [
    (json.dumps(GOOD), True),
    (json.dumps({**GOOD, 'claim': 'glama_claim_short'}), False),
    (json.dumps({**GOOD, '$schema': 'https://example.org/x.json'}), False),
    (json.dumps({**GOOD, 'extra': 1}), False),
    (json.dumps({**GOOD, 'claim': 'glama_claim_' + 'a' * 20 + '<script>'}), False),
    ('not json', False),
    (json.dumps({**GOOD, 'pad': 'x' * 2000}), False),
])
def test_only_the_exact_claim_document_is_served(tmp_path, content, ok):
    (tmp_path / 'glama.json').write_text(content)
    assert (g.glama_claim(lambda: tmp_path) == GOOD) is ok


def test_route_serves_json_with_a_short_public_cache_or_404(tmp_path, monkeypatch, client):  # noqa: F811
    monkeypatch.setattr(g, 'data_dir', lambda: tmp_path)
    assert client.get('/.well-known/glama.json').status_code == 404
    (tmp_path / 'glama.json').write_text(json.dumps(GOOD))
    r = client.get('/.well-known/glama.json')
    assert r.status_code == 200 and r.json() == GOOD and r.headers['content-type'].startswith('application/json')
    assert r.headers['cache-control'].startswith('public, max-age=300')
