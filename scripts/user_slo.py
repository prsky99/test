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
the owning team, up to three example samples ('bad'), the exact number of failed samples ('bad_count') and of
samples taken ('n'), so scripts/ops_auto.py can hand them over on the status board.
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

try:  # run as python -m scripts.<name> or as a file
    from scripts.slo_targets import FINAL, INTERIM, attainment
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from slo_targets import FINAL, INTERIM, attainment

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
TARGET = FINAL  # 11-11 19시 사용자 결정(추천 2초·페이지 1초); the interim target (11-14) is judged beside it
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
        # The server's own stages, largest first (PM 11-12 19:0x: the 18:04 misses kept only the total, so the
        # stage split had to be measured again). The slowest 8 are enough to name where server time went.
        found = {}
        for name, value in re.findall(r'(?:^|,)\s*([\w.]+)\s*;[^,]*?dur=([\d.]+)', timing):
            if name != 'server':
                found[name] = max(found.get(name, 0), round(float(value)))
        out['stages'] = dict(sorted(found.items(), key=lambda item: -item[1])[:8])
        # Garbage collection is kept even when it is not among the slowest 8 (PM 11-13 20:2x).
        out['stages'].update({name: found[name] for name in ('gc', 'gc_all') if name in found})
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


GATEWAY = re.compile(r'Endpoint:\s*(\S*/api/gateway/\S+)')
FIRST_ITEM = re.compile(r'^\s*1\.\s')
NEXT_ITEM = re.compile(r'^\s*[2-9]\d*\.\s|^\s*1\d+\.\s')


def connection_route(text):
    """The gateway endpoint of the answer's first recommendation, or None.

    11-12 PM decision (나-1): the answer never shows a provider's own address; a recommendation the gateway does not
    relay carries connection_available=False and a documentation link only. Such a first recommendation has no
    path to follow and counts as a failed connection; nothing is skipped."""
    lines, inside = text.splitlines(), False
    for line in lines:
        if not inside:
            inside = bool(FIRST_ITEM.match(line))
            if not inside:
                continue
        elif NEXT_ITEM.match(line):
            break
        found = GATEWAY.search(line)
        if found:
            return found.group(1)
    return None


def first_card(body):
    """The first recommendation card of find_agents' structured reply, or None."""
    try:
        cards = body['result']['structuredContent']['recommendations']
    except (KeyError, TypeError):
        return None
    return cards[0] if isinstance(cards, list) and cards and isinstance(cards[0], dict) else None


def first_card_available(body):
    """connection_available of the first recommendation card in find_agents' structured reply, or None.

    False means the gateway does not relay that recommendation (an action tool); a failed sample with True is a real
    connection failure (검색과 RAG 11-12: separates the two causes). Recorded only; the verdict is unchanged."""
    value = (first_card(body) or {}).get('connection_available')
    return value if isinstance(value, bool) else None


def failure_reason(entry, card):
    """Why a connect sample failed, recorded beside the verdict (PM 11-13 decision 2: nothing is excluded).

    policy_blocked: the gateway does not relay the recommended tool because the tool itself acts (send_email);
    unverified_tool: a read tool the gateway has not verified as read-only (fixable on our side);
    unrelayed: not relayed, from a card that predates the reason field; connect_failed: the connection itself failed;
    no_gateway_endpoint / no_recommendation as before. None for a passing sample."""
    if entry.get('tools') and entry.get('error') != 'tool_unlisted':
        return None
    if entry.get('error') in ('no_gateway_endpoint', 'no_recommendation'):
        return entry['error']
    reason = (card or {}).get('connection_reason')
    if reason == 'action_tool':
        return 'policy_blocked'
    if reason == 'not_verified_read_only':
        return 'unverified_tool'
    failure = entry.get('failure') or {}
    if 'provider authorization' in str(failure.get('detail') or '').lower() or failure.get('error_code') in (
            'provider_auth_required', 'not_authorized'):
        return 'provider_auth_required'     # 11-14: the recommended agent needs the caller's own provider key
    if entry.get('connection_available') is False or entry.get('error') == 'tool_unlisted':
        return 'unrelayed'
    if failure.get('stage') == 'tools/list' and failure.get('status') == 200 and not failure.get('error_code'):
        return 'no_relayed_tools'           # 11-14: connected, but no tool is verified read-only for relaying
    if failure.get('cause'):
        return 'gateway:' + str(failure['cause'])[:40]   # the edge Worker's error.data.cause (09da7f12, 11-14)
    return 'connect_failed'


def failure_detail(stage, response, body):
    """What a failed connect step answered (11-14 PM: count connection failures by their cause): HTTP status, the
    JSON-RPC or problem error code, the edge Worker's cause and a short detail. No provider text beyond 120 chars."""
    body = body if isinstance(body, dict) else {}
    error = body.get('error') if isinstance(body.get('error'), dict) else {}
    data = error.get('data') if isinstance(error.get('data'), dict) else {}
    return {'stage': stage, 'status': getattr(response, 'status_code', None),
            'error_code': data.get('error_code') or body.get('error_code'), 'cause': data.get('cause'),
            'detail': str(error.get('message') or body.get('detail') or '')[:120] or None}


