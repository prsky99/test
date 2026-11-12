"""Public check around a frontend deploy, in one command (PM 11-11 22시: 08시 묶음 확인 순서).

    # before the deploy (07:30-07:50): numbers only, no warming
    .venv/bin/python -m scripts.heavy_slot --team 성장·유통 --what "배포 전 기준값" --minutes 8 -- \
        .venv-tests/bin/python -m scripts.post_deploy_check before
    # right after the deploy: warm_edge once, then the same numbers, the screen check and the comparison
    .venv/bin/python -m scripts.heavy_slot --team 성장·유통 --what "배포 뒤 공개 확인" --minutes 10 -- \
        .venv-tests/bin/python -m scripts.post_deploy_check after

Numbers (public address, a new connection per request, nothing excluded): for each of the five pages, the bytes
on the wire with gzip, and three full downloads with cf-cache-status and the cf-ray airport. The first download
of each page is the first-visit number. "after" runs warm_edge first, so its later downloads show the warmed edge;
both are reported.

Screen check ("after", also run "before" for the old version): each page at 1280 and 375 px in Chromium. It must
load with no console error, leave no inactive panel template unfilled, and move to another panel through the main
navigation. Results go to logs/ops/post-deploy-check/<date>-<before|after>[-<label>]-<HHMM>.json, one file per run; "after" prints the comparison and
exits 1 when the screen check fails (then ask 검색과 RAG to roll the frontend back, PM 조건 ②).
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://agentconcierge.biz'
PAGES = ('/', '/new/en/explore.html', '/new/en/chat.html', '/new/en/test.html', '/new/en/list-agent.html')
WIDTHS = (1280, 375)
RUNS = 3
QA = {'X-Agentcon-QA': 'post_deploy_check'}
UA = 'agentcon-post-deploy-check/1 (site owner QA; contact@agentconcierge.biz)'
OUT = ROOT / 'logs/ops/post-deploy-check'
# The panel to open from each page through the main navigation, and the panel that must then be visible.
MOVE = {'/': 'learn', '/new/en/explore.html': 'learn', '/new/en/chat.html': 'learn', '/new/en/test.html': 'learn',
        '/new/en/list-agent.html': 'explore'}


def download(path):
    """One full download on a new connection: seconds, wire bytes (gzip), cache state, airport, status."""
    headers = {'Accept': 'text/html,application/xhtml+xml', 'Accept-Encoding': 'gzip', 'User-Agent': UA, **QA}
    start = time.monotonic()
    try:
        with httpx.Client(timeout=30, headers=headers) as client:
            with client.stream('GET', BASE + path) as r:
                wire = sum(len(chunk) for chunk in r.iter_raw())
                ray = r.headers.get('cf-ray', '')
                return {'s': round(time.monotonic() - start, 2), 'status': r.status_code, 'wire_bytes': wire,
                        'encoding': r.headers.get('content-encoding'), 'cache': r.headers.get('cf-cache-status'),
                        'colo': ray.rsplit('-', 1)[-1] if '-' in ray else None}
    except httpx.HTTPError as exc:
        return {'s': round(time.monotonic() - start, 2), 'status': type(exc).__name__}


def numbers():
    rows = {}
    for path in PAGES:
        rows[path] = [download(path) for _ in range(RUNS)]
    return rows


SCREEN = """() => ({
  templates: document.querySelectorAll('template[data-inactive-panel]').length,
  panels: document.querySelectorAll('[data-panel]').length,
  visible: [...document.querySelectorAll('[data-panel]')].filter(el => el.getClientRects().length).map(el => el.dataset.panel)
})"""


def screens():
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in WIDTHS:
            for path in PAGES:
                context = browser.new_context(viewport={'width': width, 'height': 900}, extra_http_headers=QA)
                page = context.new_page()
                errors, asked = [], []
                page.on('console', lambda m: m.type == 'error' and errors.append(m.text[:200]))
                page.on('pageerror', lambda e: errors.append(str(e)[:200]))
                page.on('request', lambda r: asked.append(r.url))
                row = {'path': path, 'width': width, 'problems': []}
                try:
                    page.goto(BASE + path, wait_until='load', timeout=30000)
                    page.wait_for_timeout(800)
                    state = page.evaluate(SCREEN)
                    row.update(panels=state['panels'], visible=state['visible'],
                               panels_js=any('/new/en/assets/panels.js' in u for u in asked))
                    if state['templates']:
                        row['problems'].append('inactive panel template left in the page')
                    if state['panels'] < 9:
                        row['problems'].append('only %d panels' % state['panels'])
                    target = MOVE[path]
                    selector = 'a[data-tab="%s"]:visible, a[href$="/%s.html"]:visible' % (target, target)
                    link = page.locator(selector).first
                    menu = page.locator('button[data-pearl-action="menu"]:visible').first
                    if not link.count() and menu.count():  # phones: the main navigation sits behind the menu button
                        menu.click()
                        page.wait_for_timeout(400)
                        link = page.locator(selector).first
                    if link.count():
                        link.click()
                        page.wait_for_timeout(600)
                        moved = page.evaluate(SCREEN)['visible']
                        row['moved_to'] = moved
                        if target not in moved and not page.url.endswith(target + '.html'):
                            row['problems'].append('navigation to %s did not show it' % target)
                    else:
                        row['problems'].append('no visible link to %s, even behind the menu' % target)
                except Exception as exc:  # noqa: BLE001 - a page that does not load is the finding
                    row['problems'].append('load: %s' % type(exc).__name__)
                finally:
                    context.close()
                if errors:
                    row['problems'].append('console: ' + errors[0])
                row['console_errors'] = len(errors)
                results.append(row)
        browser.close()
    return results


def summary(rows):
    out = {}
    for path, samples in rows.items():
        ok = [s for s in samples if isinstance(s.get('status'), int)]
        out[path] = {'first_s': samples[0]['s'], 'median_s': statistics.median(s['s'] for s in samples),
                     'wire_kb': round(ok[0]['wire_bytes'] / 1024, 1) if ok else None,
                     'caches': [s.get('cache') for s in samples], 'colos': sorted({s.get('colo') for s in samples} - {None}),
                     'within_1s': sum(1 for s in samples if s['s'] <= 1.0), 'runs': len(samples)}
    return out


def compare(before, after):
    lines = ['화면 | 압축 KB 전→후 | 첫 요청 초 전→후 | 중앙값 초 전→후 | 캐시 전 / 후 | 1초 안 전→후']
    for path in PAGES:
        b, a = before['summary'].get(path, {}), after['summary'].get(path, {})
        lines.append('%s | %s→%s | %s→%s | %s→%s | %s / %s | %s→%s' % (
            path, b.get('wire_kb'), a.get('wire_kb'), b.get('first_s'), a.get('first_s'), b.get('median_s'),
            a.get('median_s'), ','.join(map(str, b.get('caches', []))), ','.join(map(str, a.get('caches', []))),
            b.get('within_1s'), a.get('within_1s')))
    return '\n'.join(lines)


def result_path(day, stage, label=''):
    """One file per run, never overwritten (PM 11-12: after results must stay comparable across deploys):
    <day>-<stage>[-<label>]-<HHMM>.json, with -2, -3 ... if a run in the same minute already wrote one."""
    stem = '-'.join(x for x in (day, stage, label, datetime.now().strftime('%H%M')) if x)
    path, n = OUT / (stem + '.json'), 2
    while path.exists():
        path, n = OUT / ('%s-%d.json' % (stem, n)), n + 1
    return path


def latest_before(day):
    found = sorted(OUT.glob('%s-before*.json' % day), key=lambda f: f.stat().st_mtime)
    return found[-1] if found else None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('before', 'after'))
    parser.add_argument('--no-screens', action='store_true', help='numbers only')
    parser.add_argument('--label', default='', help='the release, e.g. noon (goes into the file name)')
    args = parser.parse_args(argv)
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'stage': args.stage}
    if args.stage == 'after':
        from scripts import warm_edge
        try:
            warm_edge.main([])  # its own flags, not this command line
        except SystemExit as done:
            record['warm_edge_exit'] = done.code
    record['numbers'] = numbers()
    record['summary'] = summary(record['numbers'])
    if not args.no_screens:
        record['screens'] = screens()
        record['screen_problems'] = [r for r in record['screens'] if r['problems']]
    OUT.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime('%Y-%m-%d')
    path = result_path(day, args.stage, args.label)
    record['label'] = args.label
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print('결과: %s' % path)
    print(json.dumps(record['summary'], ensure_ascii=False, indent=1))
    if not args.no_screens:
        print('화면 확인: %d개 중 문제 %d개' % (len(record['screens']), len(record['screen_problems'])))
        for row in record['screen_problems']:
            print(' -', row['path'], row['width'], '; '.join(row['problems']))
    if args.stage == 'after':
        before_path = latest_before(day)
        if before_path:
            print('비교 기준: %s' % before_path.name)
            print(compare(json.loads(before_path.read_text()), record))
        else:
            print('배포 전 기준값 파일 없음: %s-before*.json' % day)
        if record.get('screen_problems'):
            print('화면 확인 실패: 검색과 RAG에 frontend 되돌리기 요청(PM 조건 ②)')
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
