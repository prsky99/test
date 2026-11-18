"""PM 11-18 12:5x: agents ask in question form, and the words that only make a question became required capability words,
so "how many pounds is 68 kilograms", "which airport has the code YVR and where is it" and "what does the English word
ephemeral mean" found nothing on the public find_agents. A question keeps its task words."""
import json

import pytest

from agent_market.concierge.discovery import normalize_task, question_task
from agent_market.concierge.selection import capability_terms
from tests.test_fast_single_recommendation import catalog  # noqa: F401 -- shared isolated catalog fixture


def tool(name, description, **properties):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': {k: {'type': v} for k, v in properties.items()},
                            'required': list(properties)}}


LISTINGS = {
    'units': ('UnitConvertLab', 'Convert units of length, weight, volume and temperature.',
              tool('convert_units', 'Convert a value between units such as kg, lb, km and miles.', value='number', **{'from': 'string', 'to': 'string'})),
    'airport': ('Airport Info', 'Airport lookup by IATA or ICAO code: name, city, country and coordinates.',
                tool('airport_info', 'Look up an airport by its IATA or ICAO code.', code='string')),
    'dictionary': ('Open Dictionary', 'English dictionary definitions, pronunciations and examples.',
                   tool('dictionary_define', 'Dictionary definition of an English word.', word='string')),
}


@pytest.mark.parametrize('task,listing', [
    ('how many pounds is 68 kilograms', 'units'),
    ('how many grams are in 3 pounds', 'units'),
    ('which airport has the code YVR and where is it', 'airport'),
    ('what does the English word ephemeral mean', 'dictionary'),
    ("what's the meaning of the word laconic", 'dictionary'),
])
def test_a_question_finds_the_listing_that_does_the_task(catalog, task, listing):  # noqa: F811
    _, front, _, add, now = catalog
    ids = {}
    for key, (name, description, spec) in LISTINGS.items():
        ids[key] = add(name, description=description, category='productivity', report_at=now - 1,
                       usage_guide=json.dumps({'tools': [spec]}))
    assert [item['id'] for item in front.rec.search(task, kind='mcp')][:1] == [ids[listing]]


@pytest.mark.parametrize('task,core', [
    ('how many pounds is 68 kilograms', ['convert', 'unit']),
    ('what does the English word ephemeral mean', ['dictionary', 'definition', 'ephemeral']),
    ('when does this domain expire', ['domain', 'expire']),
    ('what time is it right now in Kathmandu', ['time']),
])
def test_question_words_are_not_required_words(task, core):
    assert capability_terms(normalize_task(task)) == core


@pytest.mark.parametrize('task', ['what is it', 'how are you', 'weather forecast for Seoul tomorrow',
                                  'translate this paragraph into Spanish'])
def test_small_talk_and_commands_are_left_as_they_are(task):
    # a command is no question; a question with no task words left ("what is it") keeps its text
    assert question_task(task) is None


@pytest.mark.parametrize('task,kept', [
    ('what is the mean of these numbers', ['mean', 'numbers']),   # PM 11-18: a statistic, not a word to define
    ('who is the CEO of Apple', ['ceo', 'apple']),
    ('when is the next full moon', ['next', 'full', 'moon']),
])
def test_a_question_whose_words_are_the_task_keeps_them(task, kept):
    core = capability_terms(normalize_task(task))
    assert all(word in core for word in kept) and 'dictionary' not in core, core


def test_a_currency_question_stays_a_currency_conversion():
    assert capability_terms(normalize_task('how many Polish zlotys per dollar'))[:2] == ['currency', 'conversion']
