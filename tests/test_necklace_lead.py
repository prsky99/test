"""An open necklace's run line leads a recommendation answer in its scope (PM 11-16 08:2x plan C, for 11-17).

Only offered necklaces are shown; the line runs it in one call (MCP tool or A2A 'run necklace'), with arguments
filled from the task only when certain, else the judge's example input."""
import pytest

from agent_market.concierge import necklace_lead
from agent_market.concierge import necklace_surface as ns

CVE = {'slug': 'cve-incident-brief', 'name': 'CVE incident brief', 'status': 'live', 'pricing': {'mode': 'free'},
       'input_schema': {'required': ['cve_id'], 'properties': {'cve_id': {'type': 'string'}}},
       'example_input': {'cve_id': 'CVE-2021-44228'}}
TRUST = {'slug': 'website-trust-brief', 'name': 'Website trust brief', 'status': 'live',
         'input_schema': {'required': ['domain'], 'properties': {'domain': {'type': 'string'}}}}


@pytest.fixture
def open_necklaces(monkeypatch):
    monkeypatch.setattr(ns, 'live', lambda snapshot=None, now=None: [CVE, TRUST])


def test_a_task_in_scope_gets_the_line_with_the_value_from_the_task(open_necklaces):
    line = necklace_lead.lead('Is CVE-2024-3094 actively exploited?')
    assert line == ('Free to run now: CVE incident brief (a necklace of tested agents): call tool '
                    '`necklace_cve_incident_brief` with {"cve_id":"CVE-2024-3094"}. '
                    'https://agentconcierge.biz/necklaces/cve-incident-brief')
    a2a = necklace_lead.lead('Is CVE-2024-3094 actively exploited?', kind='a2a')
    assert 'run necklace cve-incident-brief {"cve_id":"CVE-2024-3094"}' in a2a


def test_without_a_certain_value_the_example_input_is_used(open_necklaces):
    assert '{"cve_id":"CVE-2021-44228"}' in necklace_lead.lead('which vulnerabilities are actively exploited this week')


def test_no_example_leaves_a_placeholder_and_unpriced_necklaces_do_not_say_free(open_necklaces):
    line = necklace_lead.lead('is this website safe to buy from?')
    assert line.startswith('Run now: Website trust brief') and '{"domain":"<domain>"}' in line
    assert '{"domain":"shop.example.com"}' in necklace_lead.lead('is this website safe: shop.example.com')


def test_tasks_outside_every_scope_get_no_line(open_necklaces):
    for task in ('weather in Seoul', 'convert pdf to text', '', None, 'Is CVE nice?'):
        assert necklace_lead.lead(task) is None, task


def test_a_necklace_that_is_not_offered_is_never_shown():
    held = {**CVE, 'status': 'held'}
    snapshot = {'schema': ns.SCHEMA, 'necklaces': [held], 'events': []}
    assert necklace_lead.lead('Is CVE-2024-3094 actively exploited?', snapshot=snapshot) is None


def test_every_phrase_list_names_a_defined_necklace():
    import json
    from pathlib import Path
    defined = {json.loads(p.read_text())['slug'] for p in Path('agent_market/necklaces/definitions').glob('*.json')}
    assert set(necklace_lead.phrases()) <= defined
