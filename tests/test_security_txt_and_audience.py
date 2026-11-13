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


def test_security_txt_is_publicly_cacheable():
    # Cloudflare cache rule "Agent discovery documents" (11-03) caches it only when the origin allows it.
    c = client()
    for path in ('/.well-known/security.txt', '/security.txt'):
        reply = c.get(path)
        assert reply.headers['cache-control'].startswith('public') and 'no-store' not in reply.headers['cache-control']


def test_agent_documents_stay_at_the_edge_and_are_served_stale_while_refreshing():
    c = client()
    # Discovery documents stay an hour at the edge (11-11 PM decision); security.txt keeps ten minutes.
    # 11-12: max-age, not s-maxage: Cloudflare serves no stale copy when s-maxage is present.
    for path, edge in (('/llms.txt', 3600), ('/.well-known/agent-card.json', 3600), ('/.well-known/security.txt', 600)):
        value = c.get(path).headers['cache-control']
        assert f'max-age={edge},' in value and 'stale-while-revalidate=' in value and 's-maxage' not in value, (path, value)
    # Search and catalog reads keep the short shared lifetime.
    assert 's-maxage' not in c.get('/api/overview').headers.get('cache-control', '')


def test_insights_snapshot_is_kept_five_minutes_at_the_edge_but_never_for_credentialed_requests():
    """PM 11-13 15:2x: /api/insights is the jobs snapshot rewritten every five minutes, the same for everyone.

    The edge and browsers keep it for one snapshot (max-age, not s-maxage: Cloudflare serves no stale copy with
    s-maxage). Requests with a cookie or Authorization keep no-store, and the body does not depend on them."""
    c = client()
    plain = c.get('/api/insights')
    value = plain.headers['cache-control']
    assert plain.status_code == 200 and 'max-age=300,' in value and 'stale-while-revalidate=300' in value
    assert value.startswith('public') and 's-maxage' not in value and 'set-cookie' not in plain.headers
    for headers in ({'Cookie': 'sid=abc'}, {'Authorization': 'Bearer x'}):
        reply = c.get('/api/insights', headers=headers)
        assert reply.headers['cache-control'] == 'no-store' and reply.json() == plain.json(), headers
    # Other public reads keep their short shared lifetime.
    assert 'max-age=30,' in c.get('/api/overview').headers['cache-control']


def test_agent_detail_is_kept_five_minutes_at_the_edge_but_never_for_credentialed_requests():
    """PM 11-13 22:3x: /api/agents/{id} answered in 80-190 ms at the origin but 1.3-9.8 s from Korea (no-store,
    DYNAMIC). It reads no request, so the edge may keep it five minutes; cookies and Authorization keep no-store."""
    from agent_market.concierge.public_http_contract import agent_detail_path, shared_path
    c = client()
    rid = c.app.state.front.store.query("SELECT id FROM resources WHERE active=1 ORDER BY id LIMIT 1")[0]['id']
    plain = c.get(f'/api/agents/{rid}')
    value = plain.headers['cache-control']
    assert plain.status_code == 200 and value == 'public, max-age=300, stale-while-revalidate=300'
    assert plain.headers['etag'].startswith('W/"') and 'set-cookie' not in plain.headers
    assert c.get(f'/api/agents/{rid}', headers={'If-None-Match': plain.headers['etag']}).status_code == 304
    for headers in ({'Cookie': 'sid=abc'}, {'Authorization': 'Bearer x'}):
        reply = c.get(f'/api/agents/{rid}', headers=headers)
        assert reply.headers['cache-control'] == 'no-store' and reply.json() == plain.json(), headers
    missing = c.get('/api/agents/999999999')
    assert missing.status_code == 404 and 'public' not in missing.headers.get('cache-control', '')
    assert agent_detail_path('/api/agents/42') and not agent_detail_path('/api/agents/42/reported')
    assert not agent_detail_path('/api/agents/') and not agent_detail_path('/api/agents/４２')
    assert shared_path('/api/feed/verified.json') and not shared_path('/api/feed/other.json')
