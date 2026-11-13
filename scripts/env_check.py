"""Check a candidate gateway-data/agentcon.env with the settings reader of every role's running release, before it is
put in place (PM 11-14; the 11-10 07:42 AD_COIN_V2 and 11-14 04:34 WORKFLOW_RETENTION_SCHEDULE incidents).

    cp -p gateway-data/agentcon.env /tmp/x/agentcon.env.new   # edit the copy (mode 600, owned by you)
    .venv/bin/python -m scripts.env_check --env /tmp/x/agentcon.env.new     # exit 0 only if all four roles read it
    # then replace gateway-data/agentcon.env with the copy

Each role's own scripts/agentcon_config.py (from gateway-data/services/releases/<release>/) parses the file with
--export in a separate process; its standard output (the settings, secrets included) is discarded and never shown.
Only the exit status and the reader's error line are reported. --deep also runs --check (the startup validation).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'gateway-data/services/state.json'
RELEASES = ROOT / 'gateway-data/services/releases'
ROLES = ('frontend', 'admin', 'jobs', 'execution')


def active_releases(state=STATE):
    services = json.loads(Path(state).read_text())['services']
    found = {}
    for role in ROLES:
        entry = services.get(role) or {}
        found[role] = entry['slots'][entry['active']] if 'slots' in entry else entry.get('release')
    return found


def check(env, releases, root=RELEASES, deep=False, timeout=60):
    env = str(Path(env).resolve())
    results = {}
    for role, release in releases.items():
        folder = Path(root) / str(release)
        python = folder / '.venv/bin/python'
        reader = folder / 'scripts/agentcon_config.py'
        if not release or not reader.is_file():
            results[role] = {'release': release, 'ok': False, 'error': 'release or its settings reader is missing'}
            continue
        modes = ['--export'] + (['--check'] if deep else [])
        outcome = {'release': release, 'ok': True}
        for mode in modes:
            run = subprocess.run([str(python if python.exists() else sys.executable), str(reader), mode, '--env-file', env],
                                 cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout)
            if run.returncode != 0:
                outcome = {'release': release, 'ok': False, 'mode': mode,
                           'error': (run.stderr.strip().splitlines() or ['(no message)'])[-1][:300]}
                break
        results[role] = outcome
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--env', required=True, help='candidate settings file (a copy, mode 600)')
    parser.add_argument('--releases', default='active', help="'active' (default) or role=release,... pairs")
    parser.add_argument('--deep', action='store_true', help='also run the startup check of each role')
    args = parser.parse_args(argv)
    releases = active_releases() if args.releases == 'active' else dict(p.split('=', 1) for p in args.releases.split(','))
    results = check(args.env, releases, deep=args.deep)
    ok = all(r['ok'] for r in results.values())
    print(json.dumps({'ok': ok, 'env': str(args.env), 'roles': results}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
