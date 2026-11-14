"""Shell scripts handed to the user must not run a variable into non-ASCII text (PM 11-14, two incidents).

macOS bash 3.2 in a UTF-8 locale (the user's terminal, ko_KR.UTF-8) reads the first byte of a multibyte character as
part of the variable name, so "$n건" or "$PREV인지" is an unbound variable under `set -u` and the script stops
(11-13 Worker deploy, 11-14 availability fix). The same holds for "$x·" and any other non-ASCII character.
Write "${n}건". This test fails on any `$name` followed directly by a non-ASCII character and runs `bash -n` on
every shell script in the repository.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_INTO = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]')
SHEBANG = re.compile(rb'#!\s*/\S*/(ba|z)?sh\b|#!\s*/usr/bin/env\s+(ba|z)?sh\b')


def shell_scripts():
    files = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split('\n')
    for name in files:
        path = ROOT / name
        if not name or not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        if name.endswith(('.sh', '.bash')) or SHEBANG.match(path.open('rb').read(64)):
            yield path


def test_no_variable_runs_into_non_ascii_text():
    bad = [f'{p.relative_to(ROOT)}:{i}: {m.group(0)}' for p in shell_scripts()
           for i, line in enumerate(p.read_text(errors='replace').splitlines(), 1) for m in RUN_INTO.finditer(line)]
    assert not bad, 'brace these variables, e.g. ${n}건:\n' + '\n'.join(bad)


def test_every_shell_script_parses():
    broken = []
    for path in shell_scripts():
        if path.read_bytes().startswith(b'#!/bin/zsh') or path.suffix == '.zsh':
            continue
        result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
        if result.returncode:
            broken.append(f'{path.relative_to(ROOT)}: {result.stderr.strip()[:200]}')
    assert not broken, '\n'.join(broken)


def test_the_pattern_catches_the_two_incidents():
    assert RUN_INTO.search('echo "대상: $n건"') and RUN_INTO.search('[ "$current" = "$PREV" ] || echo "$PREV인지"')
    assert RUN_INTO.search('echo "$x·y"') and not RUN_INTO.search('echo "${n}건 $1건 $? 건"')
