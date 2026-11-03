"""Chat retest (2026-10-27): focused listings first, task subjects, separate requests and guidance."""
# ruff: noqa: F811 -- imported isolated pytest fixture
import json

import pytest

from agent_market.concierge import selection as sel
from agent_market.concierge.chat_guidance import pronoun_reference, review, separate_requests
from tests.test_fast_single_recommendation import catalog, ask  # noqa: F401

ROOT_HTML = 'extracted_html.txt'


@pytest.mark.parametrize('task,core', [
    ('x402 stock quote API that costs under 1 cent', ['stock', 'quote', 'price']),
    ('What is the weather in Seoul today?', ['weather']),
    ('wether forcast for londn', ['weather', 'forecast']),
    ('Translate this contract into English', ['translate']),
])
def test_places_prices_and_documents_are_not_capabilities(task, core):
    assert sel.capability_terms(task) == core


def _tools(*names):
    return json.dumps([{'name': name, 'description': name.replace('_', ' ')} for name in names])


def test_a_bundle_is_not_focused_on_one_of_its_tools():
    bundle = {'kind': 'mcp', 'name': 'Agent Tollgate', 'description': '124 x402 tools for agents: crypto, swaps, finance, web, docs, AI.',
              'usage_tools': _tools('crypto_price', 'ai_translate', 'github_repo', 'hash')}
    focused = {'kind': 'mcp', 'name': 'Brainiall NLP', 'description': 'Translation and language tools.',
               'usage_tools': _tools('translate_text', 'detect_language', 'sentiment', 'summarize')}
    benefits = {'kind': 'mcp', 'name': 'Korea Benefits Eligibility',
                'description': 'Who qualifies for Korean government benefits. Plus public data and weather.',
                'usage_tools': _tools('benefits_match', 'weather_now', 'search_data', 'list_regions')}
    small = {'kind': 'mcp', 'name': 'dropcoin', 'description': 'Utilities.', 'usage_tools': _tools('extract_invoice')}
    assert not sel._service_focus(['translation'], bundle) and sel._service_focus(['translation'], focused)
    assert not sel._service_focus(['weather'], benefits)
    # A few tools are the server's purpose, but only for the task those tools actually perform.
    assert sel._service_focus(['invoice'], small)
    assert not sel._service_focus(['pdf', 'invoice', 'json'], small)


def test_ski_snow_services_do_not_answer_city_weather():
    snow = 'grounded conversational agent for ski & snow questions across 500+ resorts: live conditions, forecasts'
    assert not sel._weather_scope_matches(['weather', 'seoul'], snow)
    assert sel._weather_scope_matches(['snow', 'forecast', 'ski'], snow)


@pytest.mark.parametrize('description,expected', [
    ('Real-time stock quotes and prices for US listed companies.', True),
    ('Find products in stock with the best price.', False),
    ('Answers equity-compensation planning questions: stock options and AMT; share prices.', False),
    ('Live UK golf prices from every retailer that stocks it.', False),
])
def test_stock_quote_requests_need_market_prices(description, expected):
    resource = {'kind': 'a2a', 'name': 'Agent', 'description': description}
    terms = ['stock', 'price']
    assert sel.task_scope_matches(terms, resource, terms, tools=[]) is expected


@pytest.mark.parametrize('task,parts', [
    ('I need weather data, a translator and a stock price feed', ['weather data', 'a translator', 'a stock price feed']),
    ('weather forecast and alerts', []),
    ('Find a weather API', []),
])
def test_separate_requests(task, parts):
    assert separate_requests(task) == parts


@pytest.mark.parametrize('text,status', [
    ("Help me hack my neighbor's wifi", 'needs_authorized_task'),
    ('hack my own router for a security audit', None),
    ('make my business better', 'needs_goal'),
    ('Find a weather API', None),
])
def test_guidance(text, status):
    assert review(text) == status


def test_pronouns_refer_to_the_last_recommendation():
    assert pronoun_reference('how do I connect to it?') and pronoun_reference('tell me more about it')
    assert not pronoun_reference('Find weather agents')


