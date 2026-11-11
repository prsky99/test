"""Score the real-task answer set on the public site: recommend, connect, call, check.

For each task in tests/data/real_tasks_30.json:
  1. ask find_agents on https://agentconcierge.biz/mcp (read-only, saves no conversation);
  2. take the first recommendation and call it through our gateway (/api/gateway/{kind}/{id}):
     MCP: initialize -> tools/list -> one tools/call of a registered informational tool;
     A2A: message/send with the task text and its sample input;
  3. grade the answer with the task's "check" patterns (every regex must match).

Nothing is paid and no credential is sent. Gateway calls are paced under the public limit (10 a minute per
address) and a 429 is retried once after Retry-After, so the score measures the agents, not our rate limit. Tools whose names look like writes (create, delete, send, ...)
are never called; the gateway itself only admits registered informational tools. Each task is one call.

Outcomes: pass, or one cause: no_recommendation, wrong_recommendation (no needed word in the agent or
tool), connection_failed (initialize/tools/list/transport error, or the provider is down, slow or answers an
invalid protocol), no_tool (no callable tool), bad_answer (the call answered but the check failed),
call_failed (the call was refused for its arguments or by policy), paid_or_auth_required (connected, but the
answer, error or tool says a paid plan, API key or sign-in is needed: 11-11 PM, counts as failed),
listing_only (free_check false: not called, scored as not passed).

    .venv/bin/python -m scripts.real_task_score              # all tasks, writes reports/real-task-score/
    .venv/bin/python -m scripts.real_task_score --only a04,p07 --out /tmp/x.json
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / 'tests/data/real_tasks_30.json'
BASE = 'https://agentconcierge.biz'
UA = 'agentconcierge-real-task-score/1.0'
QA_HEADER = {'X-Agentcon-QA': 'real_task_score'}  # 11-11: lets the error ledger set our own measurements apart
WRITE_WORDS = re.compile(r'(?i)(^|[_\-.])(create|delete|remove|update|write|send|post|put|patch|pay|transfer|buy|sell|'
                         r'order|book|submit|register|upload|publish|execute_trade|mint|deploy|drop|insert)([_\-.]|$)')
STOP = set('a an the of for to and or with by from in on at is are be that this its it as into than up per'.split())
SYNONYMS = {
    'query': ['query', 'q', 'search', 'term', 'keyword', 'keywords', 'text', 'prompt', 'input', 'topic', 'title', 'name'],
    'url': ['url', 'source_url', 'file_url', 'link', 'uri', 'page', 'pdf_url', 'source'],
    'id': ['id', 'paper_id', 'arxiv_id', 'identifier'],
    'symbol': ['symbol', 'ticker', 'coin', 'asset', 'id'],
    'currency': ['currency', 'vs_currency', 'quote', 'to'],
    'city': ['city', 'location', 'place', 'q', 'query', 'name'],
    'domain': ['domain', 'hostname', 'host', 'name', 'query'],
    'package': ['package', 'name', 'package_name', 'pkg', 'query'],
    'address': ['address', 'query', 'q', 'location', 'text'],
    'title': ['title', 'page', 'query', 'q', 'topic', 'name'],
    'ip': ['ip', 'ip_address', 'address', 'query'],
    'from': ['from', 'base', 'source', 'from_currency'],
    'to': ['to', 'target', 'symbols', 'to_currency', 'target_lang', 'target_language'],
    'amount': ['amount', 'value', 'quantity'],
    'text': ['text', 'q', 'query', 'input', 'content'],
    'target': ['target', 'target_lang', 'target_language', 'to', 'lang'],
    'country': ['country', 'country_code', 'countryCode', 'code'],
    'year': ['year'],
    'ecosystem': ['ecosystem'],
    'cve': ['cve', 'cve_id', 'id', 'query'],
    'ticker': ['ticker', 'symbol', 'query'],
    'zones': ['zones', 'timezones', 'timezone', 'tz'],
    'days': ['days', 'forecast_days'],
    'limit': ['limit', 'max_results', 'count', 'n'],
    'state': ['state', 'area'],
    'min_magnitude': ['min_magnitude', 'minmagnitude', 'magnitude'],
    'schema': ['schema'], 'instance': ['instance', 'value', 'data', 'json', 'document'],
}


def words(text):
    return {w for w in re.findall(r'[a-z0-9]+', str(text).lower()) if len(w) > 2 and w not in STOP}


GATEWAY_PER_MINUTE = 9  # the public gateway allows 10 agent requests a minute per address; stay under it
_gateway_calls = []


def pace(url, clock=time.monotonic, sleep=time.sleep):
    """Keep gateway calls under the public per-address limit, as a single well-behaved client would."""
    if '/api/gateway/' not in url:
        return
    while True:
        now = clock()
        _gateway_calls[:] = [t for t in _gateway_calls if now - t < 60]
        if len(_gateway_calls) < GATEWAY_PER_MINUTE:
            _gateway_calls.append(now)
            return
        sleep(60 - (now - _gateway_calls[0]) + 0.5)


def rpc(client, url, method, params=None, rid=1):
    body = {'jsonrpc': '2.0', 'id': rid, 'method': method}
    if params is not None:
        body['params'] = params
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'MCP-Protocol-Version': '2025-06-18'}
    pace(url)
    r = client.post(url, json=body, headers=headers)
    if r.status_code == 429:  # honour Retry-After once; a second 429 is reported as it is
        time.sleep(min(float(r.headers.get('Retry-After') or 60), 90))
        pace(url)
        r = client.post(url, json=body, headers=headers)
    try:
        data = r.json()
    except ValueError:
        data = {'error': {'code': r.status_code, 'message': r.text[:200]}}
    return r.status_code, data


def recommend(client, task):
    status, data = rpc(client, BASE + '/mcp', 'tools/call', {'name': 'find_agents', 'arguments': {'task': task}})
    sc = (data.get('result') or {}).get('structuredContent') or {}
    for key in ('agents', 'recommendations', 'items', 'results'):
        if isinstance(sc.get(key), list):
            return status, sc[key]
    return status, []


def arguments_for(schema, sample, task_text):
    props = (schema or {}).get('properties') or {}
    required = list((schema or {}).get('required') or [])
    args = {}
    for key, value in sample.items():
        if key in props:
            args[key] = value
            continue
        for alias in SYNONYMS.get(key, [key]):
            if alias in props and alias not in args:
                args[alias] = value if not isinstance(value, list) else ','.join(map(str, value))
                break
        else:
            # One value for a list field named in the plural ("cve" -> cves: [..], "address" -> addresses):
            # an agent passes the one item it has (11-11 p05, a05 were called with {}).
            plural = next((p for p in (key + 's', key + 'es') if (props.get(p) or {}).get('type') == 'array'), None)
            if plural and plural not in args:
                args[plural] = value if isinstance(value, list) else [value]
    for key in required:
        if key in args:
            continue
        kind = (props.get(key) or {}).get('type')
        if kind in (None, 'string'):
            strings = [v for v in sample.values() if isinstance(v, str)]
            args[key] = strings[0] if strings else task_text
        elif kind in ('integer', 'number'):
            nums = [v for v in sample.values() if isinstance(v, (int, float))]
            if nums:
                args[key] = nums[0]
    want = words(task_text)
    for key, spec in props.items():  # allowed values: match case-insensitively, or choose one the task names
        enum = (spec or {}).get('enum')
        if not isinstance(enum, list) or not enum:
            continue
        if key in args:
            hit = [e for e in enum if str(e).lower() == str(args[key]).lower()]
            if hit:
                args[key] = hit[0]
                continue
        after_to = words(task_text.lower().rsplit(' to ', 1)[1]) if ' to ' in task_text.lower() else set()
        def names(e, pool):
            e = str(e).lower()
            return e in pool or (e == 'txt' and 'text' in pool)
        named = [e for e in enum if names(e, after_to)] or [e for e in enum if names(e, want)]  # "PDF to text": the target
        if named and (key in required or key in args):
            args[key] = named[0]
    for key, value in list(args.items()):  # follow the declared scalar types
        kind = (props.get(key) or {}).get('type')
        if kind == 'string' and not isinstance(value, str):
            args[key] = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        elif kind in ('integer', 'number') and isinstance(value, str) and re.fullmatch(r'-?\d+(\.\d+)?', value):
            args[key] = int(value) if kind == 'integer' else float(value)
    return args


def pick_tool(tools, needs, preferred):
    callable_tools = [t for t in tools if isinstance(t, dict) and t.get('name') and not WRITE_WORDS.search(t['name'])]
    if not callable_tools:
        return None
    stem = lambda ws: {w[:6] for w in ws}  # noqa: E731  ("geocoding" and "geocode" are one word here)
    want = stem(words(needs))
    def score(t):
        named = 1 if t['name'] in preferred else 0
        hit = len(want & stem(words(t['name'] + ' ' + str(t.get('description', '')))))
        if 'revers' in stem(words(t['name'])) and 'revers' not in want:
            hit -= 1  # a reverse lookup is the opposite of the task unless the task asks for it
        return (hit, named)
    return max(callable_tools, key=score)


PAID = re.compile(r'(?i)requires? (a |an )?(\w+ )?(tier|plan|subscription|api[ _-]?key|token|account|login|sign[ -]?in)|'
                  r'(team|pro|premium|paid|enterprise) (tier|plan) (or above|required)|upgrade (your|to)|payment required|'
                  r'unauthori[sz]ed|forbidden|invalid api key|missing api key|authentication (is )?required|\bx402\b')


def paid_or_auth(status, *texts):
    """The provider answered, but only a paid plan, key or sign-in unlocks the task (11-11 PM: counts as failed)."""
    return status in (401, 402, 403) or any(PAID.search(str(t or '')) for t in texts)


def failure(status, answer):
    """An upstream that is down, slow or answers an invalid protocol is a connection failure; an error about our
    request (arguments, policy) is a call failure."""
    error = (answer or {}).get('error') or {}
    code = str(((error.get('data') or {}).get('error_code')) or '')
    if status >= 500 or status in (0, 404) or code.startswith(('UPSTREAM', 'PROVIDER', 'TIMEOUT', 'NETWORK')):
        return 'connection_failed'
    return 'call_failed'


def checked(task, payload):
    text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    missing = [p for p in task['check']['all'] if not re.search(p, text)]
    return not missing, missing, len(text)


def score_task(client, task):
    row = {'id': task['id'], 'who': task['who'], 'task': task['task']}
    t0 = time.monotonic()
    status, recs = recommend(client, task['task'])
    row['recommend_s'] = round(time.monotonic() - t0, 2)
    if not recs:
        row.update(outcome='no_recommendation', detail='find_agents status %s, no agents' % status)
        return row
    top = recs[0]
    row['agent'] = {'id': top.get('id'), 'name': top.get('name'), 'kind': top.get('kind'), 'tools': (top.get('tools') or [])[:5]}
    agent_words = words(' '.join([str(top.get('name') or ''), ' '.join(map(str, top.get('tools') or [])), str(top.get('description') or '')]))
    relevant = bool(words(task['needs']) & agent_words)
    if not task.get('free_check', True):
        row.update(outcome='listing_only', detail='not called: the task needs a paid or keyed source (free_check false)',
                   relevant=relevant)
        return row
    kind, rid = top.get('kind'), top.get('id')
    gateway = '%s/api/gateway/%s/%s' % (BASE, kind, rid)
    t1 = time.monotonic()
    try:
        if kind == 'mcp':
            st, init = rpc(client, gateway, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                           'clientInfo': {'name': 'real-task-score', 'version': '1'}})
            if 'result' not in init:
                row.update(outcome='connection_failed', detail='initialize %s %s' % (st, json.dumps(init.get('error'))[:160]))
                return row
            st, listed = rpc(client, gateway, 'tools/list', {}, 2)
            tools = (listed.get('result') or {}).get('tools') if isinstance(listed, dict) else None
            if tools is None:
                row.update(outcome='connection_failed', detail='tools/list %s %s' % (st, json.dumps(listed.get('error'))[:160]))
                return row
            # The recommendation names its tools and their input schemas (tools_schema): an agent uses those first.
            # Recommended tools (tools_schema) break ties; the tool that best matches the task wins, so a
            # recommendation that shows the wrong direction (reverse_geocode for geocoding) is recorded below.
            recommended = {t.get('name') for t in (top.get('tools_schema') or []) if isinstance(t, dict)} | set(top.get('tools') or [])
            tool = pick_tool(tools, task['needs'] + ' ' + task['task'], recommended)
            if tool and recommended and tool['name'] not in recommended:
                row['recommended_tool_mismatch'] = sorted(recommended)[:3]
            row['tool_source'] = 'recommendation' if tool and tool['name'] in recommended else 'tools/list'
            if not tool:
                row.update(outcome='no_tool', detail='tools/list returned %d tools, none callable' % len(tools))
                return row
            args = arguments_for(tool.get('inputSchema'), task['sample_input'], task['task'])
            row['call'] = {'tool': tool['name'], 'arguments': args}
            st, answer = rpc(client, gateway, 'tools/call', {'name': tool['name'], 'arguments': args}, 3)
            row['connect_call_s'] = round(time.monotonic() - t1, 2)
            if 'result' not in answer:
                cause = 'paid_or_auth_required' if paid_or_auth(st, json.dumps(answer.get('error'))) else failure(st, answer)
                row.update(outcome=cause, detail='tools/call %s %s' % (st, json.dumps(answer.get('error'))[:200]))
                return row
            payload = answer['result']
            row['_tool_text'] = tool.get('description', '')
        elif kind == 'a2a':
            text = task['task'] + '\nInput: ' + json.dumps(task['sample_input'])
            st, answer = rpc(client, gateway, 'message/send', {'message': {'kind': 'message', 'role': 'user',
                             'messageId': 'rts-%s-%d' % (task['id'], int(time.time())), 'parts': [{'kind': 'text', 'text': text}]}})
            row['connect_call_s'] = round(time.monotonic() - t1, 2)
            if 'result' not in answer:
                cause = 'paid_or_auth_required' if paid_or_auth(st, json.dumps(answer.get('error'))) else failure(st, answer)
                row.update(outcome=cause, detail='message/send %s %s' % (st, json.dumps(answer.get('error'))[:200]))
                return row
            payload = answer['result']
        else:
            row.update(outcome='no_tool', detail='kind %s is not called (x402 needs payment)' % kind)
            return row
    except httpx.HTTPError as exc:
        row.update(outcome='connection_failed', detail=type(exc).__name__, connect_call_s=round(time.monotonic() - t1, 2))
        return row
    ok, missing, size = checked(task, payload)
    row['answer_chars'] = size
    tool_text = row.pop('_tool_text', '')
    if ok:
        row['outcome'] = 'pass'
    elif paid_or_auth(0, json.dumps(payload, ensure_ascii=False)[:4000], tool_text):
        row.update(outcome='paid_or_auth_required', detail='the answer or tool asks for a paid plan, key or sign-in')
    else:
        row.update(outcome='bad_answer' if relevant else 'wrong_recommendation',
                   detail='check failed: ' + ', '.join(missing)[:200])
        row['answer_head'] = (json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload)[:300]
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--only')
    ap.add_argument('--out')
    ap.add_argument('--timeout', type=float, default=40.0)
    args = ap.parse_args(argv)
    tasks = json.loads(TASKS.read_text())['tasks']
    if args.only:
        keep = set(args.only.split(','))
        tasks = [t for t in tasks if t['id'] in keep]
    started = datetime.now(timezone.utc)
    rows = []
    with httpx.Client(timeout=args.timeout, headers={'User-Agent': UA, **QA_HEADER}, follow_redirects=False) as client:
        for task in tasks:
            t0 = time.monotonic()
            try:
                row = score_task(client, task)
            except Exception as exc:  # one broken task never stops the run
                row = {'id': task['id'], 'outcome': 'call_failed', 'detail': 'scorer error ' + type(exc).__name__}
            row['total_s'] = round(time.monotonic() - t0, 2)
            rows.append(row)
            print('%-4s %-21s %6.1fs  %s' % (row['id'], row['outcome'], row['total_s'], (row.get('agent') or {}).get('name', '')), flush=True)
    passed = sum(r['outcome'] == 'pass' for r in rows)
    causes = {}
    for r in rows:
        if r['outcome'] != 'pass':
            causes[r['outcome']] = causes.get(r['outcome'], 0) + 1
    summary = {'at': started.isoformat(timespec='seconds'), 'base': BASE, 'tasks': len(rows), 'passed': passed,
               'score': round(passed / len(rows), 3) if rows else 0.0, 'causes': causes,
               'by_who': {w: '%d/%d' % (sum(r['outcome'] == 'pass' for r in rows if r.get('who') == w), sum(r.get('who') == w for r in rows))
                          for w in ('person', 'agent')}}
    report = {'summary': summary, 'rows': rows}
    out = Path(args.out) if args.out else ROOT / 'reports/real-task-score' / (started.strftime('%Y-%m-%d') + '.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    log = ROOT / 'logs/ops/real-task-score.jsonl'
    if not args.only:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as fh:
            fh.write(json.dumps(summary, ensure_ascii=False) + '\n')
    print(json.dumps(summary, ensure_ascii=False))
    return report


if __name__ == '__main__':
    main()
