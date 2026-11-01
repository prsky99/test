"""Use a disposable PostgreSQL 18, never the operating database."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_feature_storage_on_native_postgres():
    from scripts.rehearse_storage_adapter_postgres import _driver,_tools,_private_cluster
    driver=_driver()
    with _private_cluster(_tools()) as cluster:
        env=dict(cluster['environment']);env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONPATH']=str(Path.cwd())+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        code='''
from scripts import rehearse_application_store_postgres as base
from scripts.rehearse_feature_remediation import contracts
def verify(connect):
 from agent_market.storage_adapter import open_store
 return contracts(connect,lambda pg,**kw:open_store('postgresql',connection=pg,initialize=True,**kw))
base._contracts=verify
base._worker()
'''
        child=subprocess.run([sys.executable,'-B','-c',code],env=env,input=json.dumps({'socket':cluster['socket'],'root':cluster['root']}),capture_output=True,text=True,timeout=150)
        assert child.returncode==0,child.stderr[-3000:]
        result=json.loads(child.stdout)
    assert all(result['checks'].values())
    Path('reports/feature-remediation-2026-10-29/native-postgres.json').write_text(json.dumps(result,indent=2)+'\n')
