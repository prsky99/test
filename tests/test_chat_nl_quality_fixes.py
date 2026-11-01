"""Natural-language relevance fixes found by the 2026-10-26 operating-catalog evaluation."""
# ruff: noqa: F811 -- imported isolated pytest fixture
import json

import pytest

from agent_market.concierge import selection as sel
from agent_market.concierge.chat_task_spec import parse, tool_fit
from agent_market.concierge.discovery import normalize_task
from agent_market.concierge.protocols import requested_protocol
from agent_market.concierge.task_requirements import input_requirements_match, provider_identity
from tests.test_fast_single_recommendation import catalog, ask  # noqa: F401


# D3: a leading "search for X" keeps X as the capability object.
@pytest.mark.parametrize('task,core', [
    ('Search for papers', ['search', 'papers']),
    ('search for news about AI', ['search', 'news']),
    ('Can you look for weather in Seoul', ['weather']),
    ('web search for recent AI news', ['web', 'search']),       # a search with its own object
    ('find papers about climate', ['papers']),
    ('\u8ad6\u6587\u3092\u691c\u7d22\u3057\u3066. Search for papers', ['papers', 'search']),  # local alias precedes appended normalization
])
def test_seek_phrase_capability_terms(task, core):
    assert sel.capability_terms(task) == core


def test_normalized_prefix_keeps_its_separator():
    assert sel.capability_terms(normalize_task('find research papers with DOI metadata')) == ['academic', 'paper', 'search']


# D2: a PDF input requirement is direction-aware.
@pytest.mark.parametrize('description,status', [
    ('Extract structured data from an invoice PDF. Returns JSON.', 'match'),
    ('Reads invoices and receipts from PDF into structured JSON.', 'match'),
    ('Merge several PDFs into one PDF and return JSON metadata.', 'match'),
    ('PDF tools for invoices; returns JSON.', 'match'),                      # ambiguous stays as before
    ('Convert HTML or Markdown to a pixel-perfect PDF. Returns JSON.', 'mismatch'),
    ('Document transformation and PDF synthesis from JSON. Returns JSON.', 'mismatch'),
    ('Render a PDF report from JSON data and return JSON.', 'mismatch'),
])
def test_pdf_input_direction(description, status):
    spec = parse('convert a PDF invoice into structured JSON')
    assert tool_fit(spec, {'name': 'tool', 'description': description})['status'] == status


# D5: one no-credential definition for parsing and enforcement.
@pytest.mark.parametrize('task,expected', [
    ('find papers that must not require an API key', True),
    ('find papers; it should not need an API key', True),
    ("it doesn't need credentials", True),
    ('find papers, no authentication', True),
    ('a keyless weather API', True),
    ('find papers about API key management', False),
    ('explain authentication methods', False),
])
def test_no_api_key_paraphrases(task, expected):
    assert ('no_api_key' in parse(task).state()['required']) is expected
    keyed = {'kind': 'mcp', 'auth_observed': 1}
    assert input_requirements_match(task, keyed) is (not expected)


# D6: uncovered Korean content words trigger normalization; covered requests do not.
def test_untranslated_korean_words():
    assert sel.untranslated_words('배터리 재활용에 관한 논문을 찾아줘') == ['배터리', '재활용']
    assert sel.untranslated_words('서울 내일 날씨 알려줘') == []
    assert sel.untranslated_words('계약서에서 불리한 조항을 찾아주는 에이전트 추천해줘') == []
    assert sel.untranslated_words('find papers about battery recycling') == []


def test_partially_covered_korean_uses_the_rewriter(catalog):
    _, front, client, add, now = catalog
    add('Battery Papers', description='Search research papers about battery recycling.', report_at=now - 1,
        usage_guide=json.dumps({'tools': [{'name': 'search_papers', 'description': 'Search research papers about battery recycling.'}]}))
    calls = []
    def rewrite(text):
        calls.append(text)
        return 'Find research papers about battery recycling'
    front.concierge.query_rewriter = rewrite
    ask(client, '배터리 재활용에 관한 논문을 찾아줘')
    assert calls == ['배터리 재활용에 관한 논문을 찾아줘']
    ask(client, '서울 내일 날씨 알려줘')
    assert len(calls) == 1  # fully covered: zero-generation path


# D8: a protocol named as the subject is not a selector; x402 is never enabled by a topic.
@pytest.mark.parametrize('task,protocol', [
    ('find GitHub repositories about MCP servers', None),
    ('explain the A2A protocol specification', None),
    ('tutorials about x402 payments', None),
    ('MCP weather forecast', 'mcp'),
    ('list MCP servers for databases', 'mcp'),
    ('MCP tools about MCP servers', 'mcp'),
])
def test_topic_protocol_mentions(task, protocol):
    assert requested_protocol(task, {}) == protocol


# D1: demo tools, object-bound tools and unnamed platforms are not the requested capability.
def test_relevance_gate_rules():
    core, terms = ['translation'], ['translation', 'translate', 'english', 'text', 'korean']
    bound = lambda name: sel._bound_elsewhere(core, terms, {'name': name})
    assert bound('translate_quiz') and bound('address_translate') and bound('propose_translation')
    assert not bound('translate_text') and not bound('agentbit.ai_translate') and not bound('translate')
    assert sel._bound_elsewhere(['news'], ['technology', 'news'], {'name': 'tech_news'}) is False  # abbreviation
    assert sel._bound_elsewhere(['weather', 'forecast'], ['weather'], {'name': 'snow_forecast'}) is False  # two capability words
    assert not sel._real_tool({'name': 'translate_text_demo', 'description': 'Translate text.'})
    assert not sel._real_tool({'name': 'translate', 'description': 'Free demo on a fixed sample sentence.'})
    assert sel._real_tool({'name': 'python_documentation', 'description': 'Python API documentation and HTTP client examples.'})
    assert sel.capability_terms('영어 문장을 한국어로 번역해줘') == ['translation']
    whatsapp = {'name': 'extract_whatsapp', 'description': 'Transcribes voice notes from a WhatsApp export.'}
    assert not sel._platform_served({'youtube'}, {'name': 'FalaAI'}, whatsapp)
    assert sel._platform_served({'youtube'}, {'name': 'Tube'}, {'name': 'youtube_transcript', 'description': ''})


