"""Serial calibration against the configured private primary/standby model.

Only fixed synthetic public objectives and synthetic resource IDs are sent.
No settings, accounts, agents, providers or application data are changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx

from scripts.agentcon_config import read_local_model_settings
from agent_market.workflow_model_proposer import OllamaGraphProposer
from scripts.quality_fixture_context import context
from agent_market.search_quality import percentile

OBJECTIVES = ('Find Python documentation using two steps',
    'Find documentation about FastAPI and PostgreSQL using two steps',
    'Find top 3 news about renewable energy then documentation using two steps',
    'Find documentation for 3 topics: Docker, Kubernetes and Terraform')


def run():
    settings=read_local_model_settings('gateway-data/local-model.env')
    endpoint=settings['WORKSPACE_MODEL_URL']
    standby=settings.get('WORKSPACE_MODEL_FALLBACK_URL','')
    for address in (endpoint,standby):
        if address and urlsplit(address).hostname not in ('192.168.0.24','192.168.0.25'):
            raise ValueError('Calibration requires the previously approved private model hosts.')
    rows=[]
    with httpx.Client(trust_env=False,follow_redirects=False) as client:
        proposer=OllamaGraphProposer(endpoint,settings['WORKSPACE_MODEL_NAME'],client,
            provider=settings.get('WORKSPACE_MODEL_PROVIDER','ollama'),allow_http=True,fallback_endpoint=standby)
        for objective in OBJECTIVES:
            started=time.monotonic();repairs=[]
            try:
                value=proposer.propose(context(objective),_repair_attempts=1,_quality=repairs.append)
                passed=bool(value['nodes']);error=None
            except Exception as exc:
                passed=False;error=type(exc).__name__
            rows.append({'objective':objective,'passed':passed,'seconds':round(time.monotonic()-started,1),
                         'local_query_repairs':sum(repairs),'error_class':error})
    timings=[r['seconds']for r in rows]
    return {'scope':'configured_private_model_public_synthetic_serial_calibration','samples':len(rows),
        'passed':sum(r['passed']for r in rows),'rows':rows,'p50_seconds':percentile(timings,.5),
        'p95_seconds':percentile(timings,.95),'small_sample_not_operating_slo':True,
        'provider_business_calls':0,'application_database_access':False,'warm_state':'uncontrolled_existing_server',
        'model_descriptor_hash':hashlib.sha256(settings['WORKSPACE_MODEL_NAME'].encode()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=run()
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k]for k in ('samples','passed','p50_seconds','p95_seconds','small_sample_not_operating_slo')}))
    return 0 if result['passed']==result['samples']else 1


if __name__=='__main__':raise SystemExit(main())
