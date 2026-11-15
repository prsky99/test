"""Read-only counts and lookups on the production database for team sessions (user decision 11-15:
"do not block it, let the teams check").

    .venv/bin/python -m scripts.prod_ro_sql deploy/ops/some-counts.sql
    .venv/bin/python -m scripts.prod_ro_sql -c "SELECT count(*) FROM ad_coin_v2.adc2_paid_bookings"

What keeps it read-only (each layer alone is not trusted):
  1. the text is checked before anything connects: every statement must start with SELECT, WITH, EXPLAIN or SHOW,
     and no statement may contain a writing or session-changing keyword, a psql backslash command, or a function
     that writes, sleeps, signals, reads server files or takes advisory locks;
  2. the session starts with default_transaction_read_only=on, a 5 s statement timeout and a 1 s lock timeout;
  3. everything runs inside one BEGIN READ ONLY ... ROLLBACK, after a first query that pins the snapshot (a
     transaction cannot be switched to read-write once a query has run).
One connection at a time, refused while the database already has 44 or more connections (max_connections 48).
At most 200 output lines are printed. Every run is appended to logs/ops/prod-ro-sql.jsonl (time, text hash,
statement count, lines, exit code). Names that look like secrets (password, secret, private_key, token, dsn,
credential) are refused: this tool is for counts and state, not for reading credentials or personal data.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PSQL = '/opt/homebrew/opt/postgresql@18/bin/psql'
HOST = str(ROOT / 'gateway-data/postgres18/run')
PORT = '55432'
DATABASE = 'agentcon_cutover_20261020_191757'
LOG = ROOT / 'logs/ops/prod-ro-sql.jsonl'
MAX_LINES = 200
MAX_TEXT = 20000
BUSY = 44
OPTIONS = '-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=10000'

STARTS = ('select', 'with', 'explain', 'show')
WORDS = ('insert', 'update', 'delete', 'merge', 'drop', 'alter', 'create', 'truncate', 'grant', 'revoke', 'copy',
         'call', 'do', 'set', 'reset', 'begin', 'start', 'commit', 'rollback', 'savepoint', 'release', 'lock',
         'vacuum', 'analyze', 'analyse', 'reindex', 'cluster', 'refresh', 'notify', 'listen', 'unlisten',
         'prepare', 'execute', 'deallocate', 'discard', 'into', 'comment', 'import', 'security', 'checkpoint',
         'load', 'share', 'nowait', 'declare', 'fetch', 'move', 'close')
FUNCTIONS = (r'set_config', r'pg_sleep\w*', r'pg_terminate_backend', r'pg_cancel_backend', r'pg_reload_conf',
             r'pg_rotate_logfile', r'pg_read_\w+', r'pg_ls_\w+', r'pg_stat_file', r'lo_\w+', r'dblink\w*',
             r'pg_advisory\w*', r'pg_try_advisory\w*', r'nextval', r'setval', r'pg_switch_wal', r'pg_create_\w+',
             r'pg_drop_\w+', r'pg_logical_\w+', r'pg_replication_\w+', r'pg_notify', r'query_to_xml\w*',
             r'table_to_xml\w*', r'database_to_xml\w*', r'schema_to_xml\w*', r'cursor_to_xml\w*',
             r'pg_export_snapshot', r'pg_promote', r'pg_backup_\w+', r'pg_file_\w+', r'pg_wal_\w+',
             r'txid_current', r'pg_current_xact_id', r'pg_stat_reset\w*', r'pg_import_\w+')
SECRET = re.compile(r'passw|secret|private_?key|token|credential|\bdsn\b|api_?key', re.I)


class Refused(ValueError):
    pass


def _blank(text):
    """TEXT without comments, with every string literal and quoted identifier replaced by spaces of the same
    length, so keywords are looked for only in the SQL itself. Raises on an unterminated quote or comment."""
    out, i, n = [], 0, len(text)
    while i < n:
        two = text[i:i + 2]
        ch = text[i]
        if two == '--':
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif two == '/*':
            j = text.find('*/', i + 2)
            if j < 0:
                raise Refused('unterminated comment')
            out.append(' ' * (j + 2 - i))
            i = j + 2
        elif ch in ('\'', '"'):
            j = i + 1
            while True:
                j = text.find(ch, j)
                if j < 0:
                    raise Refused('unterminated quote')
                if text[j:j + 2] == ch * 2:
                    j += 2
                    continue
                break
            out.append(ch + ' ' * (j - i - 1) + ch)
            i = j + 1
        elif ch == '$':
            tag = re.match(r'\$[A-Za-z_]*\$', text[i:])
            if not tag:
                raise Refused('a $ outside a string is not accepted')
            j = text.find(tag.group(0), i + len(tag.group(0)))
            if j < 0:
                raise Refused('unterminated dollar quote')
            out.append(' ' * (j + len(tag.group(0)) - i))
            i = j + len(tag.group(0))
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def statements(text):
    """The statements of TEXT (each as written), after checking every one. Raises Refused with the reason."""
    if len(text) > MAX_TEXT:
        raise Refused(f'text longer than {MAX_TEXT} characters')
    if '\\' in text:
        raise Refused('backslash (psql commands, escapes) is not accepted')
    if '\x00' in text:
        raise Refused('NUL byte')
    blank = _blank(text)
    found, start = [], 0
    for end in [m.start() for m in re.finditer(';', blank)] + [len(blank)]:
        raw, bare = text[start:end].strip(), blank[start:end].strip().lower()
        start = end + 1
        if not bare:
            continue
        first = re.match(r'[a-z]+', bare)
        if not first or first.group(0) not in STARTS:
            raise Refused(f'a statement must start with {", ".join(STARTS).upper()}: {raw[:60]!r}')
        for word in WORDS:
            if re.search(rf'\b{word}\b', bare):
                raise Refused(f'keyword {word.upper()} is not accepted: {raw[:60]!r}')
        for name in FUNCTIONS:
            if re.search(rf'\b{name}\s*\(', bare):
                raise Refused(f'function {name} is not accepted: {raw[:60]!r}')
        if SECRET.search(raw):
            raise Refused(f'a name that looks like a secret is not accepted: {raw[:60]!r}')
        found.append(raw)
    if not found:
        raise Refused('no statement')
    return found


def _psql(script, timeout):
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': os.environ.get('HOME', ''),
           'LANG': 'C', 'PGOPTIONS': OPTIONS, 'PGAPPNAME': 'prod_ro_sql', 'PGCONNECT_TIMEOUT': '5'}
    return subprocess.run([PSQL, '-X', '-q', '-At', '-F', '|', '-P', 'pager=off', '-v', 'ON_ERROR_STOP=1',
                           '-h', HOST, '-p', PORT, '-d', DATABASE, '-f', '-'],
                          input=script, capture_output=True, text=True, timeout=timeout, env=env)


def run(text, out=sys.stdout, err=sys.stderr, psql=_psql, log=LOG):
    """Check TEXT, run it read-only, print at most MAX_LINES lines. Returns the exit code."""
    record = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'sha256': hashlib.sha256(text.encode()).hexdigest(),
              'ppid': os.getppid()}
    try:
        parts = statements(text)
        record['statements'] = len(parts)
        busy = psql('SELECT count(*) FROM pg_stat_activity;', 10)
        if busy.returncode != 0:
            raise Refused('cannot connect: ' + busy.stderr.strip()[:200])
        if int(busy.stdout.strip() or 0) >= BUSY:
            record['code'] = 75
            print(f'refused: the database has {busy.stdout.strip()} connections (limit {BUSY}); try again later', file=err)
            return 75
        result = psql('BEGIN READ ONLY;\nSELECT 1 WHERE false;\n' + ';\n'.join(parts) + ';\nROLLBACK;\n',
                      10 + 6 * len(parts))
        lines = result.stdout.splitlines()
        for line in lines[:MAX_LINES]:
            print(line, file=out)
        if len(lines) > MAX_LINES:
            print(f'... {len(lines) - MAX_LINES} more lines not shown (limit {MAX_LINES}); aggregate instead', file=out)
        if result.returncode != 0:
            print(result.stderr.strip()[:500], file=err)
        record.update(code=result.returncode, lines=len(lines))
        return result.returncode
    except Refused as exc:
        record.update(code=2, refused=str(exc)[:200])
        print(f'refused: {exc}', file=err)
        return 2
    except subprocess.TimeoutExpired:
        record['code'] = 124
        print('timed out', file=err)
        return 124
    finally:
        try:
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with open(log, 'a') as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        except OSError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('file', nargs='?', help='a .sql file inside the project')
    parser.add_argument('-c', dest='text', help='the SQL text itself')
    args = parser.parse_args(argv)
    if bool(args.file) == bool(args.text):
        parser.error('give a file or -c "SQL", not both')
    if args.file:
        path = Path(args.file).resolve()
        if ROOT not in path.parents or path.suffix != '.sql':
            parser.error('the file must be a .sql file inside the project')
        text = path.read_text()
    else:
        text = args.text
    raise SystemExit(run(text))


if __name__ == '__main__':
    main()
