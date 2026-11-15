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


def test_without_a_certain_value_a_placeholder_is_shown_never_another_example(open_necklaces):
    line = necklace_lead.lead('which vulnerabilities are actively exploited this week')
    assert '{"cve_id":"<cve_id>"}' in line and 'CVE-2021-44228' not in line


TOPIC = {'slug': 'topic-evidence-brief', 'name': 'Topic evidence brief', 'status': 'live', 'pricing': {'mode': 'free'},
         'input_schema': {'required': ['topic'], 'properties': {'topic': {'type': 'string'}}}}
COMPANY = {'slug': 'company-due-diligence', 'name': 'Company due diligence', 'status': 'live', 'pricing': {'mode': 'free'},
           'input_schema': {'required': ['name', 'country'], 'properties': {'name': {}, 'country': {}, 'domain': {}}}}


@pytest.mark.parametrize('task,slug,args', [
    ('Find recent research papers about retrieval augmented generation', 'topic-evidence-brief',
     '{"topic":"retrieval augmented generation"}'),
    ('find academic papers on coral reef bleaching published after 2023', 'topic-evidence-brief',
     '{"topic":"coral reef bleaching"}'),
    ('find academic papers about battery recycling with citations.', 'topic-evidence-brief',
     '{"topic":"battery recycling"}'),
    ('fetch the latest 10-K filing for Nvidia', 'company-due-diligence', '{"name":"Nvidia","country":"US"}'),
    ("Show me Apple's most recent SEC filings", 'company-due-diligence', '{"name":"Apple","country":"US"}'),
    ('look up a us public company and its latest sec filings', 'company-due-diligence',
     '{"name":"<name>","country":"US"}'),
])
def test_the_11_17_necklaces_take_the_topic_or_company_from_the_task(monkeypatch, task, slug, args):
    monkeypatch.setattr(ns, 'live', lambda snapshot=None, now=None: [TOPIC, COMPANY])
    line = necklace_lead.lead(task)
    assert line and '`necklace_' + slug.replace('-', '_') + '` with ' + args in line, line


@pytest.mark.parametrize('task', [
    'training plan for a 10-k race',                       # a race distance, not a filing
    'design a LinkedIn company profile page',
    'due diligence checklist for buying a used car',
    'summarize a pdf research paper',                      # one paper, not a topic brief
    'look up a paper by its DOI',
    'generate a BibTeX entry for a paper',
    'Get the abstract of an arXiv paper by its id',
    'get company information from a domain',
    'Public research only. Do not request credentials, private files, local machine details',
    'write a brief for my design agency',
    'what are the security implications of this config',
])
def test_tasks_outside_the_11_17_necklaces_get_no_line(monkeypatch, task):
    monkeypatch.setattr(ns, 'live', lambda snapshot=None, now=None: [TOPIC, COMPANY])
    assert necklace_lead.lead(task) is None


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
