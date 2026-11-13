"""PM 11-14 07:0x: the role tool is called with schema examples or public generic values, never personal data."""
from scripts.role_tool_test import role_arguments


def tool(required, params):
    return {'name': 't', 'required': required, 'params': params}


def test_schema_values_come_first():
    args, why = role_arguments(tool(['q'], {'q': {'type': 'string', 'examples': ['transformers']}}), 'papers.search')
    assert args == {'q': 'transformers'} and why is None


def test_role_generic_values():
    assert role_arguments(tool(['query'], {'query': {'type': 'string'}}), 'papers.search')[0] == {'query': 'large language models'}
    args = role_arguments(tool(['from', 'to'], {'from': {'type': 'string'}, 'to': {'type': 'string'}}), 'fx.rate')[0]
    assert args == {'from': 'USD', 'to': 'EUR'}
    assert role_arguments(tool(['package'], {'package': {'type': 'string'}}), 'package.metadata')[0] == {'package': 'react'}
    assert role_arguments(tool(['cve_id'], {'cve_id': {'type': 'string'}}), 'cve.kev')[0] == {'cve_id': 'CVE-2021-44228'}


def test_personal_data_and_unfillable_values_skip():
    assert role_arguments(tool(['email'], {'email': {'type': 'string'}}), 'news.search') == (None, 'personal-data parameter')
    assert role_arguments(tool(['record_id'], {'record_id': {'type': 'string'}}), 'news.search')[0] is None


def test_limits_are_one():
    args = role_arguments(tool(['query'], {'query': {'type': 'string'}, 'limit': {'type': 'integer'}}), 'news.search')[0]
    assert args == {'query': 'bitcoin', 'limit': 1}


def test_optional_subject_is_filled():
    params = {'entity_type': {'type': 'string', 'enum': ['works']}, 'search': {'type': 'string'}, 'cursor': {'type': 'string'},
              'search_mode': {'type': 'string'}}
    args = role_arguments(tool(['entity_type'], params), 'papers.search')[0]
    assert args == {'entity_type': 'works', 'search': 'large language models'}     # not search_mode
    osv = {'ecosystem': {'type': 'string'}, 'name': {'type': 'string'}, 'version': {'type': 'string'}}
    assert role_arguments(tool(['ecosystem'], osv), 'package.advisories')[0] == {'ecosystem': 'npm', 'name': 'lodash', 'version': '4.17.20'}


def test_refusals_are_not_success():
    from scripts.role_tool_test import refused
    assert refused('Seoul is not covered. Covered: the San Francisco Bay Area')
    assert refused('{ "error": "No NWS data for that point." }') and refused('')
    assert not refused('# Seoul *Capital and largest city of South Korea*')
    assert not refused('546 news items. ### Tron, Tether and Chainalysis Launch Digital Crime Task Force')


def test_fx_currency_pairs_differ():
    params = {'base_currency': {'type': 'string'}, 'quote_currency': {'type': 'string'}}
    assert role_arguments(tool(['base_currency', 'quote_currency'], params), 'fx.rate')[0] == {'base_currency': 'USD', 'quote_currency': 'EUR'}
