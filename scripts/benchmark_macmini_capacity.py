"""Additional per-feature C16 and plain-text control, using captured real feature payloads."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile

import httpx

from scripts import benchmark_macmini_model as bench
from scripts.agentcon_config import read_local_model_settings


class CaptureProbe:
    """Capture payload construction only; this never contacts a model."""
    def __init__(self):
        self.requests=[];self.responses=[]
        def respond(request):
            self.requests.append(json.loads(request.content))
            self.responses.append({'status':503,'body':{}})
            return httpx.Response(503,json={})
        self.client=httpx.Client(transport=httpx.MockTransport(respond))


def main():
    config=read_local_model_settings('gateway-data/local-model.env')
    original=bench.Probe
    original_cases=bench.cases
    def explicit_cases(model):
        result=original_cases(model)
        for case in result:
            if case['feature']=='workflow' and set(case['expected_contracts'])=={'docs.search.v1'}:
                case['context']['objective']+=' Every step must search documentation only. Do not search news.'
                case['id']+='_explicit_docs_only'
        return result
    try:
        bench.Probe=CaptureProbe
        bench.cases=explicit_cases
        with tempfile.TemporaryDirectory(prefix='payload-capture-') as temp,contextlib.redirect_stdout(io.StringIO()):
            _,prepared=bench.functional(config,Path(temp),1)
    finally:
        bench.Probe=original
        bench.cases=original_cases
    output=Path('reports/model-performance-2026-10-23/additional');output.mkdir(parents=True,exist_ok=True)
    plan=[('plain_text',2,(1,4,8,16),prepared)]
    for feature in ('workflow','guidance','composer','intent','lead','rag'):
        plan.append((feature,1,(16,),[pair for pair in prepared if pair[0]['feature']==feature]))
    asyncio.run(bench.load(config,prepared,output,plan=plan))


if __name__=='__main__':main()
