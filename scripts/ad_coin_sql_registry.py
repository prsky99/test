"""Rebuild agent_market/ad_coin/sql_registry.json from what AI AD Coin product code runs.

Runs the AI AD Coin tests and the rehearsal smoke stage in record mode, keeps the
statements issued by product code (never a test's own SQL) and writes the sorted
shapes with their sha256. Review the diff before committing it.

    .venv-tests/bin/python -m scripts.ad_coin_sql_registry --write
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def collect():
    from agent_market.ad_coin.sql_registry import RECORD_ENV
    with tempfile.TemporaryDirectory() as tmp:
        record = os.path.join(tmp, 'record.jsonl')
        env = {**os.environ, RECORD_ENV: record}
        tests = sorted(glob.glob(str(ROOT / 'tests/test_ad_coin*.py')))
        for command in ([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *tests],
                        [sys.executable, '-m', 'scripts.ad_coin_rehearsal', '--stage', 'smoke', '--out', tmp]):
            done = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True)
            if done.returncode:
                raise SystemExit('Recording run failed: ' + ' '.join(command[2:4]) + '\n' + done.stdout[-2000:])
        lines = Path(record).read_text().splitlines() if Path(record).exists() else []
    return sorted({json.loads(line) for line in lines})


def static_statements():
    """SQL written as constants in AI AD Coin product code, so paths no test reaches are registered too."""
    import ast
    import re
    from agent_market.ad_coin.sql_registry import shape
    start = re.compile(r'^\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\b', re.I)

    def text(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = text(node.left), text(node.right)
            return None if left is None or right is None else left + right
        return None
    found = set()
    from agent_market.ad_coin.v2.sql import all_statements
    found.update(shape(value) for value in all_statements())
    skip = {'db.py', 'sql_registry.py', 'page.py', 'admin_page.py', 'advertiser_page.py'}
    for path in sorted((ROOT / 'agent_market/ad_coin').glob('*.py')):
        if path.name in skip:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            value = text(node) if isinstance(node, (ast.Constant, ast.BinOp)) else None
            if value and start.match(value) and 'ad_coin_' in value:
                found.add(shape(value))
    return found


def main(argv=None):
    from agent_market.ad_coin.sql_registry import PATH, digest
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--add-v2', action='store_true',
                        help='Synchronize the closed v2 SQL catalog while preserving legacy statements')
    args = parser.parse_args(argv)
    before = json.loads(PATH.read_text())['statements'] if PATH.exists() else []
    old = {item['sql'] for item in before}
    if args.add_v2:
        from agent_market.ad_coin.sql_registry import shape
        from agent_market.ad_coin.v2.sql import all_statements
        shapes = sorted({sql for sql in old if 'adc2_' not in sql} |
                        {shape(sql) for sql in all_statements()})
    else:
        shapes = sorted(set(collect()) | static_statements())
    data = {'profile': 'ai-ad-coin-sql-v1', 'statements': [{'sql': s, 'sha256': digest(s)} for s in shapes]}
    print('statements', len(shapes), 'added', len(set(shapes) - old), 'removed', len(old - set(shapes)))
    if args.write:
        PATH.write_text(json.dumps(data, indent=1, ensure_ascii=True) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
