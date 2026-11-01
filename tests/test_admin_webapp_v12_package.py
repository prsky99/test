"""Version 1.2 packaging is opt-in and excludes private authority material."""
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile

import pytest

from agent_market.admin_workflow_webapp import build_admin_package
from agent_market.admin_workflow_webapp_v12 import build_admin_package_v12
from agent_market.workflow_webapp import build_package, export_config
from tests.test_workflow_apps_v12 import v12_runtime, export_request
from tests.test_workflow_fallback import routing


def test_v12_zip_has_fixed_profile_and_neither_private_grant_nor_legacy_changes(v12_runtime):
    rt,wf,service,calls=v12_runtime;result=service.export_admin(wf['id'],export_request(service,wf),1)
    payload,name=build_admin_package_v12(result['config'],result['deployment'])
    assert name.endswith('-sdk-v12-webapp.zip')
    with ZipFile(BytesIO(payload)) as archive:
        assert set(archive.namelist())=={'index.html','assets/agentconcierge-sdk.js','assets/app.js','assets/styles.css','README.md','app-manifest.json'}
        assert all((entry.external_attr>>16)&0o777==0o644 for entry in archive.infolist())
        manifest=json.loads(archive.read('app-manifest.json'))
        assert manifest['sdk_version']=='1.2.0' and manifest['inputs']=='fixed-reviewed-literals'
        assert manifest['per_run_authorization'] is True
        index=archive.read('index.html').decode();config=json.loads(re.search(r'id="wfData" nonce="[^"]+">(.*?)</script>',index,re.S)[1])
        assert set(config)=={'app_id','publish_key','workflow_id','profile','sdk_version'}
        assert 'shareAppAuthority' in index and 'liveAppAuthority' in index and 'prepareAppBtn' in index
        assert '/api/workflow-apps-v12/' in archive.read('assets/agentconcierge-sdk.js').decode()
        text='\n'.join(archive.read(name).decode() for name in archive.namelist())
        assert result['deployment']['grant_id'] not in text and 'credential_refs' not in text and 'resource_id' not in text
        assert 'primary.example' not in text and 'alternate.example' not in text and 'third.example' not in text
        assert 'unsafe-inline' not in index and 'unsafe-eval' not in index
    public,_=build_package(export_config(wf))
    with ZipFile(BytesIO(public)) as archive:
        assert json.loads(archive.read('app-manifest.json'))['sdk_version']=='1.0.0'
        assert '/api/workflows/run' in archive.read('assets/agentconcierge-sdk.js').decode()
        assert b'workflow-apps-v12' not in archive.read('assets/agentconcierge-sdk.js')
    legacy_deployment={**result['deployment'],'sdk_version':'1.1.0','input_fields':[]}
    legacy,_=build_admin_package(result['config'],legacy_deployment)
    with ZipFile(BytesIO(legacy)) as archive:
        assert json.loads(archive.read('app-manifest.json'))['sdk_version']=='1.1.0'
        assert archive.read('assets/agentconcierge-sdk.js')==Path('agent_market/gateway/webapp/sdk.js').read_bytes()
        assert archive.read('assets/app.js')==Path('agent_market/gateway/webapp/app.js').read_bytes()
    assert not calls


def test_v12_single_html_has_local_nonce_scripts_and_escaped_metadata(v12_runtime):
    _,wf,service,calls=v12_runtime;result=service.export_admin(wf['id'],export_request(service,wf),1)
    config={**result['config'],'title':'</script><img src=x onerror=alert(1)>','description':'<script>private</script>'}
    payload,name=build_admin_package_v12(config,result['deployment'],single_html=True);text=payload.decode()
    assert name.endswith('-sdk-v12-app.html') and '&lt;img' in text and '<img src=x' not in text
    assert 'src="assets/' not in text and 'href="assets/' not in text
    assert 'unsafe-inline' not in text and 'unsafe-eval' not in text
    assert re.findall(r'<script(?![^>]*nonce=)[^>]*>',text)==[]
    assert 'shareAppAuthority' in text and 'Review run inputs' in text and not calls


@pytest.mark.parametrize('change',[{'profile':'private-controlled-pair'},{'sdk_version':'1.1.0'}])
def test_new_builder_never_relabels_legacy_or_private_authority(v12_runtime,change):
    _,wf,service,_=v12_runtime;result=service.export_admin(wf['id'],export_request(service,wf),1)
    with pytest.raises(ValueError):build_admin_package_v12(result['config'],result['deployment']|change)
