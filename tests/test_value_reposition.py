"""PM 11-16 21:13 (value review): the catalog count is not the lead number, and the name line says we are not
agentconcierge.io."""
import re
from pathlib import Path

from agent_market.concierge.front import llms_txt

ROOT = Path(__file__).resolve().parents[1]
LIVE = ['index.html', 'about.html', 'agent-status.html', 'chat.html', 'explore.html', 'learn.html', 'list-agent.html',
        'test.html', 'workflows.html']


def test_llms_txt_names_us_and_says_we_are_not_the_other_service():
    text = llms_txt('https://agentconcierge.biz', {})
    head = text.split('\n\n', 2)
    assert head[0] == '# AgentValCon'
    assert 'AgentValCon runs at agentconcierge.biz and is not affiliated with agentconcierge.io.' in head[1]


def test_home_band_leads_with_execution_checks_and_ends_with_the_catalog_count():
    for name in LIVE:
        html = (ROOT/'new/en'/name).read_text()
        band = html[html.index('<section class="catalog-band"'):html.index('id="uxHomeSnapshotState"')]
        assert re.findall(r'data-metric="(\w+)"', band) == ['execution', 'reachable', 'with_status_check', 'cataloged'], name
        assert band.count('data-primary') == 1 and re.search(r'data-primary>\s*<span[^>]*>\s*</span>\s*<strong[^>]*data-metric="execution"', band), name
        assert 'Checks overview' in band and 'Catalog overview' not in band, name
