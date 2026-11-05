"""Security review 11-05 finding 1: ids outside BIGINT answer 404, not 500."""
import pytest
from fastapi import HTTPException

from agent_market.concierge import front


class _Store:
    def query(self, sql, params):
        assert -9223372036854775808 <= params[0] <= 9223372036854775807, 'out-of-range id reached the database'
        return []


@pytest.mark.parametrize('rid', [0, -999, 9223372036854775808, -9223372036854775809, 10 ** 30])
def test_out_of_range_ids_are_not_found_without_a_query(rid):
    with pytest.raises(HTTPException) as caught:
        front.get_safe_agent_detail(_Store(), rid)
    assert caught.value.status_code == 404


def test_largest_bigint_still_reaches_the_lookup():
    with pytest.raises(HTTPException) as caught:
        front.get_safe_agent_detail(_Store(), 9223372036854775807)
    assert caught.value.status_code == 404


def test_demo_presets_keep_their_negative_ids():
    assert front.get_safe_agent_detail(_Store(), -1)['agent']['id'] == -1


# 11-05: a JSON null body was searched as the text "None" and returned an unrelated agent.
from tests.test_fast_single_recommendation import catalog  # noqa: E402,F401


@pytest.mark.parametrize('body', ['null', '0', 'true', '[1, 2]'])
def test_non_object_json_body_asks_for_a_task(catalog, body):
    _, _, client, _, _ = catalog
    response = client.post('/chat', content=body, headers={'Content-Type': 'application/json'})
    # Either "describe a task" (200) or "message required" (400); never a search for "None".
    assert response.status_code in (200, 400)
    assert not (response.json().get('data') or {}).get('recommendations')


def test_json_string_body_is_still_a_question(catalog):
    _, _, client, _, _ = catalog
    response = client.post('/chat', content='"weather forecast"', headers={'Content-Type': 'application/json'})
    assert response.status_code == 200


# 11-05 security review finding 6: no production branch trusts the literal peer name "testclient".
def test_testclient_peer_is_not_a_trusted_proxy():
    from starlette.datastructures import Headers
    from agent_market.gateway.deployment_security import forwarded_client, trusted_proxy_networks
    headers = Headers({'x-forwarded-for': '203.0.113.9'})
    assert forwarded_client('testclient', headers, trusted_proxy_networks()) == 'testclient'
    assert forwarded_client('127.0.0.1', headers, trusted_proxy_networks()) == '203.0.113.9'


def test_no_testclient_literal_in_production_code():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'agent_market'
    hits = [str(p) for p in root.rglob('*.py') if '"testclient"' in p.read_text() or "'testclient'" in p.read_text()]
    assert hits == []


# 11-05 security review finding 2: Explore cache entries keyed by search words stay only for the tab.
def test_search_word_cache_entries_use_session_storage():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / 'new/en/assets/operating.js').read_text()
    assert 'function swrStorage(key) { return swrHasSearchWords(key) ? sessionStorage : localStorage; }' in js
    assert 'swrStorage(key).getItem(SWR_STORAGE_KEY_PREFIX + key)' in js
    assert 'swrStorage(key).setItem(SWR_STORAGE_KEY_PREFIX + key, JSON.stringify(val))' in js
    assert 'localStorage.setItem(SWR_STORAGE_KEY_PREFIX' not in js
    # Entries left by earlier releases are removed on load.
    assert 'swrHasSearchWords(key.slice(SWR_STORAGE_KEY_PREFIX.length))) localStorage.removeItem(key);' in js
