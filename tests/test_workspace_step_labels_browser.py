"""Result headings name documentation steps by their agent, not the shared docs.search.v1 contract."""
from pathlib import Path
import re

from tests.test_front_workflow_browser import browser  # noqa: F401


def test_documentation_agents_are_labelled_documentation_search(browser):  # noqa: F811
    source = Path('agent_market/customer_typed_authoring_view.py').read_text()
    label = re.search(r"const taskLabel=.*?'Choose an agent'\)\};", source).group(0)
    page = browser.new_page()
    try:
        page.set_content('<!doctype html><title>labels</title>')
        page.add_script_tag(content="let candidates=[{resource_id:1,contract_id:'docs.search.v1',name:'Technical Documentation'},"
                                    "{resource_id:2,contract_id:'docs.search.v1',name:'Research Papers'}];" + label
                                    + "window.labels=[taskLabel('docs.search.v1',1),taskLabel('docs.search.v1',2),"
                                    "taskLabel('docs.search.v1',3),taskLabel('docs.search.v1'),taskLabel('news.search.v1',1),"
                                    "taskLabel('docs.search.v1','1')];")
        # The step editor reads resource ids back from <select> values as strings.
        assert page.evaluate('window.labels') == ['Documentation search', 'Research search', 'Research search',
                                                  'Research search', 'News search', 'Documentation search']
    finally:
        page.close()


def test_every_step_heading_passes_its_agent():
    source = Path('agent_market/customer_typed_authoring_view.py').read_text()
    # Option text falls back to the contract label only for agents without a name.
    calls = [call for call in re.findall(r'taskLabel\(([^()]*(?:\([^()]*\)[^()]*)*)\)', source) if call != 'c.contract_id']
    assert calls and all(',' in call for call in calls), calls
