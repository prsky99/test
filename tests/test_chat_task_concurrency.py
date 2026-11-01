"""Concurrency smoke uses an isolated catalog; it is not a model throughput benchmark."""
# ruff: noqa: F401,F811 -- imported isolated fixture
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import pytest
from tests.test_fast_single_recommendation import catalog


@pytest.mark.parametrize('concurrency',[1,4,8,16])
def test_concurrent_chat_keeps_constraints_and_verified_choice(catalog,monkeypatch,concurrency):
    _,front,client,add,now=catalog
    best=add('Verified Forecast',kind='mcp',report_at=now-1)
    add('Older Forecast',kind='mcp',report_at=now-100)
    # Keep this below production limits in scope: only the isolated security instance changes.
    monkeypatch.setattr(front.security,'allow_chat',lambda ip: True)
    def request(_):
        started=time.perf_counter()
        response=client.post('/chat',json={'message':'MCP weather forecast without an API key'})
        body=response.json()
        return {'status':response.status_code,'ms':round((time.perf_counter()-started)*1000,2),
                'correct':body.get('data',{}).get('recommendations',[{}])[0].get('id')==best,
                'constraint_retained':'no_api_key' in body.get('data',{}).get('task_spec',{}).get('required',[])}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        rows=list(pool.map(request,range(16)))
    assert all(row['status']==200 and row['correct'] and row['constraint_retained']for row in rows)
    timings=sorted(row['ms']for row in rows)
    record={'scope':'isolated SQLite TestClient with synthetic verified catalog','concurrency':concurrency,
            'requests':len(rows),'correct':sum(row['correct']for row in rows),'p50_ms':timings[7],
            'p95_ms':timings[15],'model_calls':0,'real_provider_calls':0,'requests_detail':rows}
    root=Path('reports/chat-recommendation-quality-development-2026-10-26')
    root.mkdir(parents=True,exist_ok=True)
    (root/f'fixture-concurrency-{concurrency}.json').write_text(json.dumps(record,indent=2)+'\n')
