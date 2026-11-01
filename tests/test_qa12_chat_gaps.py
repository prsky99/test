"""Improvement check round 12: Chat requests that name a product or a gerund, not a task."""
import json

from agent_market.concierge.fast_chat import retrieval_text
from tests.test_fast_single_recommendation import catalog  # noqa: F401


def tool_guide(name, description, *fields):
    fields = fields or ('q',)
    schema = {'type': 'object', 'properties': {field: {'type': 'string'} for field in fields}, 'required': list(fields)}
    return json.dumps({'tools': [{'name': name, 'description': description, 'inputSchema': schema}]})


def test_retrieval_text_names_the_implied_capability_only():
    assert retrieval_text('find a PostgreSQL MCP server') == 'find a postgres MCP server database'
    assert retrieval_text('PostgreSQL database') == 'postgres database'
    assert retrieval_text('postgres MCP').endswith(' database')
    # A request that already names the task is searched as written.
    assert retrieval_text('query my postgres database') == 'query my postgres database'
    assert retrieval_text('redis cache MCP') == 'redis cache MCP'
    assert retrieval_text('email sending MCP server') == 'send email MCP server'
    assert retrieval_text('sending invoices') == 'send invoices'
    assert retrieval_text('weather in Seoul') == 'weather in Seoul'


def test_bare_database_product_request_finds_a_database_tool(catalog):
    _, _, client, add, now = catalog
    add('Data Gateway', description='Read-only SQL access to a Postgres database.', report_at=now - 5,
        usage_guide=tool_guide('postgres__sql_read', 'Run a read-only SQL query against a Postgres database.'))
    add('postgres compose generator', description='Generate docker compose files for postgres and redis.', report_at=now - 1,
        usage_guide=tool_guide('invoke', 'Generate a docker compose file for postgres and redis.'))
    body = client.post('/chat', json={'message': 'find a PostgreSQL MCP server'}).json()
    names = [item['name'] for item in body['data']['recommendations']]
    assert names and names[0] == 'Data Gateway', body['reply']


def test_email_sending_prefers_tools_that_send(catalog):
    _, _, client, add, now = catalog
    add('Mail Check', description='Validate an email address before sending.', report_at=now - 1,
        usage_guide=tool_guide('validate_email', 'Validate an email address before sending.'))
    add('Mail Sender', description='Send an email message to a recipient.', report_at=now - 5,
        usage_guide=tool_guide('send_email', 'Send an email message to a recipient.', 'to', 'subject', 'body'))
    body = client.post('/chat', json={'message': 'email sending MCP server'}).json()
    names = [item['name'] for item in body['data']['recommendations']]
    assert names and names[0] == 'Mail Sender', body['reply']


def test_openapi_lists_every_agent_v1_path_named_in_llms_txt(catalog):
    import re
    _, _, client, _, _ = catalog
    paths = client.get('/openapi.json').json()['paths']
    named = set(re.findall(r'/api/agent/v1/[\w./{}-]+', client.get('/llms.txt').text))
    named = {path.rstrip('.').replace('{{', '{').replace('}}', '}') for path in named}
    assert named and {'/api/agent/v1/entry', '/api/agent/v1/openapi.json',
                      '/api/agent/v1/badge/{resource_id}.svg'} <= named
    assert named <= set(paths), sorted(named - set(paths))


def test_every_category_page_explains_itself(catalog):
    import re
    from agent_market.broker.categories import CATEGORIES
    _, _, client, _, _ = catalog
    for category, definition in CATEGORIES.items():
        page = client.get('/agents/category/' + category).text
        body = re.sub(r'(?s)<(script|style|head)\b.*?</\1>', '', page)
        words = re.sub(r'<[^>]+>', ' ', body).split()
        assert len(words) >= 150, (category, len(words))
        assert 'How these listings are checked' in page
        assert re.search(r'[가-힯]', page) is None


def test_channel_after_on_names_the_capability():
    assert retrieval_text('alert me on Telegram') == 'send Telegram message'
    assert retrieval_text('notify us via Slack') == 'send Slack message'


def test_two_named_capabilities_get_one_match_each(catalog):
    _, _, client, add, now = catalog
    add('Page Watch', description='Monitor a website and report when the page changes.', report_at=now - 1,
        usage_guide=tool_guide('monitor_website', 'Monitor a website page for changes.', 'url'))
    add('Site Monitor Two', description='Monitor website pages on a schedule.', report_at=now - 2,
        usage_guide=tool_guide('monitor_site', 'Monitor a website on a schedule.', 'url'))
    add('Telegram Relay', description='Send a message to a Telegram chat.', report_at=now - 5,
        usage_guide=tool_guide('send_message', 'Send a Telegram message to a chat.', 'chat_id', 'text'))
    body = client.post('/chat', json={'message': 'monitor my website and alert me on telegram when it goes down'}).json()
    items = body['data']['recommendations']
    assert [item['name'] for item in items] == ['Page Watch', 'Telegram Relay'], body['reply']
    assert [item['request_part'] for item in items] == ['monitor my website', 'alert me on telegram when it goes down']


def test_one_capability_with_a_condition_is_not_split(catalog):
    _, _, client, add, now = catalog
    add('Weather', report_at=now - 1)
    body = client.post('/chat', json={'message': 'weather forecast and alerts'}).json()
    assert all('request_part' not in item for item in body['data']['recommendations'])


def test_matches_for_the_first_part_make_room_for_the_second():
    from types import SimpleNamespace
    from agent_market.concierge.fast_chat import FastConcierge
    relay = {'id': 9, 'name': 'Telegram Relay', 'description': 'Send a Telegram message.', 'tools': ['send_message']}
    searched = []

    shiftmoor = {'id': 1, 'name': 'Shiftmoor', 'description': 'Website change monitor.', 'tools': ['check_page']}

    def search(text, **options):
        searched.append(text)
        return [relay] if 'telegram' in text else [shiftmoor] if 'website' in text else []
    owner = SimpleNamespace(rec=SimpleNamespace(search=search))
    # The whole sentence ranked a competitor tracker first; the part's own search prefers Shiftmoor.
    first = [{'id': 2, 'name': 'Competitor Monitor', 'description': 'Monitor competitor website pages.', 'tools': ['watch']},
             {'id': 1, 'name': 'Shiftmoor', 'description': 'Website change monitor.', 'tools': ['check_page']}]
    task = 'monitor my website and alert me on telegram when it goes down'
    items, parts = FastConcierge._cover_parts(owner, task, first, None, set())
    assert [item['name'] for item in items] == ['Shiftmoor', 'Telegram Relay']
    assert parts == ['monitor my website', 'alert me on telegram when it goes down']
    assert searched == ['monitor my website', 'send telegram message']
    # Nothing serves the second part: the original matches stay.
    owner.rec.search = lambda text, **options: []
    assert FastConcierge._cover_parts(owner, task, first, None, set()) == (first, [])


def test_root_varies_on_accept_for_every_representation(catalog):
    _, _, client, _, _ = catalog
    for accept in ('text/html', 'text/markdown', 'application/json'):
        response = client.get('/', headers={'Accept': accept})
        assert response.status_code == 200, accept
        assert 'accept' in response.headers.get('vary', '').lower().split(', '), accept


def test_tool_descriptions_do_not_steer_the_calling_agent():
    import re
    from agent_market.concierge.mcp_contract import mcp_tools
    bossy = [tool['name'] for tool in mcp_tools() if re.search(r'(?i)always call|call this first|ignore (all|previous)|start here', tool['description'])]
    assert not bossy
