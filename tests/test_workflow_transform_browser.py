"""First-class input/output transform nodes in the administrator workflow editor."""
# ruff: noqa: F401,F811
import json
import pytest

from playwright.sync_api import expect
from tests.test_workflow_runtime_browser import studio, login, browser

pytestmark=pytest.mark.usefixtures('rotated_bootstrap_admin')


def test_add_edit_and_connect_generic_transform_nodes(studio):
    page,_,front,errors,requests=studio
    login(page)
    page.locator('[data-tab="workflows"]').click()
    page.locator('#btnAddNodeDropdownBtn').click()
    page.locator('#wfAddInputTransform').click()
    expect(page.locator('#wfTransformRecipeBox')).to_be_visible()
    expect(page.locator('#inspAgentBox')).to_be_hidden()
    expect(page.locator('#btnTestSingleNode')).to_be_disabled()
    first=page.evaluate('canvasGraph.nodes[canvasGraph.nodes.length-1].id')
    recipe={'version':'json-io-transform-v1','input_schema':{'type':'object'},'output_schema':{'type':'object'},
        'expression':{'op':'object','fields':{'value':{'op':'integer','value':{'op':'get','path':'/requested'}}}}}
    page.locator('#wfTransformRecipe').fill(json.dumps(recipe))
    page.locator('#inspNodeInput').fill('{"requested":"12"}')
    page.locator('#btnApplyInspector').click()
    page.locator('#btnAddNodeDropdownBtn').click()
    page.locator('#wfAddOutputTransform').click()
    second=page.evaluate('canvasGraph.nodes[canvasGraph.nodes.length-1].id')
    graph=page.evaluate('canvasGraph')
    assert graph['nodes'][-2]['type']=='input_transform' and graph['nodes'][-1]['type']=='output_transform'
    assert graph['nodes'][-2]['data']['transform']==recipe
    # Save and execute the exact graph through the API tests; this browser
    # verifies the editor does not open agent replacement for local stages.
    assert first!=second and not errors
