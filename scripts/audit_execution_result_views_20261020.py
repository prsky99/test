"""Review actual live response rendering without re-executing any provider task."""
import json
from tests.test_pearl_frontend import browser,client,pearl_page,ORIGIN
from scripts.audit_frontend_ux_20261020 import INSPECT,OUT


def test_capture_real_response_rendering(pearl_page):
    page,errors,calls=pearl_page
    actual=json.loads((OUT/'live-execution-results.json').read_text())
    manifest={'scope':'operating API response replay through real renderers; no additional live dispatch', 'screens':[]}
    def capture(name):
        page.wait_for_timeout(150)
        row=page.evaluate(INSPECT);row.update(name=name,device='desktop')
        row['screenshot']='evidence/response-replay-'+name+'.png'
        page.screenshot(path=str(OUT/row['screenshot']),full_page=False)
        manifest['screens'].append(row)
    for index,row in enumerate(actual['examples']):
        page.goto(ORIGIN+'/#test')
        page.evaluate('(response)=>renderTestbenchResult(response)',row['response'])
        toggle=page.get_by_role('button',name='Show result',exact=True)
        if toggle.is_visible():toggle.click()
        page.locator('#uxTestResultPanel').evaluate("element=>element.scrollIntoView({block:'start',behavior:'auto'})")
        capture('example-'+str(index+1))
    for index,row in enumerate(actual['workflows']):
        if 'result' not in row:continue
        page.goto(ORIGIN+'/new/en/workflows.html')
        page.evaluate('(response)=>showFrontRunOutputModal(response)',row['result'])
        page.locator('#uxWorkflowResultPanel').evaluate("element=>element.scrollIntoView({block:'start',behavior:'auto'})")
        capture('workflow-'+str(index+1))
        page.keyboard.press('Escape')
    manifest['errors']=errors
    (OUT/'response-replay-inventory.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
