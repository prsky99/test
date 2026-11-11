#!/usr/bin/env python3
"""User-facing targets, measured from outside the way a visitor or an agent experiences them (11-10 user request:
"if there is a target, keep improving toward it"). Internal timings (one SQL query, server-only time) are NOT targets.

Every check goes through the public address https://agentconcierge.biz (Cloudflare and the tunnel included), with
queries the site has never seen. Targets (CLAUDE.md response-time policy, quality target 100%):

  explore      every unseen search answers within 2.0 s with at least one result (11-10 user target)
  recommend    an agent asking find_agents (MCP) gets an answer within 3.0 s; complex answers within 5.0 s
  connect      the top recommended agent answers initialize + tools/list through our gateway with >= 1 tool
  pages        the Explore and Chat pages download within 2.0 s

Writes one JSON line to logs/ops/user-slo.jsonl and prints it. "breaches" lists only failed targets, each with
the owning team, so scripts/ops_auto.py can hand them over on the status board.
"""
import json
import random
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/ops/user-slo.jsonl'
BASE = 'https://agentconcierge.biz'
UA = 'agentcon-user-slo/1 (site owner QA; contact@agentconcierge.biz)'
QA_HEADER = {'X-Agentcon-QA': 'user_slo'}  # 11-11: lets the error ledger set our own measurements apart
TOPICS = ['weather forecast', 'translate pdf', 'send email', 'crypto price', 'summarize video', 'book flights',
          'invoice ocr', 'github issues', 'stock quotes', 'calendar scheduling', 'web scraping', 'image generation',
          'speech to text', 'sql database', 'news headlines', 'legal contract review', 'recipe nutrition',
          'shipping tracking', 'customer support', 'code review', '날씨', '번역', '이메일 보내기']
MODIFIERS = ['for my team', 'in real time', 'free', 'api', 'for agents', 'quickly', 'with history', 'in korea',
             'small business', 'json output', 'today', 'bulk']
TARGET = {'explore_s': 2.0, 'recommend_s': 3.0, 'complex_s': 5.0, 'page_s': 2.0}  # 11-10 18시 사용자 결정
OWNER = {'explore': '검색과 RAG', 'recommend': '검색과 RAG', 'connect': '검색과 RAG', 'pages': '성장·유통'}
MCP_HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}


def unseen(n):
    picks = random.sample(TOPICS, n)
    return [f'{t} {random.choice(MODIFIERS)} {random.randint(10, 999)}' for t in picks]


def timed(fn):
    started = time.time()
    try:
        result = fn()
    except Exception as error:  # noqa: BLE001 - any failure is the signal
        return round(time.time() - started, 2), None, type(error).__name__
    return round(time.time() - started, 2), result, None


def mcp(client, url, method, params=None, session=None, rid=1):
    headers = dict(MCP_HEADERS, **({'Mcp-Session-Id': session} if session else {}))
    body = {'jsonrpc': '2.0', 'id': rid, 'method': method}
    if params is not None:
        body['params'] = params
    response = client.post(url, headers=headers, json=body)
    text = response.text
    if text.startswith('event:') or '\ndata:' in text:
        text = text.split('data:', 1)[1].strip()
    return response, json.loads(text)


def check_explore(client, n=6):
    rows = []
    for query in unseen(n):
        took, response, error = timed(lambda: client.get(f'{BASE}/api/explore', params={'q': query}))
        total = None
        if response is not None and response.status_code == 200:
            try:
                total = response.json().get('total')
            except ValueError:
                pass
        rows.append({'q': query, 's': took, 'status': getattr(response, 'status_code', error), 'total': total})
    bad = [r for r in rows if r['s'] > TARGET['explore_s'] or r['status'] != 200 or not r['total']]
    return {'samples': rows, 'max_s': max(r['s'] for r in rows), 'ok': not bad, 'bad': bad}


def check_recommend_and_connect(client, n=2):
    rec, conn = [], []
    for task in unseen(n):
        took, result, error = timed(lambda: mcp(client, f'{BASE}/mcp', 'tools/call',
                                                {'name': 'find_agents', 'arguments': {'task': task}}))
        text = ''
        if result:
            try:
                text = result[1]['result']['content'][0]['text']
            except (KeyError, IndexError, TypeError):
                text = ''
        rec.append({'task': task, 's': took, 'answered': bool(text), 'error': error})
        endpoint = next((line.split('Endpoint:', 1)[1].strip().split()[0] for line in text.splitlines()
                         if 'Endpoint:' in line and '/api/gateway/' in line), None)
        if not endpoint:
            continue
        if '/api/gateway/mcp/' in endpoint:
            def connect():
                init, _ = mcp(client, endpoint, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                                'clientInfo': {'name': 'user-slo', 'version': '1'}})
                listed, body = mcp(client, endpoint, 'tools/list', session=init.headers.get('mcp-session-id'), rid=2)
                return len((body.get('result') or {}).get('tools') or [])
        else:
            # A2A recommendation (11-11): connecting means the gateway serves the agent's card; no message is sent.
            def connect():
                response = client.get(endpoint, headers={'Accept': 'application/json'})
                return 1 if response.status_code == 200 else 0
        took_c, tools, error_c = timed(connect)
        conn.append({'endpoint': endpoint.rsplit('/', 2)[-2] + '/' + endpoint.rsplit('/', 1)[-1], 's': took_c,
                     'tools': tools, 'error': error_c})
    rec_bad = [r for r in rec if r['s'] > TARGET['recommend_s'] or not r['answered']]
    conn_bad = [c for c in conn if not c['tools']]
    # No gateway endpoint among the answers means connect was not measured this hour; that is recorded, not hidden,
    # but it is not counted as a failed connection (11-11: 14:02 run had two answers with no gateway endpoint).
    return ({'samples': rec, 'ok': not rec_bad, 'bad': rec_bad},
            {'samples': conn, 'ok': not conn_bad, 'bad': conn_bad, 'measured': bool(conn)})


def check_pages(client):
    rows = []
    for path in ('/new/en/explore.html', '/new/en/chat.html', '/'):
        took, response, error = timed(lambda: client.get(BASE + path, headers={'Accept': 'text/html'}))
        rows.append({'path': path, 's': took, 'status': getattr(response, 'status_code', error)})
    bad = [r for r in rows if r['s'] > TARGET['page_s'] or r['status'] != 200]
    return {'samples': rows, 'ok': not bad, 'bad': bad}


def main():
    client = httpx.Client(timeout=30, headers={'User-Agent': UA, **QA_HEADER}, follow_redirects=True)
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'targets': TARGET}
    record['explore'] = check_explore(client)
    record['recommend'], record['connect'] = check_recommend_and_connect(client)
    record['pages'] = check_pages(client)
    record['breaches'] = {k: {'team': OWNER[k], 'bad': record[k]['bad'][:3]}
                          for k in ('explore', 'recommend', 'connect', 'pages') if not record[k]['ok']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
