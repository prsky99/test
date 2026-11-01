"""Native PostgreSQL 18 verification without operating data or TCP services."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_native_registration_hardening():
    from scripts.rehearse_storage_adapter_postgres import _driver,_tools,_private_cluster
    driver=_driver()
    with _private_cluster(_tools()) as cluster:
        environment=dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE']='1'
        environment['PYTHONPATH']=str(Path.cwd())+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        code='''
from scripts import rehearse_application_store_postgres as base
from scripts.rehearse_registration_hardening import contracts
def verify(connect):
    from agent_market.storage_adapter import open_store
    return contracts(connect,lambda pg,**kw:open_store('postgresql',connection=pg,initialize=True,**kw))
base._contracts=verify
base._worker()
'''
        child=subprocess.run([sys.executable,'-B','-c',code],env=environment,
            input=json.dumps({'socket':cluster['socket'],'root':cluster['root']}),text=True,capture_output=True,timeout=150)
        assert child.returncode==0,child.stderr[-5000:]
        result=json.loads(child.stdout)
    assert all(result['checks'].values())
    output=Path('reports/registration-hardening-2026-10-27/native-postgres.json')
    output.write_text(json.dumps(result,indent=2)+'\n')
