"""PM 11-13 decision 1: the gateway relay judgment allows a read verb after one name prefix, with word
boundaries; collector trial calls keep usage.is_safe_tool unchanged."""
import pytest

from agent_market.collector import usage
from agent_market.concierge.execution_policy import safe_registered_tool


def tool(name, description='', **annotations):
    return {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': {}},
            'annotations': annotations}


@pytest.mark.parametrize('name, description', [
    ('invoice_parse_text', 'Extract all text from a PDF invoice. Returns text per page.'),
    ('acc_list_issues', 'List up to 50 issues from an ACC project.'),
    ('duvera__github_search_repos', '[duvera · risk:low] Search public GitHub repositories by keyword.'),
    ('vf_health', 'Returns server health and version metadata.'),
    ('validate.bic', 'Validate a SWIFT/BIC code.'),
    ('weather.forecast', 'Official US weather forecast for a coordinate.'),
    ('get_weather', ''),
    ('getWeather', ''),
    ('summarize_text', ''),
    ('listar_facturas', 'Historial de facturas.'),
])
def test_relay_allows_read_tools(name, description):
    assert usage.is_relay_safe_tool(tool(name, description)), name
    assert safe_registered_tool(tool(name, description)), name


@pytest.mark.parametrize('name, description', [
    ('invoice_delete', 'Delete an invoice.'),                       # deny word
    ('scratchpad_checkpoint', 'Save a checkpoint.'),                 # 'check' is not a word here
    ('checkpoint_put', 'Save where the work got to.'),
    ('browser_drag', 'Drag an element in the browser.'),             # 'browse' is not 'browser'
    ('browser_control', 'Embedded browser action (click, type, scroll).'),
    ('checkout_link', 'Get the current checkout URL for the store cart.'),
    ('counter_quote', 'Counter an existing quote.'),                 # a prefix that is itself a verb stem
    ('checklists_checkItem', 'Tick or untick an item.'),
    ('armory_version_bumper', 'Dependency and app version bump orchestration.'),
    ('gpu_quote', 'B2B bulk quote + 5% matching fee'),
    ('agentlux_list_item', 'List a generated item on the marketplace for sale.'),
    ('me_compare', 'Ask calibrated humans to compare two outputs.'),
    ('screen_show', 'Put ONE match on the venue call screen.'),
    ('record_view_results', 'Stores the result of a diagram run.'),
    ('haven_check_out', 'Leave Haven. Returns your identity summary.'),
    ('refresh_prices', 'Fetch fresh market prices now.'),
    ('a_b_get', 'Get a thing.'),                                     # two prefixes
    ('invoice_ocr', 'OCR a scanned invoice.'),                       # 'ocr' is not an allowed verb
])
def test_relay_refuses(name, description):
    assert not usage.is_relay_safe_tool(tool(name, description)), name


def test_annotations_come_first():
    assert usage.is_relay_safe_tool(tool('post_tweet', readOnlyHint=True))
    assert not usage.is_relay_safe_tool(tool('get_weather', readOnlyHint=False))
    assert not usage.is_relay_safe_tool(tool('get_weather', destructiveHint=True, readOnlyHint=True))
    personal = {**tool('get_user'), 'required': ['email']}
    assert not usage.is_relay_safe_tool(personal)


def test_collector_trial_scope_is_unchanged():
    # The relay widening does not reach collector trial calls (PM 11-13: widen them only on separate evidence).
    assert not usage.is_safe_tool(tool('invoice_parse_text', 'Extract all text from a PDF invoice.'))
    assert usage.is_safe_tool(tool('get_weather'))
