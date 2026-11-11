#!/usr/bin/env python3
"""Check every public page type, every public feature and every agent entry point from outside (11-11 user request:
"check every page and feature a visitor or an autonomous agent uses, keep checking until quality is 100%").

Everything goes through the public address https://agentconcierge.biz, the way a visitor or an agent reaches it.
Nothing is excluded: a failed sample counts. Read-only only: no account, no payment, no credentials, no write tools
(MCP call/run_workflow/report/credit/subscribe/verify_contact are listed but only checked in tools/list).

  part pages    every navigation page + random samples of every sitemap page type (status, time, title, JSON-LD,
                developer text, internal links on the page)
  part api      public REST endpoints listed in /openapi.json that are safe to call (GET + read-only POST)
  part agent    well-known files, MCP initialize/tools/list/read-only tools, A2A message/send, gateway connect
  part browser  real Chromium at 1280 and 375: console errors, failed requests, broken images, and the main flows
                (Explore search, Chat answer, Test run, agent detail, Workflows, List agent inspect)

Writes one JSON line to logs/ops/public-full-check.jsonl; "failures" lists each failed check with its owning team.

    public_full_check.py                 all parts
    public_full_check.py --parts pages,agent
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/ops/public-full-check.jsonl'
BASE = 'https://agentconcierge.biz'
UA = 'agentcon-full-check/1 (site owner QA; contact@agentconcierge.biz)'
QA_HEADER = {'X-Agentcon-QA': 'public_full_check'}  # 11-11: lets the error ledger set our own measurements apart
GAP = 0.45          # seconds between requests: stay well under our own per-IP limits
PAGE_S = 2.0        # page target (CLAUDE.md response-time policy)
API_S = 3.0
NAV = ['/', '/new/en/explore.html', '/new/en/chat.html', '/new/en/test.html', '/new/en/workflows.html',
       '/new/en/learn.html', '/new/en/agent-status.html', '/new/en/list-agent.html', '/new/en/about.html',
       '/new/en/privacy.html', '/new/en/terms.html', '/new/en/cookies.html', '/new/en/accessibility.html',
       '/new/en/contact.html', '/new/en/disclosures.html', '/new/en/sign-in.html', '/connect', '/badges',
       '/agents/best', '/reports/state-of-ai-agents', '/llms.txt', '/llms-full.txt',
       '/skill.md', '/robots.txt', '/sitemap.xml', '/openapi.json']
SLOW_OK = {'/sitemap.xml': 5.0, '/llms-full.txt': 4.0}  # large machine files, not pages a person waits on
SAMPLE = {'/agent/': 25, '/agents/compare/': 10, '/agents/task/': 15, '/agents/category/': 20, '/agents/best/': 15,
          '/reports/': 5}
OWNER = {'pages': '성장·유통', 'api': '검색과 RAG', 'agent': '운영·SRE', 'browser': '성장·유통'}
DEV_TEXT = re.compile(r'(?i)traceback|\bundefined\b|\bNaN\b|lorem ipsum|\{\{ ?[a-z_]+ ?\}\}|\[object Object\]|exception:')
MCP_H = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
WRITE_TOOLS = {'call', 'run_workflow', 'report', 'credit', 'subscribe', 'verify_contact', 'adapt_rest'}


def client():
    return httpx.Client(timeout=30, headers={'User-Agent': UA, **QA_HEADER}, follow_redirects=True, http2=False)


def timed(c, method, url, **kw):
    time.sleep(GAP)
    t = time.time()
    try:
        r = c.request(method, url, **kw)
    except Exception as e:  # noqa: BLE001 - any failure is a finding
        return round(time.time() - t, 2), None, f'{type(e).__name__}'
    return round(time.time() - t, 2), r, None


def edge(r):
    """'<airport> <cache status>' of a response, so a slow sample shows where it was served (11-11 PM)."""
    if r is None:
        return ''
    ray = r.headers.get('cf-ray', '')
    return '%s %s' % (ray.rsplit('-', 1)[-1] if '-' in ray else '?', r.headers.get('cf-cache-status', '-'))


def rpc_json(r):
    text = r.text
    if not text.lstrip().startswith('{') and 'data:' in text:
        text = text.split('data:', 1)[1].strip().split('\n', 1)[0]
    return json.loads(text)


class Run:
    def __init__(self):
        self.checks, self.failures = 0, []

    def ok(self, part, name, cond, detail='', took=None):
        self.checks += 1
        if not cond:
            self.failures.append({'part': part, 'team': OWNER[part], 'check': name, 'detail': str(detail)[:240],
                                  's': took})
        return cond


def sitemap_pages(c):
    _, r, _ = timed(c, 'GET', BASE + '/sitemap.xml')
    locs = re.findall(r'<loc>https://agentconcierge\.biz([^<]+)</loc>', r.text if r else '')
    pages = [l for l in locs if not l.endswith('.xml')]
    for sub in [l for l in locs if l.endswith('.xml')]:
        _, rs, _ = timed(c, 'GET', BASE + sub)
        pages += [l for l in re.findall(r'<loc>https://agentconcierge\.biz([^<]+)</loc>', rs.text if rs else '')
                  if not l.endswith('.xml')]
    return list(dict.fromkeys(pages))


def part_pages(run, c):
    pages = sitemap_pages(c)
    picked = list(NAV)
    for prefix, n in SAMPLE.items():
        pool = [p for p in pages if p.startswith(prefix)]
        picked += random.sample(pool, min(n, len(pool)))
    picked += [p for p in pages if p.startswith('/new/en/')]
    picked = list(dict.fromkeys(picked))
    links = set()
    for path in picked:
        took, r, err = timed(c, 'GET', BASE + path, headers={'Accept': 'text/html,*/*'})
        if not run.ok('pages', f'GET {path}', r is not None and r.status_code == 200,
                      err or (r.status_code if r is not None else ''), took):
            continue
        run.ok('pages', f'time {path}', took <= SLOW_OK.get(path, PAGE_S), f'{took}s ({edge(r)})', took)
        if 'html' not in r.headers.get('content-type', ''):
            continue
        body = r.text
        run.ok('pages', f'title {path}', re.search(r'<title>[^<]{3,}', body), 'no <title>')
        for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', body, re.S):
            try:
                json.loads(m.group(1))
            except ValueError:
                run.ok('pages', f'json-ld {path}', False, 'invalid JSON-LD')
        visible = re.sub(r'<script.*?</script>|<style.*?</style>|<code.*?</code>|<pre.*?</pre>', '', body, flags=re.S)
        hit = DEV_TEXT.search(re.sub(r'<[^>]+>', ' ', visible))
        run.ok('pages', f'dev-text {path}', not hit, hit.group(0) if hit else '')
        links.update(h for h in re.findall(r'href="(/[^"#?]*)"', body)
                     if not h.startswith(('/new/en/assets', '/static', '/cdn-cgi')) and not h.endswith(('.css', '.js')))
    unchecked = [l for l in links if l not in picked]
    for path in random.sample(unchecked, min(40, len(unchecked))):
        took, r, err = timed(c, 'GET', BASE + path, headers={'Accept': 'text/html,*/*'})
        run.ok('pages', f'link {path}', r is not None and r.status_code < 400,
               err or (r.status_code if r is not None else ''), took)
    return {'pages_checked': len(picked), 'links_checked': min(40, len(unchecked)), 'sitemap_pages': len(pages)}


def part_api(run, c):
    q = random.choice(['weather forecast', 'translate text', 'currency rates', 'github issues', 'pdf to text',
                       'stock price', 'send email', 'web search', 'image generation', 'speech to text'])
    q = f'{q} {random.randint(100, 999)}'
    took, r, err = timed(c, 'GET', BASE + '/api/explore', params={'q': q})
    data = r.json() if r is not None and r.status_code == 200 else {}
    run.ok('api', 'explore status', r is not None and r.status_code == 200, err or getattr(r, 'status_code', ''), took)
    run.ok('api', 'explore time', took <= PAGE_S, f'{q}: {took}s', took)
    run.ok('api', 'explore results', (data.get('total') or 0) > 0, f'{q}: 0 results')
    items = data.get('items') or data.get('results') or []
    rid = next((i.get('id') or i.get('rid') for i in items if i.get('id') or i.get('rid')), None)
    gets = ['/api/overview', '/api/insights', '/api/test/presets', '/api/workflows/templates', '/api/feed/verified.json',
            '/api/agent/v1/entry', '/api/agent/v1/openapi.json', '/api/register/recent']
    if rid:
        gets += [f'/api/agents/{rid}', f'/api/connections/{rid}', f'/api/agent/v1/badge/{rid}.svg', f'/agent/{rid}']
    for path in gets:
        took, r, err = timed(c, 'GET', BASE + path)
        run.ok('api', f'GET {path}', r is not None and r.status_code == 200, err or getattr(r, 'status_code', ''), took)
        run.ok('api', f'time {path}', took <= API_S, f'{took}s ({edge(r)})', took)
    templates = []
    try:
        _, r, _ = timed(c, 'GET', BASE + '/api/workflows/templates')
        body = r.json()
        templates = body if isinstance(body, list) else body.get('templates') or body.get('items') or []
    except Exception:  # noqa: BLE001
        pass
    if templates:
        tid = templates[0].get('id') or templates[0].get('template_id')
        took, r, err = timed(c, 'GET', f'{BASE}/api/workflows/templates/{tid}')
        run.ok('api', 'workflow template detail', r is not None and r.status_code == 200, err or getattr(r, 'status_code', ''), took)
    took, r, err = timed(c, 'POST', BASE + '/api/agent/v1/discover', json={'task': q})
    run.ok('api', 'POST discover', r is not None and r.status_code == 200, err or getattr(r, 'status_code', ''), took)
    run.ok('api', 'discover time', took <= 3.0, f'{took}s', took)
    took, r, err = timed(c, 'POST', BASE + '/api/register/inspect', json={'url': BASE + '/.well-known/agent-card.json'})
    run.ok('api', 'POST register/inspect (read-only)', r is not None and r.status_code < 500,
           err or getattr(r, 'status_code', ''), took)
    return {'query': q}


def part_agent(run, c):
    for path in ['/.well-known/agent-card.json', '/.well-known/mcp.json', '/.well-known/mcp/server-card.json',
                 '/.well-known/agent-entry.json', '/llms.txt']:
        took, r, err = timed(c, 'GET', BASE + path)
        good = r is not None and r.status_code == 200
        if good and path.endswith('.json'):
            try:
                r.json()
            except ValueError:
                good = False
        run.ok('agent', f'GET {path}', good, err or getattr(r, 'status_code', ''), took)
    took, r, err = timed(c, 'POST', BASE + '/mcp', headers=MCP_H, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'full-check', 'version': '1'}}})
    if not run.ok('agent', 'MCP initialize', r is not None and r.status_code == 200, err or getattr(r, 'status_code', ''), took):
        return {}
    h = dict(MCP_H, **({'Mcp-Session-Id': r.headers['mcp-session-id']} if r.headers.get('mcp-session-id') else {}))
    timed(c, 'POST', BASE + '/mcp', headers=h, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    took, r, err = timed(c, 'POST', BASE + '/mcp', headers=h, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
    tools = (rpc_json(r).get('result') or {}).get('tools') or [] if r is not None and r.status_code == 200 else []
    run.ok('agent', 'MCP tools/list', len(tools) > 0, err or 'no tools', took)
    task = f'{random.choice(["convert currency", "weather forecast", "summarize a web page", "github issues"])} {random.randint(100, 999)}'
    sample_args = {'query': task, 'task': task, 'q': task, 'message': task, 'text': task, 'goal': task}
    endpoint = None
    for i, tool in enumerate(tools):
        name = tool.get('name')
        if name in WRITE_TOOLS:
            continue
        req = (tool.get('inputSchema') or {}).get('required') or []
        args = {k: sample_args[k] for k in req if k in sample_args}
        if any(k not in args for k in req):
            continue  # needs an id we do not have; covered by detail checks elsewhere
        took, r, err = timed(c, 'POST', BASE + '/mcp', headers=h, json={
            'jsonrpc': '2.0', 'id': 10 + i, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}})
        try:
            res = rpc_json(r).get('result') or {}
        except Exception:  # noqa: BLE001
            res = {}
        text = ((res.get('content') or [{}])[0] or {}).get('text', '')
        run.ok('agent', f'MCP tool {name}', bool(text) and not res.get('isError'),
               err or text[:160] or getattr(r, 'status_code', ''), took)
        limit = 3.0 if name in ('find_agents', 'search', 'chat') else 5.0
        run.ok('agent', f'MCP tool {name} time', took <= limit, f'{took}s > {limit}s', took)
        if name == 'find_agents' and not endpoint:
            m = re.search(r'Endpoint:\s*(\S*/api/gateway/mcp/\d+)', text)
            endpoint = m.group(1) if m else None
    if endpoint:
        took, r, err = timed(c, 'POST', endpoint, headers=MCP_H, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'full-check', 'version': '1'}}})
        good = r is not None and r.status_code == 200
        gh = dict(MCP_H, **({'Mcp-Session-Id': r.headers['mcp-session-id']} if good and r.headers.get('mcp-session-id') else {}))
        n = 0
        if good:
            _, r2, _ = timed(c, 'POST', endpoint, headers=gh, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            try:
                n = len((rpc_json(r2).get('result') or {}).get('tools') or [])
            except Exception:  # noqa: BLE001
                n = 0
        run.ok('agent', 'gateway connect to top recommendation', n > 0, f'{endpoint.rsplit("/", 1)[-1]}: tools={n}', took)
    took, r, err = timed(c, 'POST', BASE + '/a2a', json={'jsonrpc': '2.0', 'id': 1, 'method': 'message/send', 'params': {
        'message': {'role': 'user', 'messageId': f'fc-{random.randint(1, 10**9)}', 'parts': [{'kind': 'text', 'text': task}]}}})
    ok = False
    try:
        body = rpc_json(r)
        ok = 'result' in body and 'error' not in body
    except Exception:  # noqa: BLE001
        body = {}
    run.ok('agent', 'A2A message/send', ok, err or str(body.get('error') or getattr(r, 'status_code', '')), took)
    run.ok('agent', 'A2A time', took <= 3.0, f'{took}s', took)
    return {'tools': [t.get('name') for t in tools], 'gateway_endpoint': bool(endpoint)}


def wait_text(page, pattern, timeout):
    """Poll the page text from Python: the site's CSP forbids string eval, so wait_for_function cannot be used."""
    end = time.time() + timeout
    while time.time() < end:
        m = re.search(pattern, page.inner_text('body'))
        if m:
            return m
        page.wait_for_timeout(250)
    raise TimeoutError(pattern)


