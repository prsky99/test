"""PostgreSQL 18.7 rehearsal without touching Homebrew links (운영·SRE, PM 11-15 12:46).

    .venv/bin/python -m scripts.heavy_slot --team 운영·SRE --what "pg 18.7 rehearsal" --minutes 15 -- \
        .venv/bin/python deploy/ops/pg187_rehearsal.py --root <scratch dir>

What it does, all under --root (the real /opt/homebrew and the production cluster are never touched):
1. Pours the downloaded 18.7 bottles (postgresql@18, openssl@4, lz4, krb5; `brew fetch` cache) into <root>/hb/Cellar,
   rewrites their @@HOMEBREW_PREFIX@@ load commands to <root>/hb and signs them again (ad hoc), and builds
   <root>/hb/lib|share/postgresql@18 the way the formula's symlink_tree does, plus the installed pgvector 0.8.2 files.
   PostgreSQL finds pkglibdir relative to its own executable (bindir and pkglibdir share /opt/homebrew/ at build
   time), so <root>/hb/Cellar/postgresql@18/18.7/bin/postgres loads modules from <root>/hb/lib/postgresql@18.
2. "new": a fresh 18.7 cluster (C locale, socket only, pg_stat_statements preloaded like production): loads plpgsql,
   vector 0.8.2 (with an HNSW index), unaccent and pg_stat_statements, installs the application schema with the
   application's own store, opens it again with full validation (the five public triggers and their bodies) and
   counts the triggers.
3. "mixed": the 18.6_1 server binary (a copy, so its pkglibdir resolves under <root>/hb186) started with 18.6 links;
   while it runs, lib and share are relinked to 18.7 - the state of a running 18.6 server between `brew upgrade` and
   its restart. It runs a
   plpgsql trigger, unaccent and pg_stat_statements there and reports whether each loads.
Prints one JSON line per step and writes <root>/result.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BREW = '/opt/homebrew'
FORMULAE = ('postgresql@18', 'openssl@4', 'lz4', 'krb5')
SHARED_OPT = ('gettext', 'icu4c@79', 'readline', 'zstd')         # not upgraded: link to the installed ones
PGVECTOR = Path(BREW, 'Cellar/pgvector/0.8.2')
OLD = Path(BREW, 'Cellar/postgresql@18/18.6_1')
PORT = 55491
KEY = b'r' * 32


def say(step, **fields):
    line = {'step': step, **fields}
    print(json.dumps(line, ensure_ascii=False), flush=True)
    return line


def run(cmd, env=None, check=True, timeout=300):
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    if check and done.returncode:
        raise RuntimeError(f"{Path(cmd[0]).name} failed ({done.returncode}): {(done.stderr or done.stdout)[-400:]}")
    return done


def bottle(name):
    path = run(['/opt/homebrew/bin/brew', '--cache', name], env={**os.environ, 'HOMEBREW_NO_AUTO_UPDATE': '1'}).stdout.strip()
    if not Path(path).is_file():
        raise RuntimeError(f'bottle not downloaded: {name} (run brew fetch first)')
    return Path(path)


def macho(path):
    return path.is_file() and not path.is_symlink() and run(['/usr/bin/file', '-b', str(path)], check=False).stdout.startswith('Mach-O')


def pour(hb):
    cellar = hb / 'Cellar'
    cellar.mkdir(parents=True, exist_ok=True)
    kegs = {}
    for name in FORMULAE:
        with tarfile.open(bottle(name)) as tar:
            tar.extractall(cellar, filter='tar')
        version = sorted(p.name for p in (cellar / name).iterdir())[-1]
        kegs[name] = cellar / name / version
    (hb / 'opt').mkdir(exist_ok=True)
    for name, keg in kegs.items():
        link(hb / 'opt' / name, os.path.relpath(keg, hb / 'opt'))
    for name in SHARED_OPT:
        link(hb / 'opt' / name, f'{BREW}/opt/{name}')
    fixed = 0
    for keg in kegs.values():
        for path in keg.rglob('*'):
            if not macho(path):
                continue
            listing = run(['/usr/bin/otool', '-L', str(path)]).stdout.splitlines()[1:]
            args = []
            for row in listing:
                old = row.strip().split(' (')[0]
                if old.startswith('@@HOMEBREW_PREFIX@@') or old.startswith('@@HOMEBREW_CELLAR@@'):
                    new = old.replace('@@HOMEBREW_PREFIX@@', str(hb)).replace('@@HOMEBREW_CELLAR@@', str(cellar))
                    args += ['-change', old, new]
            ident = run(['/usr/bin/otool', '-D', str(path)]).stdout.splitlines()[1:]
            if ident and '@@HOMEBREW' in ident[0]:
                args += ['-id', ident[0].replace('@@HOMEBREW_PREFIX@@', str(hb)).replace('@@HOMEBREW_CELLAR@@', str(cellar))]
            if args:
                os.chmod(path, path.stat().st_mode | 0o200)
                run(['/usr/bin/install_name_tool', *args, str(path)])
                run(['/usr/bin/codesign', '--force', '-s', '-', str(path)])
                fixed += 1
    return kegs, fixed


def link(path, target):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        path.unlink()
    os.symlink(target, path)


def symlink_tree(hb, keg, with_vector=True):
    """lib/postgresql -> lib/postgresql@18, share/postgresql -> share/postgresql@18, like the formula; plus pgvector."""
    count = 0
    for top in ('lib', 'share'):
        source = keg / top / 'postgresql'
        for path in source.rglob('*'):
            if path.is_dir():
                continue
            dest = hb / top / 'postgresql@18' / path.relative_to(source)
            link(dest, os.path.relpath(path, dest.parent))
            count += 1
    if with_vector:
        for path in PGVECTOR.rglob('*'):
            if path.is_file() and 'postgresql@18' in path.parts:
                top = path.relative_to(PGVECTOR).parts[0]
                rest = path.relative_to(PGVECTOR / top / 'postgresql@18')
                if top in ('lib', 'share'):
                    dest = hb / top / 'postgresql@18' / rest
                    link(dest, str(path))
                    count += 1
    return count


class Cluster:
    def __init__(self, bindir, data, socket, log):
        self.bin, self.data, self.socket, self.log = Path(bindir), Path(data), Path(socket), Path(log)
        self.env = {'PATH': f'{bindir}:/usr/bin:/bin', 'LC_ALL': 'en_US.UTF-8', 'LANG': 'en_US.UTF-8', 'HOME': os.environ.get('HOME', '/tmp')}

    def initdb(self):
        run([str(self.bin / 'initdb'), '-D', str(self.data), '--username=postgres', '--auth-local=trust',
             '--auth-host=reject', '--no-locale', '--encoding=UTF8'], self.env)

    def start(self):
        self.socket.mkdir(mode=0o700, exist_ok=True)
        run([str(self.bin / 'pg_ctl'), '-D', str(self.data), '-l', str(self.log), '-w', '-t', '60', '-o',
             f"-k {self.socket} -p {PORT} -c listen_addresses='' -c unix_socket_permissions=0700 "
             "-c shared_preload_libraries=pg_stat_statements", 'start'], self.env)

    def stop(self):
        if (self.data / 'postmaster.pid').exists():
            for mode in ('fast', 'immediate'):
                run([str(self.bin / 'pg_ctl'), '-D', str(self.data), '-m', mode, '-w', '-t', '30', 'stop'], self.env, check=False)
                if not (self.data / 'postmaster.pid').exists():
                    break

    def sql(self, text, check=True):
        done = run([str(self.bin / 'psql'), '-h', str(self.socket), '-p', str(PORT), '-U', 'postgres', '-d', 'postgres',
                    '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', text], self.env, check=check)
        return done.stdout.strip() if done.returncode == 0 else 'ERROR: ' + (done.stderr.strip().splitlines() or ['?'])[-1]


EXTENSIONS = ("CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS unaccent; "
              "CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
PROBES = {
    'version': "SELECT version()",
    'pkglibdir': "SELECT setting FROM pg_config() WHERE name='PKGLIBDIR'",
    'extensions': "SELECT string_agg(extname||' '||extversion, ', ' ORDER BY extname) FROM pg_extension",
    'plpgsql': "DO $$BEGIN PERFORM 1; END$$; SELECT 'ok'",
    'trigger': ("CREATE TABLE IF NOT EXISTS probe_t(x int); CREATE OR REPLACE FUNCTION probe_f() RETURNS trigger "
                "LANGUAGE plpgsql AS $$BEGIN NEW.x := NEW.x + 1; RETURN NEW; END$$; "
                "DROP TRIGGER IF EXISTS probe_tg ON probe_t; CREATE TRIGGER probe_tg BEFORE INSERT ON probe_t "
                "FOR EACH ROW EXECUTE FUNCTION probe_f(); INSERT INTO probe_t VALUES (1) RETURNING x"),
    'unaccent': "SELECT unaccent('Crème Brûlée')",
    'pg_stat_statements': "SELECT count(*) >= 0 FROM pg_stat_statements",
}
VECTOR = ("CREATE TABLE IF NOT EXISTS probe_v(id int, e vector(3)); TRUNCATE probe_v; "
          "INSERT INTO probe_v SELECT i, ARRAY[i, i*2, i*3]::real[]::vector FROM generate_series(1, 200) i; "
          "CREATE INDEX IF NOT EXISTS probe_v_hnsw ON probe_v USING hnsw (e vector_l2_ops); "
          "SET enable_seqscan = off; SELECT id FROM probe_v ORDER BY e <-> '[10,20,30]' LIMIT 1")


def app_check(socket):
    """The application's own store: install the schema, then open with full validation (triggers and bodies)."""
    code = f'''
import json, psycopg
from agent_market.storage_adapter import open_store
def connect(): return psycopg.connect(host={str(socket)!r}, port={PORT}, dbname="postgres", user="postgres", autocommit=True)
store = open_store("postgresql", connection=connect(), initialize=True, workflow_key={KEY!r})
store.close()
store = open_store("postgresql", connection=connect(), workflow_key={KEY!r}, required_capabilities=("full_application",))
with store.tx(readonly=True):
    n = store._execute("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace s ON s.oid=c.relnamespace WHERE s.nspname=current_schema() AND NOT t.tgisinternal").fetchone()[0]
store.close()
print(json.dumps({{"opened_with_validation": True, "public_triggers": n}}))
'''
    env = {k: v for k, v in os.environ.items() if not k.startswith(('APPLICATION_', 'PG', 'AGENTCON'))}
    done = subprocess.run([str(ROOT / '.venv/bin/python'), '-I', '-c', code], cwd=ROOT, env={**env, 'PYTHONPATH': str(ROOT)},
                          capture_output=True, text=True, timeout=300)
    if done.returncode:
        return {'opened_with_validation': False, 'error': (done.stderr.strip().splitlines() or ['?'])[-1][:300]}
    return json.loads(done.stdout.strip().splitlines()[-1])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--keep', action='store_true', help='leave the scratch clusters in place')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if str(root).startswith(BREW) or (root / 'hb').resolve() == Path(BREW):
        raise SystemExit('refusing: --root must be a scratch folder, not the Homebrew prefix')
    results, started = {}, time.time()
    hb = root / 'hb'
    if hb.exists():
        shutil.rmtree(hb)
    kegs, fixed = pour(hb)
    new_keg = kegs['postgresql@18']
    links = symlink_tree(hb, new_keg)
    results['pour'] = say('pour', kegs={k: v.name for k, v in kegs.items()}, relocated_files=fixed, links=links)
    pg_config = run([str(new_keg / 'bin/pg_config'), '--version', '--pkglibdir', '--sharedir']).stdout.split('\n')
    results['paths'] = say('paths', pg_config=pg_config[:3], expected_pkglibdir=str(hb / 'lib/postgresql@18'))

    # 2) 18.7 alone
    new = Cluster(new_keg / 'bin', root / 'data187', root / 's187', root / 'server187.log')
    try:
        if new.data.exists():
            shutil.rmtree(new.data)
        new.initdb()
        new.start()
        new.sql(EXTENSIONS)
        probes = {name: new.sql(text, check=False) for name, text in PROBES.items()}
        probes['vector_hnsw'] = new.sql(VECTOR, check=False)
        probes['app'] = app_check(new.socket)
        results['new'] = say('new', **probes)
    finally:
        new.stop()

    # 3) a running 18.6 server whose lib/share links already point at 18.7 (between brew upgrade and restart)
    hb186 = root / 'hb186'
    if hb186.exists():
        shutil.rmtree(hb186)
    old_keg = hb186 / 'Cellar/postgresql@18/18.6_1'
    shutil.copytree(OLD, old_keg, symlinks=True)
    symlink_tree(hb186, new_keg)
    old_lib = run([str(old_keg / 'bin/pg_config'), '--pkglibdir']).stdout.strip()
    mixed = Cluster(old_keg / 'bin', root / 'data186', root / 's186', root / 'server186.log')
    try:
        if mixed.data.exists():
            shutil.rmtree(mixed.data)
        # initdb with the 18.6 tools against the 18.6 share files (the cluster existed before the upgrade) ...
        symlink_tree(hb186, old_keg, with_vector=False)
        mixed.initdb()
        mixed.start()
        mixed.sql("CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        # ... then brew upgrade relinks lib and share to 18.7 while the 18.6 server keeps running. The postmaster
        # keeps the 18.6 pg_stat_statements it preloaded; every new connection (psql below) loads plpgsql and
        # unaccent afresh from the relinked folder, exactly as after a real brew upgrade.
        symlink_tree(hb186, new_keg, with_vector=False)
        probes = {name: mixed.sql(text, check=False) for name, text in PROBES.items() if name != 'extensions'}
        results['mixed'] = say('mixed', pkglibdir_of_18_6_binary=old_lib, **probes)
    finally:
        mixed.stop()
    results['seconds'] = round(time.time() - started, 1)
    (root / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    if not args.keep:
        for name in ('data187', 'data186', 'hb186'):
            shutil.rmtree(root / name, ignore_errors=True)
    ok_new = (results['new'].get('app', {}).get('public_triggers') == 5 and
              all(not str(v).startswith('ERROR') for k, v in results['new'].items() if k != 'app'))
    say('summary', new_ok=ok_new, mixed_errors=[k for k, v in results['mixed'].items() if str(v).startswith('ERROR')],
        seconds=results['seconds'])
    return 0 if ok_new else 1


if __name__ == '__main__':
    sys.exit(main())
