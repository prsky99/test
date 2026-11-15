"""AgentPeering ownership badge (PM 11-15 16:57): /.well-known/agentpeering-verify returns the saved public value
(ap-verify-<32 hex>) as plain text only when public-pages/agentpeering-verify holds exactly it; otherwise 404."""
import pytest

from agent_market.concierge import growth_pages as g
from tests.test_pearl_frontend import client  # noqa: F401 - fixture

GOOD = 'ap-verify-' + '0123456789abcdef' * 2


@pytest.mark.parametrize('content, ok', [
    (GOOD, True), (GOOD + '\n', True),
    ('ap-verify-' + 'A' * 32, False), ('ap-verify-short', False), (GOOD + ' extra', False),
    ('<script>' + GOOD, False), (GOOD + 'x' * 200, False), ('', False),
])
def test_only_the_exact_value_is_served(tmp_path, content, ok):
    (tmp_path / 'agentpeering-verify').write_text(content)
    assert (g.agentpeering_value(lambda: tmp_path) == GOOD) is ok


def test_route_serves_plain_text_or_404(tmp_path, monkeypatch, client):  # noqa: F811
    monkeypatch.setattr(g, 'data_dir', lambda: tmp_path)
    r = client.get('/.well-known/agentpeering-verify')
    assert r.status_code == 404 and r.headers['cache-control'] == 'no-store'
    (tmp_path / 'agentpeering-verify').write_text(GOOD + '\n')
    r = client.get('/.well-known/agentpeering-verify')
    assert r.status_code == 200 and r.text == GOOD and r.headers['content-type'].startswith('text/plain')
