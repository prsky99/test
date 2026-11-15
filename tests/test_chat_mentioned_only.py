"""11-14 find_agents "get current weather for a city": MailerDot (342017), a city newsletter whose description says
weather but whose tools are list_cities and get_city, was second."""
from agent_market.concierge.fast_chat import mentioned_only_last


def _listing(i, name, description, tools):
    return {'id': i, 'name': name, 'description': description,
            'tools_schema': [{'name': n, 'description': d} for n, d in tools]}


FACE = _listing(1, 'Faceabot Weather', 'weather for a city', [('get_weather', 'Current weather for a city')])
MAILER = _listing(2, 'MailerDot', 'city newsletter with local news, weather and events',
                  [('list_cities', 'List cities'), ('get_city', 'Get a city newsletter')])
METEO = _listing(3, 'Meteo', 'forecasts', [('forecast', 'Weather forecast for a city')])


def test_a_listing_that_only_mentions_the_subject_goes_behind_the_tools_that_do_it():
    ids = lambda items: [item['id'] for item in items]
    task = 'get current weather for a city'
    assert ids(mentioned_only_last(task, [MAILER, FACE, METEO])) == [1, 3, 2]
    assert ids(mentioned_only_last(task, [FACE, MAILER, METEO])) == [1, 3, 2]
    assert ids(mentioned_only_last(task, [FACE, METEO, MAILER])) == [1, 3, 2]


def test_nothing_moves_without_known_tools_or_a_candidate_whose_tools_say_it():
    ids = lambda items: [item['id'] for item in items]
    no_tools = {'id': 9, 'name': 'Sky', 'description': 'weather'}
    assert ids(mentioned_only_last('get current weather for a city', [MAILER, no_tools])) == [2, 9]
    assert ids(mentioned_only_last('city newsletter', [MAILER, FACE])) == [2, 1]