def test_object_bound_and_demo_tools_do_not_outrank_real_translators(catalog):
    _, _, client, add, now = catalog
    def tool(name, description):
        return json.dumps({'tools': [{'name': name, 'description': description,
                                      'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}}}]})
    add('Quiz Studio', description='Make and share quizzes.', report_at=now - 1,
        usage_guide=tool('translate_quiz', 'Translates a quiz into another language.'))
    add('Demo Hub', description='Agent tools.', report_at=now - 2,
        usage_guide=tool('translate_text_demo', 'Free demo of translate_text on a fixed sample sentence.'))
    real = add('Polyglot', description='Text translation between languages.', report_at=now - 600,
               usage_guide=tool('translate_text', 'Translate text between 100 languages.'))
    body = ask(client, 'translate English text to Korean', data={'protocol': 'mcp'})
    assert [item['id'] for item in body['data']['recommendations']] == [real]


def test_reverse_pdf_tools_are_not_pdf_readers(catalog):
    _, _, client, add, now = catalog
    def tool(name, description):
        return json.dumps({'tools': [{'name': name, 'description': description,
                                      'inputSchema': {'type': 'object', 'properties': {'url': {'type': 'string'}}}}]})
    add('Pdf Maker', description='Invoice PDF engine.', report_at=now - 1,
        usage_guide=tool('convert_invoice', 'Convert invoice JSON to a PDF and return JSON with a link.'))
    reader = add('Invoice Reader', description='Invoice extraction.', report_at=now - 600,
                 usage_guide=tool('extract_invoice', 'Extract structured JSON from an invoice PDF.'))
    body = ask(client, 'convert a PDF invoice into structured JSON', data={'protocol': 'mcp'})
    assert [item['id'] for item in body['data']['recommendations']] == [reader]


# D9: sibling hosts of one named provider count as one choice.
def test_provider_identity_across_sibling_hosts():
    a = provider_identity({'kind': 'a2a', 'name': 'ManyLives', 'url': 'https://manylives.me/.well-known/agent-card.json'})
    b = provider_identity({'kind': 'a2a', 'name': 'ManyLives', 'url': 'https://api.manylives.me/.well-known/agent-card.json'})
    c = provider_identity({'kind': 'a2a', 'name': 'ManyLives', 'url': 'https://other.example/agent'})
    assert a == b and a != c


# D4: a long narrative is summarized only when it found nothing; the summary is grounded.
LONG_REQUEST = ("I am planning a week of outdoor product photography and need help coordinating the schedule around "
                "the conditions. Our team will shoot on rooftops and in parks, and we want to avoid rain, strong wind and "
                "very low light. We usually prepare equipment the evening before, so a forecast that covers the next "
                "several days is more useful than only today. The location is Seoul, and it must not require an API key.")


@pytest.mark.parametrize('summary,valid', [
    ('weather forecast', True),
    ('multi-day forecast', True),
    ('weather forecast for Tokyo', False),      # a place the request never named
    ('forecast for 7 days', False),             # a number the request never stated
    ('book a hotel room', False),               # mostly ungrounded words
    ('forecast https://example.com', False),
    ('a very long query that keeps adding many more words beyond the limit', False),
])
def test_summary_validation(summary, valid):
    from agent_market.concierge.chat_query_rewrite import validate_summary
    assert (validate_summary(LONG_REQUEST, json.dumps({'task': summary})) is not None) is valid
    assert validate_summary(LONG_REQUEST, '{"task": 3}') is None and validate_summary(LONG_REQUEST, 'not json') is None


def test_long_request_without_results_uses_one_grounded_summary(catalog):
    _, front, client, add, now = catalog
    forecast = add('Forecaster', description='Weather forecast for any city.', report_at=now - 1,
                   usage_guide=json.dumps({'tools': [{'name': 'get_forecast', 'description': 'Multi-day weather forecast for any city.',
                                                      'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}}}]}))
    calls = []
    def summarize(text):
        calls.append(text)
        return 'weather forecast'
    front.concierge.query_summarizer = summarize
    body = ask(client, LONG_REQUEST, data={'protocol': 'mcp'})
    assert len(calls) == 1 and 'Seoul' in calls[0] and 'API key' in calls[0]  # the cleaned request, once
    assert [item['id'] for item in body['data']['recommendations']] == [forecast]
    assert body['data']['task_focus'] == 'weather forecast'
    assert 'no_api_key' in body['data']['task_spec']['required']  # conditions still come from the request
    ask(client, 'weather forecast for Seoul', data={'protocol': 'mcp'})
    assert len(calls) == 1  # short requests keep the zero-generation path


@pytest.mark.parametrize('task,paper_search', [
    ('Find a paper about battery recycling', True),          # normalized Korean/Japanese wording
    ('search papers on arXiv', True),
    ('find news articles about AI', False),
    ('paper airplane instructions', False),
])
def test_finding_papers_normalizes_to_paper_search(task, paper_search):
    assert normalize_task(task).startswith('academic paper search for ') is paper_search
