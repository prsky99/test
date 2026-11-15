"""deploy/ops/pg187-restore-links.sh on a fake Homebrew prefix (운영·SRE 11-15): the real /opt/homebrew is never touched."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'deploy/ops/pg187-restore-links.sh'
FILES = ['lib/postgresql/plpgsql.dylib', 'lib/postgresql/unaccent.dylib', 'share/postgresql/extension/unaccent.control',
         'include/postgresql/server/pg_config.h', 'bin/psql', 'bin/postgres']


def keg(prefix, version, extra=()):
    base = prefix / 'Cellar/postgresql@18' / version
    for name in FILES + list(extra):
        (base / name).parent.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(version)
    (base / 'bin/postgres').chmod(0o755)
    return base


def link(prefix, path, target):
    p = prefix / path
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_symlink():
        p.unlink()
    os.symlink(target, p)


def layout(prefix, version):
    """What brew's symlink_tree makes: lib/share/include/postgresql@18, bin/*-18 and opt/postgresql@18."""
    link(prefix, 'opt/postgresql@18', f'../Cellar/postgresql@18/{version}')
    for name in FILES:
        top, _, rest = name.partition('/')
        if top == 'bin':
            link(prefix, f'bin/{rest}-18', f'../Cellar/postgresql@18/{version}/{name}')
        else:
            sub = rest.partition('/')[2]
            depth = '../' * (sub.count('/') + 2)
            link(prefix, f'{top}/postgresql@18/{sub}', f'{depth}Cellar/postgresql@18/{version}/{name}')


def setup(tmp_path):
    prefix = tmp_path / 'hb'
    keg(prefix, '18.6_1')
    layout(prefix, '18.6_1')
    link(prefix, 'lib/postgresql@18/vector.dylib', '../../Cellar/pgvector/0.8.2/lib/postgresql@18/vector.dylib')
    rows = []
    for d in ('opt', 'bin', 'lib', 'share', 'include'):
        for p in sorted((prefix / d).rglob('*')):
            if p.is_symlink() and 'postgresql@18/18.6_1' in os.readlink(p):
                rows.append(f"/opt/homebrew{str(p)[len(str(prefix)):]}\t{os.readlink(p)}")
    record = tmp_path / 'links.tsv'
    record.write_text('\n'.join(rows) + '\n')
    keg(prefix, '18.7', extra=['lib/postgresql/new_in_187.dylib'])     # what brew upgrade pours
    layout(prefix, '18.7')
    link(prefix, 'lib/postgresql@18/new_in_187.dylib', '../../Cellar/postgresql@18/18.7/lib/postgresql/new_in_187.dylib')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), 'LANG': 'ko_KR.UTF-8', 'LC_ALL': 'ko_KR.UTF-8',
           'PG_PREFIX': str(prefix), 'PG_LINKS': str(record), 'PG_RUNNING': 'true'}
    return prefix, record, env


def run(env, *args, **extra):
    return subprocess.run(['/bin/bash', str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True)


def test_restores_every_recorded_link_and_drops_the_new_one(tmp_path):
    prefix, record, env = setup(tmp_path)
    r = run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    for row in record.read_text().splitlines():
        path, target = row.split('\t')
        assert os.readlink(prefix / path[len('/opt/homebrew/'):]) == target
    assert not (prefix / 'lib/postgresql@18/new_in_187.dylib').exists()
    assert os.readlink(prefix / 'lib/postgresql@18/vector.dylib').startswith('../../Cellar/pgvector/0.8.2')
    assert '18.7에만 있는 링크: 1개' in r.stdout and '모두 기록과 같음' in r.stdout
    again = run(env)
    assert again.returncode == 0 and '되돌릴 링크: 0개' in again.stdout


def test_dry_run_changes_nothing(tmp_path):
    prefix, _, env = setup(tmp_path)
    before = os.readlink(prefix / 'opt/postgresql@18')
    r = run(env, '--dry-run')
    assert r.returncode == 0 and '지울 것(18.7에만 있음)' in r.stdout and '미리 보기 끝' in r.stdout
    assert os.readlink(prefix / 'opt/postgresql@18') == before == '../Cellar/postgresql@18/18.7'
    assert (prefix / 'lib/postgresql@18/new_in_187.dylib').is_symlink()


def test_refuses_while_a_server_is_running(tmp_path):
    prefix, _, env = setup(tmp_path)
    r = run(env, PG_RUNNING='echo 1350 /opt/homebrew/opt/postgresql@18/bin/postgres -D data')
    assert r.returncode == 3 and '아직 돌고 있습니다' in r.stdout
    assert os.readlink(prefix / 'opt/postgresql@18') == '../Cellar/postgresql@18/18.7'


def test_refuses_when_the_old_keg_was_cleaned_up(tmp_path):
    prefix, _, env = setup(tmp_path)
    (prefix / 'Cellar/postgresql@18/18.6_1/bin/postgres').unlink()
    r = run(env)
    assert r.returncode == 1 and '18.6_1 가 없습니다' in r.stdout
