#!/usr/bin/env python3
"""User-facing targets, measured from outside the way a visitor or an agent experiences them (11-10 user request:
"if there is a target, keep improving toward it"). Internal timings (one SQL query, server-only time) are NOT targets.

Every check goes through the public address https://agentconcierge.biz (Cloudflare and the tunnel included), with
queries the site has never seen. Targets (CLAUDE.md response-time policy, quality target 100%):

  explore      every unseen search answers within 2.0 s with at least one result (11-10 user target)
  recommend    an agent asking find_agents (MCP) gets an answer within 2.0 s; complex answers within 5.0 s
  connect      the top recommended agent answers initialize + tools/list through our gateway with >= 1 tool
  pages        the Explore and Chat pages download within 1.0 s

Each sample opens its own connection (DNS, TCP, TLS included), as a first-time visitor does (11-11 PM); page and
explore samples record the Cloudflare cache state and airport.

Writes one JSON line to logs/ops/user-slo.jsonl and prints it. "breaches" lists only failed targets, each with
the owning team, so scripts/ops_auto.py can hand them over on the status board.
"""
import json
import os
import random
import re
import socket
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
TARGET = {'explore_s': 2.0, 'recommend_s': 2.0, 'complex_s': 5.0, 'page_s': 1.0}  # 11-11 19시 사용자 결정(추천 2초·페이지 1초)
OWNER = {'explore': '검색과 RAG', 'recommend': '검색과 RAG', 'connect': '검색과 RAG', 'pages': '성장·유통'}
MCP_HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}


def unseen(n):
    picks = random.sample(TOPICS, n)
    return [f'{t} {random.choice(MODIFIERS)} {random.randint(10, 999)}' for t in picks]


class _Phases:
    """Where one sample's time went (11-11 PM): DNS, TCP, TLS, first byte and whole body, all from the start of
    the sample, from httpcore's trace events of the first request on the new connection. The verdict still uses
    the whole time ('s'); these only show which leg was slow (e.g. find_agents: first byte 2-3 s, body 2-28 s)."""

    def __init__(self):
        self.started = time.monotonic()
        self.at = {}

    def trace(self, event, info):
        name = event.split('.', 1)[-1]          # 'connection.connect_tcp.complete' -> 'connect_tcp.complete'
        self.at.setdefault(name, time.monotonic() - self.started)

    def summary(self, response=None):
        def at(*names):
            found = [self.at[n] for n in names if n in self.at]
            return round(found[0], 3) if found else None
        out = {'dns_s': self.dns_s, 'tcp_s': at('connect_tcp.complete'), 'tls_s': at('start_tls.complete'),
               'first_byte_s': at('receive_response_headers.complete'),
               'body_s': at('receive_response_body.complete', 'response_closed.complete')}
        timing = response.headers.get('server-timing', '') if response is not None else ''
        server = re.search(r'(?:^|,)\s*server\s*;[^,]*?dur=([\d.]+)', timing)
        out['server_ms'] = round(float(server.group(1))) if server else None
        return out


class _TracedTransport(httpx.HTTPTransport):
    def __init__(self, phases, **kwargs):
        super().__init__(**kwargs)
        self.phases = phases

    def handle_request(self, request):
        request.extensions['trace'] = self.phases.trace
        return super().handle_request(request)


LAST = {'phases': None}


def fresh(phases=None):
    """A new client, so each sample pays its own DNS, TCP and TLS like a first-time visitor (11-11 PM: the hour's
    samples used to share one keep-alive connection, which left the handshake out of every sample after the first)."""
    transport = _TracedTransport(phases) if phases else None
    return httpx.Client(timeout=30, headers={'User-Agent': UA, **QA_HEADER}, follow_redirects=True, transport=transport)


def on_fresh(fn):
    """Run fn(client) on a new connection and return its result (the response body is read before closing)."""
    phases = _Phases()
    LAST['phases'] = phases
    host = BASE.split('://', 1)[-1].split('/', 1)[0]
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)   # the resolve a first-time visitor makes
        phases.dns_s = round(time.monotonic() - phases.started, 3)
    except OSError:
        phases.dns_s = None
    with fresh(phases) as client:
        return fn(client)


def phases(response=None):
    """The legs of the sample that just ran (on_fresh), with the server's own time from Server-Timing."""
    current = LAST['phases']
    return current.summary(response) if current else {}


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


def cache(response):
    return response.headers.get('cf-cache-status') if response is not None else None


