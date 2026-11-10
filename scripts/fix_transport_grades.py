#!/usr/bin/env python3
"""Apply the AQEF-30 Grade A gate to stored test reports whose probe was transport-only (11-10 audit).

An Agent Card fetch, an MCP tools/list handshake or an unpaid x402 402 challenge is transport evidence,
never execution evidence, so such a report cannot hold Grade A (AQEF-30 section 3.1). The 11-10 Opus audit
found 213 of 300 re-scored reports graded A on transport-only probes; the cause was the generator labelling
every probe as 'execution' and using an A threshold of 88 (fixed in report_pipeline_common.py).

For every report with a transport-only test_method this script:
- sets evidence_scope to 'transport';
- re-applies the grade gate (A -> B, score capped at 89.4);
- rewrites the grade and score mentions in content_md and summary, and when the body mentioned a grade
  or score, adds one short correction note at the top;
- adds '### Pros' / '### Cons' sections built from the stored pros/cons arrays when the body has none
  (lint R4), and normalises '## Pros' / '## Cons' headings to '### '.
No numbers are invented: the new score is the stored score capped at 89.4.

    fix_transport_grades.py            dry run: counts only
    fix_transport_grades.py --apply    back up the affected rows to logs/ops/report-quality/ then update
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from remediate_all_test_reports import connect  # noqa: E402
from report_pipeline_common import TRANSPORT_ONLY_METHODS, _aqef_grade_gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOTE = ('> [!NOTE]\n> **AQEF-30 grade correction (2026-11-10)**: Grade **B** | AQEF-30 Score: **{score:.1f}/100**. '
        'This probe checked transport only ({method}); AQEF-30 Grade A requires verified live execution evidence. '
        'Any earlier grade or score in this report is superseded.\n\n')
METHOD_LABEL = {'a2a agent card': 'an A2A Agent Card fetch', 'mcp tools list': 'an MCP tools/list handshake',
                'x402 challenge': 'an unpaid x402 402 challenge'}
SCORE = r'\d{1,3}(?:\.\d+)?'


def rewrite_text(text, old_score, new_score):
    """Replace grade-A and old-score mentions that describe this report's own result."""
    if not text:
        return text
    new = f'{new_score:.1f}'
    out = text
    # Grade mentions that state this report's grade (not rule sentences like "Grade A requires").
    out = re.sub(r'((?:Recorded|Canonical|Reported|Stored|Evaluation)?\s*Grade(?:\*\*)?:?\s*\**)A(\**\s*(?:\||\(|,|\)|\.|$))',
                 r'\1B\2', out, flags=re.M)
    out = re.sub(r'(\*\*(?:Recorded|Evaluation) Grade\*\*:?\s*\|?\s*`?(?:Grade )?)A\b', r'\1B', out)
    out = re.sub(r'(, (?:recorded )?Grade )A\)', r'\1B)', out)
    out = re.sub(r'\(Grade A\)', '(Grade B)', out)
    if old_score is not None and abs(old_score - new_score) > 0.05:
        # Longest spelling first; the number must not continue (99 must not match inside 99.0).
        for o in sorted({f'{old_score:.1f}', f'{old_score:g}'}, key=len, reverse=True):
            esc = re.escape(o) + r'(?![\d]|\.\d)'
            out = re.sub(rf'((?:AQEF-30 |Recorded |Stored )?Score:?\s*\**){esc}(\s*/\s*100|\**|\))', rf'\g<1>{new}\2', out)
            out = re.sub(rf'(\|\s*AQEF-30 Score\s*\|\s*){esc}/100', rf'\g<1>{new}/100', out)
            out = re.sub(rf'\({esc}/100\)', f'({new}/100)', out)
            out = re.sub(rf'\({esc} / 100\)', f'({new} / 100)', out)
            out = re.sub(rf'score {esc}\b', f'score {new}', out)
    return out


def fix_pros_cons(md, pros, cons):
    md = re.sub(r'^## (Pros|Cons)\s*$', r'### \1', md, flags=re.M)
    added = False
    if '### Pros' not in md or '### Cons' not in md:
        def items(value):
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                value = [value]
            return [str(v).strip() for v in (value or []) if str(v).strip()]
        parts = []
        if '### Pros' not in md and items(pros):
            parts.append('### Pros\n' + '\n'.join(f'- {v}' for v in items(pros)))
        if '### Cons' not in md and items(cons):
            parts.append('### Cons\n' + '\n'.join(f'- {v}' for v in items(cons)))
        if parts:
            md = md.rstrip() + '\n\n' + '\n\n'.join(parts) + '\n'
            added = True
    return md, added


def main(apply):
    conn = connect()
    cur = conn.cursor()
    cur.execute("select id, lower(test_method), evidence_scope, eval_grade, eval_score, latency_ms, content_md, summary, "
                "pros, cons from agent_test_reports where lower(test_method) = any(%s) or content_md !~ '### Pros' "
                "or content_md !~ '### Cons'", (sorted(TRANSPORT_ONLY_METHODS),))
    rows = cur.fetchall()
    changes, backup, counts = [], [], {'scope': 0, 'grade_a_to_b': 0, 'note': 0, 'pros_cons': 0}
    for rid, method, scope, grade, score, latency, md, summary, pros, cons in rows:
        md0, summary0 = md or '', summary or ''
        new_scope, new_grade, new_score = scope, grade, score
        new_md, new_summary = md0, summary0
        if method in TRANSPORT_ONLY_METHODS:
            new_scope = 'transport'
            old = float(score) if score is not None else None
            gated_score, new_grade = _aqef_grade_gate(old if old is not None else 0.0, grade, 'transport', latency)
            if grade == 'A':
                new_score = gated_score
                counts['grade_a_to_b'] += 1
                new_md = rewrite_text(md0, old, new_score)
                new_summary = rewrite_text(summary0, old, new_score)
                if re.search(r'Grade|Score', md0):
                    new_md = NOTE.format(score=new_score, method=METHOD_LABEL[method]) + new_md
                    counts['note'] += 1
            if new_scope != scope:
                counts['scope'] += 1
        new_md, added = fix_pros_cons(new_md, pros, cons)
        counts['pros_cons'] += added
        if (new_scope, new_grade, new_score, new_md, new_summary) != (scope, grade, score, md0, summary0):
            changes.append((new_scope, new_grade, new_score, new_md, new_summary, time.time(), rid))
            backup.append({'id': rid, 'evidence_scope': scope, 'eval_grade': grade, 'eval_score': score,
                           'content_md': md, 'summary': summary})
    print(json.dumps({'rows_scanned': len(rows), 'rows_to_update': len(changes), **counts}))
    if not apply:
        return 0
    out = ROOT / 'logs/ops/report-quality' / f'backup-transport-grades-{datetime.now():%Y%m%d-%H%M%S}.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w') as fh:
        for row in backup:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    for start in range(0, len(changes), 500):
        cur.executemany('update agent_test_reports set evidence_scope=%s, eval_grade=%s, eval_score=%s, content_md=%s, '
                        'summary=%s, updated_at=%s where id=%s', changes[start:start + 500])
        conn.commit()
    print(f'backup: {out.relative_to(ROOT)}  updated: {len(changes)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main('--apply' in sys.argv))
