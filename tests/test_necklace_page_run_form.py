"""F17 (PM 11-15): a first-time person can run a necklace from its page, and reads plain sentences when it does not run.

The page carries a plain form (no script: the growth-page CSP allows form-action 'self'), one field per input with a
hint, the consent box and a Run button; the form post answers with the same page, the result first and the values kept.
The rules are those of /api/necklaces/<slug>/run: no consent, no member call. Members are the loopback MCP servers of
test_necklace_app_run; nothing leaves the machine."""
import json
from urllib.parse import urlencode

from agent_market.concierge import necklace_surface as ns
from tests.test_necklace_app_run import calls, site  # noqa: F401 - fixture

FORM = {'content-type': 'application/x-www-form-urlencoded', 'accept': 'text/html'}


def test_live_page_has_a_keyboard_form_and_a_standing_line(site):  # noqa: F811
    client, servers, _ = site
    r = client.get('/necklaces/advisory-brief', headers={'accept': 'text/html'})
    html = r.text
    assert '<form class="stack" method="post" action="/necklaces/advisory-brief/run">' in html
    assert 'id="nk-q"' in html and 'for="nk-q"' in html and 'aria-describedby="nk-q-hint"' in html and ' required' in html
    assert 'name="necklace_notice" value="necklace-v1" required' in html
    assert '<button class="btn primary" type="submit">Run</button>' in html
    assert 'Standing: running · its connection test (3 runs on different inputs) has not run yet; once it passes, one connection run a day keeps it open.' in html and '95%' not in html   # PM 22:30: the 110-retest wait could never be reached
    assert "form-action 'self'" in r.headers['content-security-policy']
    held = client.get('/necklaces/held-brief', headers={'accept': 'text/html'}).text
    assert '<form' not in held and 'Standing: paused.' in held


def test_form_without_consent_runs_nothing_and_says_what_to_do(site):  # noqa: F811
    client, servers, _ = site
    r = client.post('/necklaces/advisory-brief/run', content=urlencode({'q': 'lodash'}), headers=FORM)
    assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
    assert 'Tick the box to confirm you read where your input goes' in r.text
    assert 'value="lodash"' in r.text            # the value is kept for the second try
    assert calls(servers) == 0


def test_form_with_consent_shows_each_step_its_sources_and_the_limits(site):  # noqa: F811
    client, servers, _ = site
    r = client.post('/necklaces/advisory-brief/run',
                    content=urlencode({'q': 'lodash', 'necklace_notice': 'necklace-v1', 'extra': 'dropped'}), headers=FORM)
    assert r.status_code == 200 and calls(servers) >= 2
    result = r.text.split('id="result"', 1)[1].split('</section>', 1)[0]
    assert 'Finished.' in result
    assert '<dt>advisories</dt>' in result and '<dt>exploited</dt>' in result
    assert 'href="/agent/' in result                  # each step names the agent that answered
    assert 'Answers come from third-party agents' in result
    assert '<script' not in result


def test_agents_read_a_plain_sentence_before_the_code():
    assert ns.message('consent_required').startswith('Tick the box')
    assert ns.message('slot_failed:identity').startswith('No agent for the identity step')
    assert 'try again later' in ns.message('something_new').lower()


def test_example_input_feeds_the_agent_examples():
    entry = {'slug': 'x', 'input_schema': {'type': 'object', 'required': ['name', 'country'],
                                           'properties': {'name': {'type': 'string'}, 'country': {'type': 'string'}}},
             'example_input': {'name': 'Apple Inc', 'country': 'US', 'secret': 'not a field'}}
    assert ns.example_input(entry) == {'name': 'Apple Inc', 'country': 'US'}
    assert ns.example_arguments(entry['input_schema'], ns.example_input(entry)) == {'name': 'Apple Inc', 'country': 'US'}
    assert ns.example_arguments(entry['input_schema']) == {'name': '<name>', 'country': '<country>'}
    assert json.dumps(ns.example_input({**entry, 'example_input': 'x'})) == 'null'


def test_free_for_now_is_said_only_when_the_snapshot_marks_it():
    """11-15 user decision: necklaces run free for now; the judge marks it (pricing {"mode": "free"}), no end date."""
    entry = {'slug': 'x', 'name': 'X', 'summary': 'S', 'pricing': {'mode': 'free'},
             'input_schema': {'type': 'object', 'required': ['q'], 'properties': {'q': {'type': 'string'}}}}
    assert ns.free_now(entry) and not ns.free_now({**entry, 'pricing': {'mode': 'paid'}}) and not ns.free_now({'slug': 'x'})
    assert not ns.free_now({**entry, 'pricing': 'free'})
    assert 'for now' in ns.FREE_NOW and 'until' not in ns.FREE_NOW.lower()


def test_free_line_on_page_tools_skills_and_llms(site, monkeypatch):  # noqa: F811
    client, servers, data = site
    path = data / 'necklaces.json'
    snapshot = json.loads(path.read_text())
    snapshot['necklaces'][0]['pricing'] = {'mode': 'free'}
    path.write_text(json.dumps(snapshot))
    page = client.get('/necklaces/advisory-brief', headers={'accept': 'text/html'}).text
    assert ns.FREE_NOW in page
    held = client.get('/necklaces/held-brief', headers={'accept': 'text/html'}).text
    assert ns.FREE_NOW not in held
    snap = ns.load()
    assert 'Free to run for now' in ns.llms_section(snapshot=snap)
    tool = [t for t in ns.tools(snapshot=snap) if t['name'] == 'necklace_advisory_brief'][0]
    assert 'Free to run for now' in tool['description']
    assert 'Free to run for now' in ns.skills(snapshot=snap)[0]['description']