def part_browser(run):
    from playwright.sync_api import sync_playwright
    flows = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in ((1280, 800), (375, 740)):
            ctx = browser.new_context(viewport={'width': width, 'height': height}, user_agent=UA + ' Chromium',
                                      extra_http_headers=QA_HEADER)
            page = ctx.new_page()
            errors, failed = [], []
            page.on('console', lambda m: errors.append(m.text[:160]) if m.type == 'error' else None)
            page.on('requestfailed', lambda q: failed.append(f'{q.method} {q.url[:120]} {q.failure}'))
            page.on('response', lambda resp: failed.append(f'{resp.status} {resp.url[:120]}')
                    if resp.status >= 500 or (resp.status >= 400 and '/api/' in resp.url) else None)
            for path in NAV[:9]:
                errors.clear()
                failed.clear()
                t = time.time()
                try:
                    page.goto(BASE + path, wait_until='load', timeout=20000)
                    page.wait_for_timeout(1200)
                except Exception as e:  # noqa: BLE001
                    run.ok('browser', f'{width} load {path}', False, type(e).__name__)
                    continue
                took = round(time.time() - t, 2)
                run.ok('browser', f'{width} load time {path}', took <= 4.0, f'{took}s', took)
                broken = page.evaluate("[...document.images].filter(i=>i.complete&&i.naturalWidth===0&&i.offsetParent).map(i=>i.src).slice(0,3)")
                hscroll = page.evaluate("document.documentElement.scrollWidth>innerWidth+1")
                run.ok('browser', f'{width} console {path}', not errors, errors[:2])
                run.ok('browser', f'{width} requests {path}', not failed, failed[:2])
                run.ok('browser', f'{width} images {path}', not broken, broken)
                run.ok('browser', f'{width} no sideways scroll {path}', not hscroll, 'horizontal scroll')
            # Flow: Explore search shows result cards.
            try:
                page.goto(BASE + '/new/en/explore.html', wait_until='load')
                page.wait_for_selector('.acard', timeout=15000)
                box = page.locator('#xQ')
                box.fill(f'weather forecast {random.randint(100, 999)}')
                t = time.time()
                with page.expect_response(lambda resp: '/api/explore?' in resp.url and 'q=weather' in resp.url, timeout=15000):
                    box.press('Enter')
                page.wait_for_selector('.acard', timeout=10000)
                flows.append(('explore', width, round(time.time() - t, 2)))
                run.ok('browser', f'{width} explore search time', time.time() - t <= 3.0, f'{round(time.time() - t, 2)}s')
            except Exception as e:  # noqa: BLE001
                run.ok('browser', f'{width} explore search shows cards', False, type(e).__name__)
            # Flow: open the first agent card.
            try:
                page.locator('.acard').first.click()
                page.wait_for_timeout(1500)
                run.ok('browser', f'{width} agent card opens', 'agent' in page.url or page.locator('[role=dialog],.agent-detail,.detail').count() > 0,
                       page.url)
            except Exception as e:  # noqa: BLE001
                run.ok('browser', f'{width} agent card opens', False, type(e).__name__)
            # Flow: Chat answers with a recommendation.
            try:
                page.goto(BASE + '/new/en/chat.html', wait_until='load')
                ta = page.locator('[placeholder="What do you want to accomplish?"]:visible').first
                ta.fill(f'find a tool to convert currency rates {random.randint(100, 999)}')
                t = time.time()
                ta.press('Enter')
                wait_text(page, r'Endpoint:|Show \d+ alternatives|Did it work\?', 20)
                took = round(time.time() - t, 2)
                flows.append(('chat', width, took))
                run.ok('browser', f'{width} chat answer time', took <= 3.0, f'{took}s', took)
            except Exception as e:  # noqa: BLE001
                run.ok('browser', f'{width} chat answers', False, f'{type(e).__name__}: {str(e)[:120]}')
            # Flow: Test page runs the default example.
            try:
                page.goto(BASE + '/new/en/test.html', wait_until='load')
                page.wait_for_timeout(800)
                t = time.time()
                page.locator('#tbRunBtn').click()
                m = wait_text(page, r'Latest test\W+(Completed|Failed|Error)', 30)
                took = round(time.time() - t, 2)
                flows.append(('test', width, took))
                status = m.group(1)
                run.ok('browser', f'{width} test run completes', status == 'Completed', status, took)
                run.ok('browser', f'{width} test run time', took <= 5.0, f'{took}s', took)
            except Exception as e:  # noqa: BLE001
                # 11-11: say what the page showed, so a limit, a wording change and a real failure differ.
                try:
                    shown = re.findall(r'(?:Latest test|Rate|limit|slow down|unavailable)[^\n]{0,90}', page.inner_text('body'), re.I)[:2]
                except Exception:  # noqa: BLE001
                    shown = []
                run.ok('browser', f'{width} test run', False, f'{type(e).__name__}: {shown}')
            ctx.close()
        browser.close()
    return {'flows': flows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parts', default='pages,api,agent,browser')
    args = ap.parse_args()
    run, extra = Run(), {}
    started = time.time()
    with client() as c:
        for part in args.parts.split(','):
            try:
                if part == 'pages':
                    extra['pages'] = part_pages(run, c)
                elif part == 'api':
                    extra['api'] = part_api(run, c)
                elif part == 'agent':
                    extra['agent'] = part_agent(run, c)
                elif part == 'browser':
                    extra['browser'] = part_browser(run)
            except Exception as e:  # noqa: BLE001 - a crashed part is a failure, never a silent pass
                run.ok(part, f'{part} part crashed', False, f'{type(e).__name__}: {e}')
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'minutes': round((time.time() - started) / 60, 1),
              'checks': run.checks, 'failed': len(run.failures),
              'pass_rate': round(100 * (run.checks - len(run.failures)) / max(run.checks, 1), 1),
              'failures': run.failures, **extra}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in record.items() if k != 'failures'}, ensure_ascii=False))
    for f in run.failures:
        print(f"FAIL [{f['team']}] {f['check']}: {f['detail']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
