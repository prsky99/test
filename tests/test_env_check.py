"""A candidate agentcon.env is read by every role's own settings reader before it is put in place (PM 11-14)."""
import json
import os

from scripts import env_check

READER = '''import sys
args = sys.argv[1:]
env = args[args.index('--env-file') + 1]
allowed = {ALLOWED}
for n, line in enumerate(open(env), 1):
    line = line.strip()
    if line and not line.startswith('#') and line.split('=', 1)[0] not in allowed:
        print('Configuration check failed: Line %d: unsupported setting name.' % n, file=sys.stderr); sys.exit(1)
print('SECRET_TOKEN=do-not-show')
'''


def release(root, name, allowed):
    folder = root / name / 'scripts'
    folder.mkdir(parents=True)
    (folder / 'agentcon_config.py').write_text(READER.replace('{ALLOWED}', repr(set(allowed))))


def test_every_role_reads_the_candidate_and_secrets_never_reach_the_report(tmp_path, capsys):
    root = tmp_path / 'releases'
    release(root, 'old-r1', {'HOST', 'SECRET_TOKEN'})
    release(root, 'new-r2', {'HOST', 'SECRET_TOKEN', 'NEW_SWITCH'})
    env = tmp_path / 'agentcon.env'
    env.write_text('HOST=0.0.0.0\nSECRET_TOKEN=do-not-show\nNEW_SWITCH=1\n')
    os.chmod(env, 0o600)
    roles = {'frontend': 'new-r2', 'admin': 'new-r2', 'jobs': 'new-r2', 'execution': 'old-r1'}
    results = env_check.check(env, roles, root=root)
    assert [r for r, v in results.items() if not v['ok']] == ['execution']          # one old role is enough to refuse
    assert 'Line 3: unsupported setting name' in results['execution']['error']
    assert 'do-not-show' not in json.dumps(results)
    env.write_text('HOST=0.0.0.0\nSECRET_TOKEN=do-not-show\n')
    assert all(v['ok'] for v in env_check.check(env, roles, root=root).values())
    missing = env_check.check(env, {'jobs': 'gone-r9'}, root=root)
    assert missing['jobs']['ok'] is False


def test_active_releases_reads_slots_and_single_releases(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'services': {
        'frontend': {'active': 'b', 'slots': {'a': 'f-r1', 'b': 'f-r2'}}, 'admin': {'active': 'a', 'slots': {'a': 'a-r1'}},
        'jobs': {'release': 'j-r1'}, 'execution': {'release': 'e-r1'}}}))
    assert env_check.active_releases(state) == {'frontend': 'f-r2', 'admin': 'a-r1', 'jobs': 'j-r1', 'execution': 'e-r1'}
