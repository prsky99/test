"""Guidance accuracy for paid or impossible tasks, kept apart from the completion score (PM 11-11 23시).

    .venv/bin/python -m scripts.heavy_slot --team 성장·유통 --what "유료 과제 안내 정확도" --minutes 5 -- \
        .venv/bin/python -m scripts.paid_task_guidance

A task marked free_check false in tests/data/real_tasks_30.json (today: p15, a YouTube transcript) cannot be
completed for free, so real_task_score counts it as failed and keeps doing so. This score asks a different
question: did Agent Concierge point the visitor at a source that really does the task, and say up front that it
costs money or needs a key? The top recommendation passes only if all four hold:

  input_fit   the recommended tool takes the task's input (a link for a link, not only a file or base64),
              read from the tool's schema in the gateway's tools/list
  output_fit  the tool says it returns the thing asked for (caption text), not a summary or metadata only
  disclosed   the recommendation states the price or the key before connecting (price_usdc > 0, x402, or
              auth_required), and that statement agrees with the unpaid call below
  unpaid_call one call through the gateway with the sample input and no payment or key answers 401, 402 or 403
              (or a payment/key error); a 402 must name a price. Nothing is ever paid.

If the unpaid call simply succeeds and returns what the task needs, the task is not paid after all: the row says
free_source_found and the task should move back to real calls (weekly re-check, PM 11-11).
Rows go to reports/paid-task-guidance/<date>.json; the completion score is not touched.
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

from scripts.real_task_score import BASE, PAID, TASKS, UA, arguments_for, checked, rpc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/paid-task-guidance'
QA_HEADER = {'X-Agentcon-QA': 'paid_task_guidance'}
LINKY = re.compile(r'(?i)\b(url|uri|link|href|video_?id|youtube)\b|https?://')
FILEY = re.compile(r'(?i)\b(file|file_?path|path|base64|audio|bytes|blob|upload|attachment)\b')
WANTS = {  # what the tool must say it returns, by task id; a missing id falls back to the task's "needs" words
    'p15': re.compile(r'(?i)transcript|caption|subtitle'),
}
SUMMARY_ONLY = re.compile(r'(?i)\b(summar(y|ies|ize)|key points|chapters|metadata)\b')
PRICE = re.compile(r'(?i)(\$\s?\d|\d+(\.\d+)?\s?usdc|\bprice\b|amount|maxAmountRequired|per (call|minute|request))')


def schema_props(tool):
    props = ((tool or {}).get('inputSchema') or {}).get('properties') or {}
    return {k: (v or {}) for k, v in props.items() if isinstance(v, dict) or v is None}


def input_fit(tool, sample):
    """The task gives a link: some string field must take a link; a tool that takes only files or base64 fails."""
    if not tool:
        return False, 'no tool'
    props = schema_props(tool)
    gives_link = any(isinstance(v, str) and v.startswith(('http://', 'https://')) for v in sample.values())
    linky = [k for k, v in props.items() if LINKY.search(k) or LINKY.search(str(v.get('description', '')))]
    if gives_link and not linky:
        filey = [k for k in props if FILEY.search(k)]
        return False, 'takes %s, not a link' % (', '.join(filey or sorted(props)) or 'nothing')
    return True, 'link field: %s' % ', '.join(linky) if linky else 'no link needed'


def output_fit(task, tool):
    text = '%s %s' % ((tool or {}).get('name', ''), (tool or {}).get('description', ''))
    wants = WANTS.get(task['id']) or re.compile('|'.join(map(re.escape, re.findall(r'[a-z]{5,}', task['needs'].lower()))) or '.')
    if not wants.search(text):
        return False, 'tool does not say it returns %s' % task['needs']
    if SUMMARY_ONLY.search(text) and not re.search(r'(?i)full|raw|plain|timed|text of', text):
        return False, 'summary or metadata only'
    return True, 'returns %s' % wants.pattern


def disclosed(rec):
    """What the recommendation tells the visitor before connecting: 'paid', 'key' or None (presented as free)."""
    if (rec.get('price_usdc') or 0) > 0 or str(rec.get('method') or '').lower() == 'x402' or rec.get('kind') == 'x402':
        return 'paid'
    if rec.get('auth_required'):
        return 'key'
    return None


def unpaid_call(client, gateway, tool, task):
    """One tools/call with no payment and no key. Returns (kind, detail): paid, key, free, error."""
    args = arguments_for(tool.get('inputSchema'), task['sample_input'], task['task'])
    status, answer = rpc(client, gateway, 'tools/call', {'name': tool['name'], 'arguments': args}, 3)
    text = json.dumps(answer, ensure_ascii=False)[:4000]
    if 'result' in answer and not (answer['result'] or {}).get('isError'):
        ok, _, _ = checked(task, answer['result'])
        return ('free' if ok else 'error'), 'answered without payment; check %s' % ('passed' if ok else 'failed')
    if status == 402 or re.search(r'(?i)\b402\b|payment required|x402', text):
        return ('paid' if PRICE.search(text) else 'error'), '402 %s' % ('with a price' if PRICE.search(text) else 'without a price')
    if status in (401, 403) or PAID.search(text):
        return 'key', '%s %s' % (status, text[:160])
    return 'error', '%s %s' % (status, text[:160])


def score(client, task):
    row = {'id': task['id'], 'task': task['task']}
    status, data = rpc(client, BASE + '/mcp', 'tools/call', {'name': 'find_agents', 'arguments': {'task': task['task']}})
    sc = (data.get('result') or {}).get('structuredContent') or {}
    recs = next((sc[k] for k in ('recommendations', 'agents', 'items') if isinstance(sc.get(k), list)), [])
    if not recs:
        row.update(passed=False, detail='no recommendation (find_agents %s)' % status)
        return row
    rec = recs[0]
    row['agent'] = {'id': rec.get('id'), 'name': rec.get('name'), 'kind': rec.get('kind'),
                    'price_usdc': rec.get('price_usdc'), 'auth_required': rec.get('auth_required')}
    told = disclosed(rec)
    row['disclosed'] = told
    named = (rec.get('reason') or {}).get('tool') or (rec.get('tools') or [None])[0]
    tool, unpaid = None, ('error', 'not called')
    if rec.get('kind') == 'mcp':
        gateway = '%s/api/gateway/mcp/%s' % (BASE, rec.get('id'))
        rpc(client, gateway, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                            'clientInfo': {'name': 'paid-task-guidance', 'version': '1'}})
        st, listed = rpc(client, gateway, 'tools/list', {}, 2)
        tools = ((listed.get('result') or {}).get('tools') or []) if isinstance(listed, dict) else []
        tool = next((t for t in tools if isinstance(t, dict) and t.get('name') == named), None)
        if tool:
            unpaid = unpaid_call(client, gateway, tool, task)
    row['tool'] = named
    checks = {}
    checks['input_fit'] = input_fit(tool, task['sample_input'])
    checks['output_fit'] = output_fit(task, tool) if tool else (False, 'tool %s not in tools/list' % named)
    checks['unpaid_call'] = (unpaid[0] in ('paid', 'key'), '%s: %s' % unpaid)
    agrees = told is not None and unpaid[0] in ('paid', 'key') and (told == unpaid[0] or told == 'paid')
    checks['disclosed'] = (agrees, 'recommendation says %s, unpaid call says %s' % (told or 'free', unpaid[0]))
    row['checks'] = {k: {'ok': v[0], 'why': v[1]} for k, v in checks.items()}
    row['passed'] = all(v[0] for v in checks.values())
    row['free_source_found'] = unpaid[0] == 'free'
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--only', help='one task id')
    args = ap.parse_args(argv)
    data = json.loads(TASKS.read_text())
    tasks = [t for t in (data['tasks'] if isinstance(data, dict) else data) if t.get('free_check') is False]
    if args.only:
        tasks = [t for t in tasks if t['id'] == args.only]
    started = time.monotonic()
    with httpx.Client(timeout=60, headers={'User-Agent': UA, **QA_HEADER}) as client:
        rows = [score(client, t) for t in tasks]
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'tasks': len(rows),
              'passed': sum(r['passed'] for r in rows), 'seconds': round(time.monotonic() - started, 1), 'rows': rows}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (datetime.now().strftime('%Y-%m-%d') + '.json')
    runs = json.loads(path.read_text()) if path.is_file() else []
    runs.append(record)
    path.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    print('안내 정확도 %d/%d' % (record['passed'], record['tasks']))
    for r in rows:
        print('-', r['id'], (r.get('agent') or {}).get('name'), r.get('tool'), 'PASS' if r['passed'] else 'FAIL')
        for name, c in (r.get('checks') or {}).items():
            print('   %s %s: %s' % ('✓' if c['ok'] else '✗', name, c['why'][:150]))
        if r.get('free_source_found'):
            print('   무료로 답함: 이 과제는 실제 호출 채점으로 옮길 후보')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
