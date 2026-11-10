#!/usr/bin/env python3
"""Relabel restored reports whose test_method says transport but whose stored wire shows a real call (11-10).

The second Opus re-score found legacy reports labelled 'A2A Agent Card' or 'MCP Tools List' although input_wire
holds a tools/call, a JSON-RPC task method or tool arguments. fix_transport_grades.py had downgraded them as
transport-only. This script, for each such report:
- sets test_method to 'MCP Tool Call' or 'A2A Message' (from the wire);
- restores evidence_scope, eval_grade, eval_score, content_md and summary from the backup taken before
  fix_transport_grades.py ran (the nightly remediation then re-applies the Grade A gate and C1~C17);
- backs up the current values first.

    fix_mislabeled_methods.py            dry run
    fix_mislabeled_methods.py --apply
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from remediate_all_test_reports import connect  # noqa: E402
from report_consistency import executed_method  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / 'logs/ops/report-quality/backup-transport-grades-20261110-124529.jsonl'


def main(apply):
    old = {}
    if BEFORE.is_file():
        for line in BEFORE.read_text().splitlines():
            row = json.loads(line)
            old[row['id']] = row
    conn = connect()
    cur = conn.cursor()
    cur.execute("select id, test_method, input_wire, evidence_scope, eval_grade, eval_score, content_md, summary "
                "from agent_test_reports where lower(test_method) in ('a2a agent card', 'mcp tools list')")
    updates, backup = [], []
    for rid, method, input_wire, scope, grade, score, md, summary in cur.fetchall():
        new_method = executed_method({'test_method': method, 'input_wire': input_wire})
        if not new_method:
            continue
        prev = old.get(rid, {})
        backup.append({'id': rid, 'test_method': method, 'evidence_scope': scope, 'eval_grade': grade,
                       'eval_score': score, 'content_md': md, 'summary': summary})
        updates.append((new_method, prev.get('evidence_scope') or 'legacy', prev.get('eval_grade') or grade,
                        prev.get('eval_score') if prev.get('eval_score') is not None else score,
                        prev.get('content_md') or md, prev.get('summary') or summary, time.time(), rid))
    print(json.dumps({'relabelled': len(updates), 'restored_from_backup': sum(1 for b in backup if b['id'] in old)}))
    if apply and updates:
        out = ROOT / 'logs/ops/report-quality' / f'backup-mislabeled-{datetime.now():%Y%m%d-%H%M%S}.jsonl'
        out.write_text(''.join(json.dumps(b, ensure_ascii=False, default=str) + '\n' for b in backup))
        cur.executemany('update agent_test_reports set test_method=%s, evidence_scope=%s, eval_grade=%s, eval_score=%s, '
                        'content_md=%s, summary=%s, updated_at=%s where id=%s', updates)
        conn.commit()
        print(f'backup: {out.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main('--apply' in sys.argv))
