"""security.txt (RFC 9116) and the audience wording that names agents and their operators (11-03 review)."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from agent_market.concierge import engine
from agent_market.concierge.front import NOTICE, create_front_app
from tests.test_gateway import populated


def client():
    return TestClient(create_front_app(populated().app.state.front))


def test_security_txt_names_a_contact_and_a_near_expiry():
    c = client()
    for path in ('/.well-known/security.txt', '/security.txt'):
        reply = c.get(path)
        assert reply.status_code == 200 and reply.headers['content-type'].startswith('text/plain')
        fields = [line.split(': ', 1) for line in reply.text.strip().splitlines()]
        names = [name for name, _ in fields]
        assert 'Contact' in names and names.count('Expires') == 1 and 'Canonical' in names
        assert dict(fields)['Canonical'].endswith('/.well-known/security.txt')
        assert any(value.startswith('mailto:') for name, value in fields if name == 'Contact')
        expires = datetime.strptime(dict(fields)['Expires'], '%Y-%m-%dT%H:%M:%S.000Z').replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        assert now < expires < now + timedelta(days=365)  # RFC 9116: less than a year ahead


def test_audience_wording_includes_the_people_who_run_agents():
    assert 'not for humans' not in NOTICE and 'people who run them' in NOTICE
    assert 'humans are not the audience' not in engine.T['intro']
    card = client().get('/.well-known/agent-card.json').json()
    assert card['description'].startswith('FOR AI AGENTS.') and 'not for humans' not in card['description']
