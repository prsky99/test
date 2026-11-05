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
