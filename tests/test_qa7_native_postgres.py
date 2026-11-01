"""PostgreSQL 18 rehearsal isolated from operating databases and TCP."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_native_qa7_schema_recovery():
    from scripts.rehearse_storage_adapter_postgres import _driver,_tools,_private_cluster
    driver=_driver()
    with _private_cluster(_tools()) as cluster:
        env=dict(cluster['environment']);env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONPATH']=str(Path.cwd())+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        code='''
from scripts import rehearse_application_store_postgres as base
from scripts.rehearse_qa7_remediation import contracts
def verify(connect):
 from agent_market.storage_adapter import open_store
 return contracts(connect,lambda pg,**kw:open_store('postgresql',connection=pg,initialize=True,**kw))
base._contracts=verify
base._worker()
'''
        child=subprocess.run([sys.executable,'-B','-c',code],env=env,input=json.dumps({'socket':cluster['socket'],'root':cluster['root']}),capture_output=True,text=True,timeout=150)
        assert child.returncode==0,child.stderr[-5000:]
        result=json.loads(child.stdout)
    assert all(result['checks'].values())
    Path('reports/qa7-remediation-2026-10-29/native-postgres.json').write_text(json.dumps(result,indent=2)+'\n')