def recommended_tool(body):
    """The tool the first recommendation names (card 'tools'[0]), or None."""
    tools = (first_card(body) or {}).get('tools')
    return tools[0] if isinstance(tools, list) and tools and isinstance(tools[0], str) else None


# PM 11-12 16:2x: a connect counts only when the recommended tool is on the gateway's tools/list (16:01 mcp/43775
# connected with 27 tools while the recommended tool was not relayed). Judged from the hour after the 11-13 08:10
# alignment bundle; before that it is recorded only.
TOOL_LISTED_FROM = time.mktime((2026, 11, 13, 9, 0, 0, 0, 0, -1))


def connector(endpoint, seen=None):
    """A read-only connect through the gateway: MCP initialize + tools/list, or the A2A card. No tools/call.
    A failed step leaves its failure_detail in `seen` (11-14)."""
    seen = {} if seen is None else seen

    def parsed(response):
        try:
            return response.json()
        except ValueError:
            return {}
    if '/api/gateway/a2a/' in endpoint:
        # A2A (11-11): connecting means the gateway serves the agent's card; no message is sent.
        def connect(client):
            response = client.get(endpoint, headers={'Accept': 'application/json'})
            if response.status_code != 200:
                seen.update(failure_detail('agent card', response, parsed(response)))
            return ['(agent card)'] if response.status_code == 200 else []
        return connect

    def connect(client):  # one connection for the pair: the session belongs to it
        init, first = mcp(client, endpoint, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                            'clientInfo': {'name': 'user-slo', 'version': '1'}})
        if init.status_code != 200 or 'error' in first:
            seen.update(failure_detail('initialize', init, first))
            return []
        listed, body = mcp(client, endpoint, 'tools/list', session=init.headers.get('mcp-session-id'), rid=2)
        names = [t.get('name') for t in (body.get('result') or {}).get('tools') or [] if isinstance(t, dict)]
        if not names:
            seen.update(failure_detail('tools/list', listed, body))
        return names
    return connect


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
        available = first_card_available(result[1] if result else None)
        wanted = recommended_tool(result[1] if result else None)
        rec.append({'task': task, 's': took, 'answered': bool(text), 'error': error,
                    **phases(result[0] if result else None)})
        endpoint = connection_route(text)
        if not endpoint:
            # No gateway path for the first recommendation (or no recommendation): a failed connection (PM 11-12).
            # A no-match answer has text but no card: no recommendation, not a card without a gateway path
            # (PM 11-13 22:2x, 22:07 'customer support bulk 926').
            card = first_card(result[1] if result else None)
            entry = {'endpoint': None, 's': 0.0, 'tools': 0, 'connection_available': available,
                     'error': 'no_gateway_endpoint' if text and card is not None else 'no_recommendation'}
            entry['reason'] = failure_reason(entry, first_card(result[1] if result else None))
            conn.append(entry)
            continue
        seen = {}
        took_c, names, error_c = timed(lambda: on_fresh(connector(endpoint, seen)))
        names = names or []
        listed = (wanted in names) if wanted and '/api/gateway/mcp/' in endpoint and names else None
        if listed is False and time.time() >= TOOL_LISTED_FROM:
            error_c = error_c or 'tool_unlisted'
        entry = {'endpoint': endpoint.rsplit('/', 2)[-2] + '/' + endpoint.rsplit('/', 1)[-1], 's': took_c,
                 'tools': len(names), 'error': error_c, 'connection_available': available,
                 'recommended_tool': wanted, 'tool_listed': listed}
        if seen:
            entry['failure'] = seen
        entry['reason'] = failure_reason(entry, first_card(result[1] if result else None))
        conn.append(entry)
    rec_bad = [r for r in rec if r['s'] > TARGET['recommend_s'] or not r['answered']]
    conn_bad = [c for c in conn if not c['tools'] or c.get('error') == 'tool_unlisted']
    # A first recommendation without a gateway path is a failed connection (PM 11-12, replacing the 11-11 rule
    # that left such an hour unmeasured).
    return ({'samples': rec, 'ok': not rec_bad, 'bad': rec_bad},
            {'samples': conn, 'ok': not conn_bad, 'bad': conn_bad, 'measured': bool(conn)})


def breaches(record):
    """Failed targets with their owner, up to three example samples and the exact count (11-12 PM: 'bad' is a
    sample list, so the number of failed samples is kept apart as bad_count and n as the samples taken)."""
    return {k: {'team': OWNER[k], 'bad': record[k]['bad'][:3], 'bad_count': len(record[k]['bad']),
                'n': len(record[k].get('samples') or [])}
            for k in ('explore', 'recommend', 'connect', 'pages') if not record[k]['ok']}


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
    record['breaches'] = breaches(record)
    # 11-14 (user, via PM): the same samples judged against the final and the interim target, none left out.
    record['interim_targets'] = INTERIM
    record['attainment'] = {'final': attainment(record, TARGET), 'interim': attainment(record, INTERIM)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
