"""PM 11-14 06:1x: pearl-first report batch, provider limits and the narrow A2A execution test."""
import json

from scripts import pearl_batch as PB


def test_metadata_tools_do_not_prove_a_task():
    assert not PB.is_work_tool('get_account') and not PB.is_work_tool('list_coverage') and not PB.is_work_tool('docs_health')
    assert PB.is_work_tool('get_forecast') and PB.is_work_tool('list_festivals') and not PB.is_work_tool('')


def test_pacer_limits_per_provider(tmp_path):
    now = [1000.0]
    slept = []
    pacer = PB.Pacer(day='20261114', state_dir=tmp_path, clock=lambda: now[0], sleep=slept.append)
    for _ in range(PB.PER_HOST_DAY):
        assert pacer.allowed('a.example')
        pacer.wait('a.example')
        pacer.called('a.example', 200)
        now[0] += 5
    assert not pacer.allowed('a.example')                       # 3 a day
    assert slept and all(gap > 0 for gap in slept)              # 60 s apart
    pacer.called('b.example', 429)
    assert not pacer.allowed('b.example')                       # a 429 ends the day for that provider
    pacer.called('c.example', 200, {'Retry-After': '120'})
    assert not pacer.allowed('c.example')
    again = PB.Pacer(day='20261114', state_dir=tmp_path)         # a second run the same day obeys the file
    assert not again.allowed('a.example') and again.allowed('d.example')
    assert again.allowed('d.example', a2a=True)
    again.called('d.example', 200, a2a=True)
    assert not again.allowed('d.example', a2a=True) and again.allowed('d.example')


def test_daily_room():
    pacer = PB.Pacer(day='x', state_dir=None)
    pacer.state['reports'] = PB.DAILY_LIMIT
    assert pacer.room() == 0


CARD = {'name': 'Weather agent', 'url': 'https://agent.example/a2a', 'skills': [
    {'id': 'book_table', 'name': 'Book a table', 'description': 'Reserve a restaurant table', 'examples': ['Book for two']},
    {'id': 'forecast', 'name': 'Weather forecast', 'description': 'Get the forecast for a city', 'examples': ['Weather in Paris tomorrow']},
]}


def test_a2a_skill_is_read_only_with_a_published_example():
    skill, example = PB.a2a_task_skill(CARD)
    assert skill['id'] == 'forecast' and example == 'Weather in Paris tomorrow'
    assert PB.a2a_task_skill({**CARD, 'securitySchemes': {'bearer': {}}}) is None     # authenticated cards are out
    no_example = {'skills': [{'id': 'forecast', 'name': 'Weather forecast', 'description': 'Get the forecast'}]}
    assert PB.a2a_task_skill(no_example) is None
    personal = {'skills': [{'id': 'lookup', 'name': 'Lookup', 'description': 'Find a contact',
                            'examples': ['Look up jane@example.com']}]}
    assert PB.a2a_task_skill(personal) is None
    sending = {'skills': [{'id': 'news', 'name': 'News search', 'description': 'Search news and send email digests',
                           'examples': ['latest AI news']}]}
    assert PB.a2a_task_skill(sending) is None


def test_a2a_message_body():
    body = PB.a2a_message('Weather in Paris', 'm1')
    assert body['method'] == 'message/send' and body['params']['message']['parts'][0]['text'] == 'Weather in Paris'
    json.dumps(body)


def test_a2a_reply_classes():
    done = {'result': {'kind': 'task', 'status': {'state': 'completed'},
                       'artifacts': [{'parts': [{'kind': 'text', 'text': 'Sunny, 21C'}]}]}}
    assert PB.classify_a2a_reply(done)[0] == 'completed'
    message = {'result': {'kind': 'message', 'parts': [{'kind': 'text', 'text': 'Sunny'}]}}
    assert PB.classify_a2a_reply(message)[:2] == ('completed', 'message')
    more = {'result': {'kind': 'task', 'status': {'state': 'input-required',
                                                  'message': {'parts': [{'kind': 'text', 'text': 'Which city?'}]}}}}
    assert PB.classify_a2a_reply(more)[:2] == ('stopped', 'input-required')
    assert PB.classify_a2a_reply({'result': {'kind': 'task', 'status': {'state': 'working'}}})[0] == 'stopped'
    assert PB.classify_a2a_reply({'error': {'code': -32601}})[0] == 'failed'
    assert PB.classify_a2a_reply(None)[0] == 'failed'
    long = {'result': {'kind': 'message', 'parts': [{'kind': 'text', 'text': 'x' * 10000}]}}
    assert len(PB.classify_a2a_reply(long)[2]) == PB.REPLY_KEEP