def colo(response):
    """Cloudflare airport from cf-ray (e.g. '...-LAX'), so a slow hour can be matched to its path (11-11 PM)."""
    ray = response.headers.get('cf-ray', '') if response is not None else ''
    return ray.rsplit('-', 1)[-1] if '-' in ray else None


def check_explore(n=6):
    rows = []
    for query in unseen(n):
        took, response, error = timed(lambda: on_fresh(lambda c: c.get(f'{BASE}/api/explore', params={'q': query})))
        total = None
        if response is not None and response.status_code == 200:
            try:
                total = response.json().get('total')
            except ValueError:
                pass
        rows.append({'q': query, 's': took, 'status': getattr(response, 'status_code', error), 'total': total,
                     'colo': colo(response), 'cache': cache(response), **phases(response)})
    bad = [r for r in rows if r['s'] > TARGET['explore_s'] or r['status'] != 200 or not r['total']]
    return {'samples': rows, 'max_s': max(r['s'] for r in rows), 'ok': not bad, 'bad': bad}


def check_recommend_and_connect(n=2):
    rec, conn = [], []
    for task in unseen(n):
        took, result, error = timed(lambda: on_fresh(lambda c: mcp(c, f'{BASE}/mcp', 'tools/call',
                                                                   {'name': 'find_agents', 'arguments': {'task': task}})))
        text = ''
        if result:
            try:
                text = result[1]['result']['content'][0]['text']
            except (KeyError, IndexError, TypeError):
                text = ''
        rec.append({'task': task, 's': took, 'answered': bool(text), 'error': error,
                    **phases(result[0] if result else None)})
        endpoint = next((line.split('Endpoint:', 1)[1].strip().split()[0] for line in text.splitlines()
                         if 'Endpoint:' in line and '/api/gateway/' in line), None)
        if not endpoint:
            continue
        if '/api/gateway/mcp/' in endpoint:
            def connect(client):  # one connection for the pair: the session belongs to it
                init, _ = mcp(client, endpoint, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                                'clientInfo': {'name': 'user-slo', 'version': '1'}})
                listed, body = mcp(client, endpoint, 'tools/list', session=init.headers.get('mcp-session-id'), rid=2)
                return len((body.get('result') or {}).get('tools') or [])
        else:
            # A2A recommendation (11-11): connecting means the gateway serves the agent's card; no message is sent.
            def connect(client):
                response = client.get(endpoint, headers={'Accept': 'application/json'})
                return 1 if response.status_code == 200 else 0
        took_c, tools, error_c = timed(lambda: on_fresh(connect))
        conn.append({'endpoint': endpoint.rsplit('/', 2)[-2] + '/' + endpoint.rsplit('/', 1)[-1], 's': took_c,
                     'tools': tools, 'error': error_c})
    rec_bad = [r for r in rec if r['s'] > TARGET['recommend_s'] or not r['answered']]
    conn_bad = [c for c in conn if not c['tools']]
    # No gateway endpoint among the answers means connect was not measured this hour; that is recorded, not hidden,
    # but it is not counted as a failed connection (11-11: 14:02 run had two answers with no gateway endpoint).
    return ({'samples': rec, 'ok': not rec_bad, 'bad': rec_bad},
            {'samples': conn, 'ok': not conn_bad, 'bad': conn_bad, 'measured': bool(conn)})


def check_pages():
    rows = []
    for path in ('/new/en/explore.html', '/new/en/chat.html', '/'):
        took, response, error = timed(lambda: on_fresh(lambda c: c.get(BASE + path, headers={'Accept': 'text/html'})))
        rows.append({'path': path, 's': took, 'status': getattr(response, 'status_code', error), 'colo': colo(response),
                     'cache': cache(response), **phases(response)})  # 11-11 PM: edge state and legs next to the time
    bad = [r for r in rows if r['s'] > TARGET['page_s'] or r['status'] != 200]
    return {'samples': rows, 'ok': not bad, 'bad': bad}


def main():
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'targets': TARGET, 'connection': 'new per sample'}
    record['load_1_start'] = round(os.getloadavg()[0], 2)   # 11-12 PM: never put off for load; record it
    record['explore'] = check_explore()
    record['recommend'], record['connect'] = check_recommend_and_connect()
    record['pages'] = check_pages()
    record['load_1_end'] = round(os.getloadavg()[0], 2)
    record['breaches'] = {k: {'team': OWNER[k], 'bad': record[k]['bad'][:3]}
                          for k in ('explore', 'recommend', 'connect', 'pages') if not record[k]['ok']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
