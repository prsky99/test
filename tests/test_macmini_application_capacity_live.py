"""Explicit real-model test of the existing application's admission limit."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Barrier,Lock
import time

import httpx
import pytest

from agent_market.workflow_model_proposer import OllamaGraphProposer
from agent_market import workspace_app_factory
from scripts.agentcon_config import read_local_model_settings
from tests.test_workspace_growth import growth  # noqa: F401
from tests.test_workspace_typed_flows import typed_world,routing  # noqa: F401
from tests.test_workspace_model_proposal import request

pytestmark=pytest.mark.skipif(os.environ.get('LIVE_MACMINI_CAPACITY_CHECK')!='1',reason='Explicit local model load opt-in required')


def test_sixteen_requests_measure_existing_app_admission(growth):
    g=growth;s=read_local_model_settings('gateway-data/local-model.env');lock=Lock();gate=Barrier(16)
    calls=[];active=0;peak=0
    def before(req):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active);calls.append({'model':json.loads(req.content)['model']})
    def after(res):
        nonlocal active
        with lock:active-=1
    with httpx.Client(trust_env=False,follow_redirects=False,event_hooks={'request':[before],'response':[after]}) as client:
        g.factory.model_proposer=OllamaGraphProposer(s['WORKSPACE_MODEL_URL'],s['WORKSPACE_MODEL_NAME'],client,provider='openai',allow_http=True)
        def one(index):
            gate.wait(timeout=15);start=time.monotonic()
            try:
                result=g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
                return {'index':index,'completed':True,'seconds':round(time.monotonic()-start,4),'node_count':len(result['definition']['nodes'])}
            except Exception as exc:return {'index':index,'completed':False,'seconds':round(time.monotonic()-start,4),'error':type(exc).__name__}
        with ThreadPoolExecutor(max_workers=16) as pool:rows=list(pool.map(one,range(16)))
    result={'requests':16,'completed':sum(x['completed'] for x in rows),'rejected_or_failed':sum(not x['completed'] for x in rows),
            'model_requests_sent':len(calls),'peak_model_requests':peak,
            'configured_process_slots':workspace_app_factory._proposal_slots._initial_value,'production_data_modified':False,
            'rows':rows,'note':'Isolated AppFactory with real model; existing process admission is measured without changing it.'}
    result['configured_active_requests']=workspace_app_factory.MODEL_ACTIVE_REQUESTS
    output=Path(os.environ.get('LIVE_MODEL_REPORT_DIR','reports/model-performance-2026-10-23'))
    output.mkdir(parents=True,exist_ok=True)
    (output/'application-admission.json').write_text(json.dumps(result,indent=2)+'\n')
    assert len(rows)==16 and peak<=workspace_app_factory.MODEL_ACTIVE_REQUESTS
    assert not g.w.calls