def test_greeting_and_help_offer_examples(catalog):
    _, _, client, _, _ = catalog
    for text in ('hi', 'help'):
        body = ask(client, text)
        assert len(body['data']['examples']) >= 3 and 'For example' in body['reply']


def test_separate_requests_return_one_match_each(catalog):
    store, front, client, add, now = catalog
    add('Weather', description='Weather forecast API')
    add('Translator', description='Translate text between languages',
        usage_guide=json.dumps({'tools': [{'name': 'translate_text', 'description': 'Translate text between languages',
                                           'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}]}))
    body = ask(client, 'I need weather forecasts, a translator, and a stock price feed')
    parts = [item.get('request_part') for item in body['data']['recommendations']]
    assert parts[:2] == ['weather forecasts', 'a translator'] and body['data']['request_parts'] == parts


def test_no_match_points_to_explore_and_questions_are_explained(catalog):
    _, _, client, _, _ = catalog
    body = ask(client, 'find a PostgreSQL migration agent')
    assert body['data']['reason_code'] == 'no_eligible_match' and 'postgresql' in body['data']['explore_query']
    body = ask(client, "What's the capital of France?")
    assert body['data']['reason_code'] in ('out_of_scope', None) or body['data'].get('status') == 'needs_task'


def test_connect_to_it_continues_with_the_last_discussed_recommendation(catalog):
    store, front, client, add, now = catalog
    add('Weather One', description='Weather forecast API')
    add('Weather Two', description='Weather forecast service', last_ok_at=now - 5)
    first = ask(client, 'find a weather forecast API')
    token = first['visitor']['token']
    names = [item['name'] for item in first['data']['recommendations']]
    second = ask(client, 'what about the second one?', visitor_token=token)
    assert second['data']['recommendation']['name'] == names[1]
    third = ask(client, 'how do I connect to it?', visitor_token=token)
    assert third['data']['recommendation']['name'] == names[1] and 'Endpoint:' in third['reply']


def test_chat_cards_hide_unrecorded_evidence_and_explain_matches():
    html = open(ROOT_HTML).read()
    assert "'Not separately recorded'" not in html and ": 'No published report') + '</dd></div>'" not in html
    assert 'One of this service\'s tools, ' in html and 'Browse unverified listings in Explore' in html
    from agent_market.concierge.front import HTML
    assert HTML == html


def test_constraint_follow_ups_refine_the_list_and_keep_the_context(catalog):
    """QA 17: "which of these is free?" became a new task, failed, and erased the list for "the second one"."""
    store, front, client, add, now = catalog
    add('Weather One', description='Weather forecast API')
    add('Weather Two', description='Weather forecast service', last_ok_at=now - 5)
    first = ask(client, 'find a weather forecast API')
    token = first['visitor']['token']
    names = [item['name'] for item in first['data']['recommendations']]
    assert names
    for follow in ('show only free options that need no API key', 'which of these is free?'):
        body = ask(client, follow, visitor_token=token)
        assert body['data'].get('recommendations'), (follow, body['reply'])
        assert body['data'].get('status') != 'needs_task'
        assert body['reply'].startswith('Filtered for: ') and 'free to call' in body['reply'], body['reply']
    second = ask(client, 'the second one', visitor_token=token)
    assert 'Describe the task first' not in second['reply']


def test_a_request_without_a_task_offers_task_choices(catalog):
    # 11-04 review B6: the clarify reply names choices a person can tap and an agent can pick.
    from agent_market.concierge.fast_chat import CLARIFY_EXAMPLES
    _, _, client, _, _ = catalog
    body = ask(client, 'assistant')
    assert body['intent'] == 'clarify' and body['data']['status'] == 'needs_task'
    assert body['data']['examples'] == list(CLARIFY_EXAMPLES) == body['suggested_replies']
    assert all(3 <= len(value) <= 80 and value.isascii() for value in CLARIFY_EXAMPLES)  # operating.js chip filter
