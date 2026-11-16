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


def test_role_task_input_maps_onto_parameter_names():
    from scripts.role_tool_test import case_arguments
    osv = tool(['ecosystem', 'name'], {'ecosystem': {'type': 'string'}, 'name': {'type': 'string'}, 'version': {'type': 'string'},
                                       'search_mode': {'type': 'string'}})
    args, missing = case_arguments(osv, {'ecosystem': 'npm', 'package': 'lodash', 'version': '4.17.20'})
    assert args == {'ecosystem': 'npm', 'name': 'lodash', 'version': '4.17.20'} and missing == []
    site = tool(['url'], {'url': {'type': 'string'}})
    assert case_arguments(site, {'domain': 'python.org'})[0] == {'url': 'https://python.org'}
    assert case_arguments(tool(['record_id'], {'record_id': {'type': 'string'}}), {'query': 'x'})[1] == ['record_id']


def test_case_input_wins_over_generic_values():
    args = role_arguments(tool(['cve_id'], {'cve_id': {'type': 'string'}}), 'cve.kev', case_input={'cve_id': 'CVE-2024-3094'})[0]
    assert args == {'cve_id': 'CVE-2024-3094'}


def test_events_use_coming_dates():
    from scripts.role_tool_test import coming_dates
    params = {'year': {'type': 'integer', 'default': 2020, 'minimum': 2020}, 'month': {'type': 'integer', 'minimum': 1}}
    args = role_arguments(tool(['year', 'month'], params), 'events.search')[0]
    soon = coming_dates()
    assert args == {'year': soon['year'], 'month': soon['month']} and args['year'] >= 2026


def test_new_role_task_inputs_map():
    from scripts.role_tool_test import case_arguments
    fx = tool(['base_currency', 'quote_currency'], {'base_currency': {'type': 'string'}, 'quote_currency': {'type': 'string'},
                                                    'amount': {'type': 'number'}})
    assert case_arguments(fx, {'amount': 100, 'from': 'USD', 'to': 'EUR'})[0] == {'base_currency': 'USD', 'quote_currency': 'EUR', 'amount': 100}
    wb = tool(['country', 'indicator_code'], {'country': {'type': 'string'}, 'indicator_code': {'type': 'string'},
                                              'year': {'type': 'integer'}})
    assert case_arguments(wb, {'country': 'KOR', 'indicator': 'population', 'year': 2023})[0] == \
        {'country': 'KOR', 'indicator_code': 'SP.POP.TOTL', 'year': 2023}
    wx = tool(['latitude', 'longitude'], {'latitude': {'type': 'number'}, 'longitude': {'type': 'number'}})
    assert case_arguments(wx, {'city': 'Seoul', 'latitude': 37.5665, 'longitude': 126.978})[0] == {'latitude': 37.5665, 'longitude': 126.978}


def test_rag_task_inputs_map():
    from scripts.role_tool_test import case_arguments
    assert case_arguments(tool(['iata'], {'iata': {'type': 'string'}}), {'code': 'ICN'})[0] == {'iata': 'ICN'}
    assert case_arguments(tool(['ip_address'], {'ip_address': {'type': 'string'}}), {'ip': '8.8.8.8'})[0] == {'ip_address': '8.8.8.8'}
    conv = tool(['value', 'from_unit', 'to_unit'], {'value': {'type': 'number'}, 'from_unit': {'type': 'string'}, 'to_unit': {'type': 'string'}})
    assert case_arguments(conv, {'value': 10, 'from': 'mile', 'to': 'kilometer'})[0] == {'value': 10, 'from_unit': 'mile', 'to_unit': 'kilometer'}


def test_a_parameter_the_catalog_input_cannot_fill_never_recurses():
    """11-14 09:12 launchd run: the fallback call re-read the catalog input and recursed into RecursionError."""
    tool = {'name': 'whois', 'required': ['domain', 'record_type'],
            'params': {'domain': {'type': 'string'}, 'record_type': {'type': 'string', 'enum': ['A', 'MX']}}}
    args, why = role_arguments(tool, 'domain.lookup', None)
    assert why is None and args['domain'] == 'python.org' and args['record_type'] == 'A'
    odd = {'name': 'odd', 'required': ['domain', 'zzqx'], 'params': {'domain': {'type': 'string'}, 'zzqx': {'type': 'object'}}}
    args, why = role_arguments(odd, 'domain.lookup', None)                   # nothing fills zzqx: a reason, no crash
    assert args is None and why.startswith('missing_args') and 'zzqx' in why   # recorded as skipped(missing_args)


def test_public_https_uses_the_project_check_and_refuses_shared_address_space(monkeypatch):
    """R16 (PM 11-15): the project check (ip.is_global) refuses 100.64.0.0/10, which the old private-range test let through."""
    import socket
    from scripts import role_tool_test as RT
    answers = {'cgnat.example': '100.64.1.2', 'public.example': '93.184.216.34'}
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, port, *a, **k: [(2, 1, 6, '', (answers[host], port))])
    assert not RT.public_https('https://cgnat.example/mcp')
    assert RT.public_https('https://public.example/mcp')
    assert not RT.public_https('http://public.example/mcp')


def test_a_task_input_that_reaches_no_parameter_is_skipped_not_replaced():
    """PM 11-16 10:5x (C): github-react-license gave search_repos query='model context protocol' (its example) and
    judged the answer against facebook/react's license; such a call is skipped as cannot fill."""
    search = tool(['query'], {'query': {'type': 'string', 'examples': ['model context protocol']},
                              'limit': {'type': 'integer'}})
    args, why = role_arguments(search, 'github.repo.v1', case_input={'repo': 'facebook/react'})
    assert args is None and why.startswith('missing_args: cannot fill query')
    # a task input that reaches one parameter still lets the generic fill supply the rest
    repo = tool(['repo', 'format'], {'repo': {'type': 'string'}, 'format': {'type': 'string', 'enum': ['json', 'text']}})
    assert role_arguments(repo, 'github.repo.v1', case_input={'repo': 'facebook/react'}) == \
        ({'repo': 'facebook/react', 'format': 'json'}, None)
