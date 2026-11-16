"""Capability admission rules observed on live recommendations (2026-10-20)."""
import json

from agent_market.concierge.selection import capability_terms, search_terms, task_scope_matches


def resource(description, tools, kind='a2a', name='Agent'):
    return {'kind': kind, 'name': name, 'description': description,
            'usage_tools': json.dumps(tools)}


def admits(task, item):
    return task_scope_matches(search_terms(task), item, capability_terms(task))


BOILERPLATE = 'Agents pay for work and prove what happened.'


def test_skill_names_with_copied_marketing_text_are_not_capability_evidence():
    item = resource(BOILERPLATE, [{'name': name, 'description': BOILERPLATE}
                                  for name in ('Research Paper', 'Trust Report', 'Agent ID Issue', 'Check Url')])
    assert not admits('find recent research papers about battery recycling', item)


def test_paper_search_agent_is_admitted_without_mentioning_the_topic():
    item = resource('ArXiv AI/CS paper search with structured digests.',
                    [{'name': 'ArXiv AI/CS Paper Search', 'description': 'Search arXiv papers and return a digest.'}])
    assert capability_terms('find recent research papers about battery recycling') == ['papers']
    assert admits('find recent research papers about battery recycling', item)


def test_crypto_only_market_tool_does_not_serve_a_stock_request():
    item = resource('Web search; point-in-time crypto market state; point-in-time news.',
                    [{'name': 'Point-in-time market state', 'description': 'Crypto perpetual futures and prediction-market odds.'},
                     {'name': 'Web search', 'description': 'Live web pages for a query.'}])
    assert not admits('latest stock market news', item)
    equity = resource('US market data.', [{'name': 'Stock quotes', 'description': 'Latest stock market prices and news for NYSE tickers.'}])
    assert admits('latest stock market news', equity)


def test_a_union_of_unrelated_tools_is_not_one_capability():
    item = resource('Translate text, search the web and read pages for agents.',
                    [{'name': f'Tool {n}', 'description': d} for n, d in enumerate(
                        ('Search the live web for a query.', 'Read a page as markdown.', 'Take a screenshot.', 'Company facts from a domain.'))])
    assert not admits('translate text to French', item)
    translator = resource('Language tools.', [{'name': 'translate', 'description': 'Translate text between languages.'}])
    assert admits('translate text to French', translator)


def test_generic_verbs_do_not_carry_a_match():
    assert capability_terms('send an email') == ['send', 'email']
    item = resource('Speech to text API.', [{'name': 'Get an API key', 'description': 'Request a key for the transcription API.'},
                                            {'name': 'Transcribe', 'description': 'Transcribe audio files.'}])
    assert not admits('send an email', item)


def test_single_tool_listing_may_reuse_its_description():
    item = resource('Weather forecast temperature API', [{'name': 'forecast', 'description': 'Weather forecast temperature API'}], kind='mcp')
    assert admits('find an MCP weather forecast API', item)


def test_exact_agent_name_search_lists_that_agent_first():
    from agent_market.concierge.front import _exact_name_first
    rows = [{'id': 1, 'name': 'Citeerbaar'}, {'id': 2, 'name': 'Weather & Geo Intel MCP'}, {'id': 3, 'name': 'Weather & Geo Intel MCP Pro'}]
    ordered = _exact_name_first('weather & geo intel mcp', rows[:1], rows, 45)
    assert [r['id'] for r in ordered] == [2, 3, 1]
    assert _exact_name_first('ab', rows[:1], rows, 45) == rows[:1]


# Live cases, 2026-10-21: a matching word in a catalog, account or usage note is not the task.

def test_catalog_search_tool_is_not_a_web_search_capability():
    apex = resource('Web page extraction in a real headless Chrome and token exit checks.',
                    [{'name': 'APEX Market: find a paid API for anything', 'description': 'One search over every paid x402 API we can see on the web.'},
                     {'name': 'Web page to text in a real browser', 'description': 'Render any public web page and return its visible text.'}])
    assert not admits('search the web for recent AI news', apex)
    directory = resource('Agent directory.', [{'name': 'Find an agent', 'description': 'Search all listed agents for web search and more.'}])
    assert not admits('web search', directory)
    search = resource('Research tools.', [{'name': 'Web Search / Research (one call)', 'description': 'Search the live web and return cited results.'}])
    assert admits('search the web for recent AI news', search)


def test_account_tools_and_usage_notes_are_not_task_evidence():
    whisper = resource('Speech recognition service.', [{'name': 'Get a Whisper API key', 'description': 'Request a key; we email it to you.'},
                                                    {'name': 'identify', 'description': 'Identify the caller by email.'}])
    assert not admits('send an email', whisper)
    noted = resource('Provider enrollment checks.', [{'name': "Check providers' enrollment records", 'description': 'Send an email and a list of NPIs to the endpoint.'},
                                                    {'name': 'Weekly follow-up', 'description': 'Send an email and a roster to the endpoint.'}])
    assert not admits('send an email', noted)
    aside = resource('Small agency.', [{'name': 'Send a job request', 'description': "Sends a job request (only with the user's ok to share their email)."},
                                       {'name': 'Offers', 'description': 'Current offers.'}])
    assert not admits('send an email', aside)
    mailer = resource('Local tools.', [{'name': 'Email', 'description': 'Send an email through the configured account.'},
                                       {'name': 'Calendar', 'description': 'Create calendar events.'}])
    assert admits('send an email', mailer)


def test_two_capability_words_must_name_one_tool_and_targets_are_parameters():
    assert capability_terms('convert currency from USD to EUR') == ['convert', 'currency']
    assert capability_terms('translate text to French') == ['translate']
    rental = resource('Car rental.', [{'name': 'Check live car availability and prices', 'description': 'Prices in EUR or USD.'},
                                      {'name': 'Book a car', 'description': 'Reserve a vehicle.'}])
    assert not admits('convert currency from USD to EUR', rental)
    translator = resource('AI tools.', [{'name': 'Translate', 'description': 'Translation between 100 languages.'},
                                        {'name': 'Summarize', 'description': 'Summarize a document.'}])
    assert admits('translate text to French', translator)


def test_word_forms_match_and_named_account_words_are_kept():
    extractor = resource('Document AI.', [{'name': 'Document Transcription and Extraction', 'description': 'Transcribe audio or extract fields from a PDF.'},
                                          {'name': 'Status', 'description': 'Service status.'}])
    assert admits('transcribe an audio file', extractor)
    quotes = resource('US market data.', [{'name': 'Stock quotes', 'description': 'Latest stock market prices and news for NYSE tickers.'},
                                          {'name': 'Run SQL', 'description': 'Query the dataset.'}])
    assert admits('latest stock market news', quotes)


def test_workflow_proposals_name_unsupported_actions_but_not_topics():
    from agent_market.workspace_goal_coverage import missing
    docs = ('docs.search.v1',)
    assert missing('Book a flight from Seoul to Tokyo', docs) == ['Booking, purchasing or payments']
    assert missing('Compare prices of the iPhone 16 and Galaxy S25', docs) == ['Product comparison']
    assert 'Sending messages or publishing' in missing('Find battery research and email me the results', docs)
    assert missing('Find research papers about payment fraud detection', docs) == []
    assert missing('Search documentation for sending email with SMTP', docs) == []
