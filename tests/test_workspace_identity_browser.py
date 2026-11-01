"""Current staff manage synthetic customer links; no SSO or provider call."""
import time

from playwright.sync_api import expect

from tests.test_workspace_browser import workspace_browser, sign_in, select_space, make_space
from tests.test_front_workflow_browser import browser


def test_staff_owner_links_customer_and_prepares_separate_unchecked_https_proof(workspace_browser):
    w=workspace_browser;w.page.context.set_offline(True)
    ws=make_space(w)
    customer='cu_'+'a'*32
    with w.store.tx() as db:
        db.execute('INSERT INTO customer_identities VALUES(?,?,?,1,1,?,?)',
                   (customer,'https://accounts.google.com','b'*64,time.time(),time.time()))
    rid=w.store.upsert_resource({'key':'mcp:https://provider-fixture.invalid/mcp','source':'mcp-registry','kind':'mcp',
        'url':'https://provider-fixture.invalid/mcp','name':'Synthetic endpoint','description':'Synthetic control-proof fixture',
        'category':'dev_tools','networks':[],'price_usdc':0,'details':{}})
    sign_in(w);select_space(w,ws);w.page.locator('#workspaceIdentity').click()
    dialog=w.page.get_by_role('dialog',name='Customer access and provider control')
    expect(dialog).to_be_visible();expect(dialog.get_by_role('status')).to_contain_text('Customer access is explicit.')
    dialog.get_by_label('Customer ID',exact=True).fill(customer)
    dialog.get_by_role('button',name='Save customer access').click()
    expect(dialog).to_contain_text(customer+' · viewer · active · revision 1')
    assert w.store.query('SELECT active,revision FROM customer_workspace_links')[0][:]==(1,1)
    dialog.get_by_label('Registered resource ID').fill(str(rid))
    dialog.get_by_role('button',name='Prepare HTTPS challenge').click()
    expect(dialog.locator('pre')).to_contain_text('https://provider-fixture.invalid/.well-known/agent-concierge-claim.json')
    expect(dialog.get_by_role('checkbox',name='I authorize one HTTPS request',exact=False)).not_to_be_checked()
    expect(dialog.get_by_role('button',name='Verify endpoint control')).to_be_disabled()
    assert not any(method=='POST' and path.endswith('/provider-claims/verify') for method,path,_ in w.requests)
    dialog.get_by_role('button',name='Close',exact=True).click()
    expect(dialog).to_have_count(0)
    assert not w.external and not w.errors


def test_closing_identity_dialog_discards_late_customer_list(workspace_browser):
    w=workspace_browser;w.page.context.set_offline(True);ws=make_space(w);sign_in(w);select_space(w,ws)
    pending=[]
    def hold(route):
        response=w.client.get('/admin/api/workflow-workspaces/'+ws['id']+'/customers',headers=w.headers['owner'])
        pending.append((route,response));w.page.evaluate('window.__customerListHeld=true')
    w.page.route('**/customers',hold);w.page.locator('#workspaceIdentity').click()
    w.page.wait_for_function('()=>window.__customerListHeld===true')
    w.page.get_by_role('dialog',name='Customer access and provider control').get_by_role('button',name='Close',exact=True).click()
    route,response=pending[0]
    try:route.fulfill(status=response.status_code,content_type='application/json',body=response.content)
    except Exception:pass  # AbortController may have already cancelled this read.
    assert w.page.get_by_role('dialog',name='Customer access and provider control').count()==0
    assert not w.external and not w.errors
