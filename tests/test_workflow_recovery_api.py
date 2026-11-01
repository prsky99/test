"""Recovery metadata requires the private highest-admin boundary."""
from tests.test_admin_webapp_deployments import app_runtime
from tests.test_workflow_runtime import runtime,wait
from tests.test_admin_security_audit import login,session_headers
from agent_market.gateway.admin_auth import create_admin_user
from tests.conftest import staff_session


def test_recovery_api_is_private_bounded_and_has_no_checkpoint_payload(app_runtime):
    rt,wf,_,public,admin=app_runtime;job=rt.submit(wf);wait(rt,job);route='/admin/api/workflows/runs/'+job['run_id']+'/recovery'
    assert admin.get(route).status_code in (401,403)
    assert public.get(route).status_code==404
    with rt.store.tx() as db:create_admin_user(db,'recovery-manager','recovery-password-123','Manager','admin')
    token=login(admin,'recovery-manager','recovery-password-123').json()['token']
    assert admin.get(route,headers=session_headers(token)).status_code==403
    headers=staff_session(rt.store);r=admin.get(route,headers=headers)
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert r.json()['run']['status']=='succeeded'
    for private in ('signature','payload','input_hash','subject','target','snapshot','output','signing_secret'):assert private not in r.text
    assert admin.get(route.replace(job['run_id'],'bad-reference'),headers=headers).status_code==400
