"""PM 11-18 (zero results are a target breach): "convert 250 Swiss franc to Japanese yen at today rate" found nothing on
the public find_agents, although general currency converters (Frankfurter: "Convert currencies and fetch blended FX
rates") were active. The currency names became required capability words ("swiss", "franc"), which a general converter
never lists. A request naming currencies is a currency conversion; the names stay search words, not requirements."""
import json

import pytest

from agent_market.concierge.discovery import normalize_task
from agent_market.concierge.selection import capability_terms
from tests.test_fast_single_recommendation import catalog  # noqa: F401 -- shared isolated catalog fixture

TOOL = {'name': 'convert_currency', 'description': 'Convert an amount between two currencies at the latest rate.',
        'inputSchema': {'type': 'object', 'properties': {'amount': {'type': 'number'}, 'from': {'type': 'string'},
                                                         'to': {'type': 'string'}}, 'required': ['amount', 'from', 'to']}}

ASKED = [
    'convert 250 Swiss franc to Japanese yen at today rate',
    'convert 250 Swiss francs to Japanese yen at today rate',
    'convert 90 Swedish kronor to euros',
    'how many Polish zlotys per dollar',
    'what is 40 British pounds in Indian rupees',
    'convert 250 CHF to JPY',
    'convert 40 British pounds to euros',       # 11-18 PM check: pounds next to convert was read as a weight
]


@pytest.mark.parametrize('task', ASKED)
def test_named_currencies_are_a_conversion_not_required_words(task):
    core = capability_terms(normalize_task(task))
    assert core[:2] == ['currency', 'conversion'], core


@pytest.mark.parametrize('task', [
    'stock price of Apple in dollars',            # one currency and no conversion: a price question
    'find a weather forecast for Japan',
    'real estate listings in Lisbon',             # "real" alone is no currency
    'who won the match yesterday',                # nor "won"
    'convert 150 pounds to kilograms',            # a weight
    'convert 5 pounds to kg',
    'how many pounds in 3 stone',
    'convert 1 bitcoin to dollars',               # crypto has its own price tools
])
def test_other_requests_are_not_rewritten(task):
    assert not normalize_task(task).startswith('currency conversion for ')


@pytest.mark.parametrize('task', ASKED)
def test_a_general_converter_is_recommended(catalog, task):  # noqa: F811
    _, front, _, add, now = catalog
    rid = add('Frankfurter', description='Convert currencies and fetch blended FX rates from 50+ institutional sources.',
              category='finance_crypto', report_at=now - 1, usage_guide=json.dumps({'tools': [TOOL]}))
    add('Weather', description='Weather forecast temperature API')
    assert [item['id'] for item in front.rec.search(task, kind='mcp')][:1] == [rid]
