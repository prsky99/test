#!/usr/bin/env python3
"""Submit verified report drafts through the official admin API using the caller's own admin session.

The session token is read from the ADMIN_SESSION_TOKEN environment variable (never from a file, never
printed). Each draft is linted, checked for an existing report, then POSTed; the stored report is read back.

  export ADMIN_SESSION_TOKEN='<personal admin session token>'   # from your logged-in admin session
  python3 scripts/submit_report_drafts.py [drafts_dir] [--dry-run]
"""
from pathlib import Path
import glob, json, os, sys, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from report_pipeline_common import lint

BASE = os.environ.get('REPORT_API_BASE', 'http://127.0.0.1:8200')
DEFAULT_DIR = str(Path.home() / '.gemini/antigravity/brain/c483b1b9-b552-4e83-b78d-d6f36bf0128d/scratch/drafts')


def call(token, method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': 'Bearer ' + token, 'X-Dashboard': '1',
                                          'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b'{}')
        except Exception: return e.code, {}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry-run' in sys.argv
    folder = args[0] if args else DEFAULT_DIR
    token = os.environ.get('ADMIN_SESSION_TOKEN', '').strip()
    if not dry and not token:
        raise SystemExit('Set ADMIN_SESSION_TOKEN to your own admin session token first (or use --dry-run).')
    if token and (not token.isascii() or any(c in token for c in '<> \t') or len(token) < 16):
        raise SystemExit('ADMIN_SESSION_TOKEN does not look like a real session token (placeholder text, spaces or too short). '
                         'Paste the actual token value, not the example text.')
    allowed_kinds = tuple(k.strip() for k in os.environ.get('REPORT_KINDS', 'a2a,mcp').split(',') if k.strip())
    ok = skipped = failed = 0
    for path in sorted(glob.glob(os.path.join(folder, '*.json'))):
        name = os.path.basename(path)
        report = json.load(open(path))
        if report.get('kind') not in allowed_kinds:
            print(f"{name}: skipped (kind={report.get('kind')} excluded)"); skipped += 1; continue
        problems = lint(report)
        if report.get('is_success') in (True, 1) and report.get('evidence_scope') not in ('execution','contract'):
            problems.append('Successful publication requires recorded execution evidence; a connection-only probe is not task execution.')
        if problems:
            print(f'{name}: REJECTED locally {problems}'); failed += 1; continue
        if dry:
            print(f'{name}: lint clean (dry run)'); continue
        code, data = call(token, 'GET', f"/admin/api/test-reports/existing?resource_id={report['resource_id']}")
        if code == 200 and data.get('exists'):
            print(f"{name}: already reported (#{data.get('existing_report_id')}), skipped"); skipped += 1; continue
        if code != 200: print(f'{name}: pre-check unavailable (HTTP {code}); the service will re-check duplicates on create')
        for attempt in range(3):
            code, data = call(token, 'POST', '/admin/api/test-reports', report)
            if code == 200 and data.get('ok'):
                break
            time.sleep(1)
        if code != 200 or not data.get('ok'):
            print(f"{name}: not created (HTTP {code}, {data.get('error_code') or data.get('detail') or 'error'})"); failed += 1; continue
        stored = call(token, 'GET', f"/admin/api/test-reports/{data['id']}")[1].get('report', {})
        back = lint(stored) if stored else ['read-back failed']
        print(f"{name}: created #{data['id']}" + ('' if not back else f' WARNING read-back: {back}')); ok += 1
    print(f'created={ok} skipped={skipped} failed={failed}')
    if failed > 0:
        sys.exit(1)
    return 0


if __name__ == '__main__':
    main()
