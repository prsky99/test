#!/usr/bin/env python3
"""Deterministic consistency rules for published test reports (11-10, quality target 100%).

The 11-10 Opus 5.5 audit of 300 rewritten reports (median 88/100) found that most remaining issues are
mechanical, so plain code can find and fix them without any model call:

  C1 sections_match_fields   the ### Pros / ### Cons lists and the workflow section in content_md must say
                             exactly what the pros, cons and workflow_recommendation fields say (the fields win)
  C2 score_matches_field     every "AQEF-30 Score: X/100" in prose must equal eval_score and name the grade
  C3 transport_scope_stated  a transport-only report must say that grade and score reflect transport evidence
                             only and that no tool, skill or task was invoked
  C4 exact_latency_present   the unrounded latency_ms must appear at least once (prose rounds it)
  C5 empty_description_noted a card description that only repeats the agent name is stated as such and
                             listed in cons
  C6 neutral_not_pro         "declared as unsupported" items are limitations, not advantages: they move to cons
  C7 single_trial_telemetry  output_wire telemetry from one trial carries no p95 or jitter value
  C8 restored_record_noted   a legacy (restored) report says it is a historical record
  C9 lists_are_json          pros and cons are JSON arrays of strings

normalize(report) returns (new_report, applied_rule_ids); check(report) returns the rules still violated.
No numbers are invented: every value written comes from the report's own fields.
"""
import json
import re

TRANSPORT_ONLY_METHODS = {'a2a agent card', 'mcp tools list', 'x402 challenge'}
SCOPE_SENTENCE = ('The grade and score reflect transport-level evidence only; no tool, skill or task was invoked.')
RESTORED_NOTE = ('> Historical record restored from a retained backup. Recorded outcomes and grades are not a new '
                 'execution and not a guarantee of current availability.\n\n')
EMPTY_DESCRIPTION = 'Provider description: not provided beyond the agent name.'
EMPTY_DESCRIPTION_CON = 'The card description only repeats the agent name, so it gives no functional detail.'
NEUTRAL_PRO = re.compile(r'(?i)\b(declared as unsupported|declared as false|are not supported|is not supported)\b')
SCORE_PROSE = re.compile(r'(AQEF-30 Score:\s*\**)(\d{1,3}(?:\.\d+)?)(\s*/\s*100\**)')
SINGLE_TRIAL_NOTE = 'single trial; p95 and jitter not measurable'


def as_list(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or '').strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return [part.strip().rstrip('.') + '.' for part in text.split(';') if part.strip().rstrip('.')]
    if isinstance(parsed, list):
        return [str(v).strip() for v in parsed if str(v).strip()]
    return [str(parsed).strip()] if str(parsed).strip() else []


def is_transport(report):
    return str(report.get('test_method') or '').strip().lower() in TRANSPORT_ONLY_METHODS


def _section_span(md, heading):
    """(start_of_body, end_of_body) for a heading line, or None. The body ends at the next heading."""
    match = re.search(rf'(?m)^{re.escape(heading)}[ \t\r]*\n', md)
    if not match:
        return None
    nxt = re.search(r'(?m)^#{1,6} ', md[match.end():])
    end = match.end() + nxt.start() if nxt else len(md)
    return match.end(), end


def _replace_body(md, heading, body):
    span = _section_span(md, heading)
    if not span:
        return md
    start, end = span
    tail = md[end:]
    return md[:start] + '\n' + body.strip() + '\n' + ('\n' if tail else '') + tail


def _bullets(items):
    return '\n'.join(f'- {item}' for item in items)


def _score_text(score):
    return f'{float(score):.1f}'


def _fmt_ms(value):
    return f'{float(value):.1f}'.rstrip('0').rstrip('.')


def _needs_exact_latency(report, md):
    latency = report.get('latency_ms')
    if latency is None:
        return False
    try:
        latency = float(latency)
    except (TypeError, ValueError):
        return False
    if latency < 0 or abs(latency - round(latency)) < 0.05:
        return False  # whole numbers are already exact when shown
    return f'{_fmt_ms(latency)} ms' not in md


def _telemetry(report):
    try:
        wire = json.loads(report.get('output_wire') or '')
    except (TypeError, ValueError):
        return None, None
    if not isinstance(wire, dict) or not isinstance(wire.get('telemetry'), dict):
        return wire, None
    return wire, wire['telemetry']


def _agent_name_only_description(report, md):
    name = str(report.get('agent_name') or '').strip()
    if not name:
        return None
    match = re.search(rf'(?m)^(.*?)Provider description:\s*{re.escape(name)}\.?[ \t]*$', md)
    return match


def check(report):
    md = str(report.get('content_md') or '')
    problems = []
    pros, cons = as_list(report.get('pros')), as_list(report.get('cons'))
    for heading, items in (('### Pros', pros), ('### Cons', cons)):
        span = _section_span(md, heading)
        if span and items and md[span[0]:span[1]].strip() != _bullets(items):
            problems.append('C1')
            break
    else:
        workflow = str(report.get('workflow_recommendation') or '').strip()
        span = _section_span(md, '## Recommended Workflow Integration')
        if span and workflow and md[span[0]:span[1]].strip() != workflow:
            problems.append('C1')
    score = report.get('eval_score')
    if score is not None:
        for line in md.splitlines():
            if line.lstrip().startswith('|'):
                continue
            for match in SCORE_PROSE.finditer(line):
                if abs(float(match.group(2)) - float(score)) > 0.05 or 'Grade' not in line:
                    problems.append('C2')
                    break
            if 'C2' in problems:
                break
    if is_transport(report) and SCOPE_SENTENCE not in md:
        problems.append('C3')
    if _needs_exact_latency(report, md):
        problems.append('C4')
    if _agent_name_only_description(report, md) or (
            EMPTY_DESCRIPTION.lower() in md.lower() and not any('description' in c.lower() for c in cons)):
        problems.append('C5')
    if any(NEUTRAL_PRO.search(p) for p in pros) and len(pros) > 1:
        problems.append('C6')
    _, tele = _telemetry(report)
    if tele and tele.get('trials') == 1 and (tele.get('p95_ms') is not None or tele.get('jitter_ms') is not None):
        problems.append('C7')
    if report.get('evidence_scope') == 'legacy' and not re.search(r'(?i)restored|historical', md):
        problems.append('C8')
    for key in ('pros', 'cons'):
        value = report.get(key)
        if value and not isinstance(value, list):
            try:
                if not isinstance(json.loads(value), list):
                    problems.append('C9')
            except ValueError:
                problems.append('C9')
    problems += extra_check(report, md, pros)
    if report.get('input_wire') is not None and executed_method(report):
        problems.append('C18')  # fixed by scripts/fix_mislabeled_methods.py, not by normalize()
    return sorted(set(problems))


def normalize(report):
    """Return (new_report, applied rule ids). The input dict is not changed."""
    r = dict(report)
    md = re.sub(r'(?m)^#{3,6} Recommended Workflow Integration[ \t\r]*$', '## Recommended Workflow Integration',
                str(r.get('content_md') or ''))
    applied = set(check(r))
    pros, cons = as_list(r.get('pros')), as_list(r.get('cons'))

    # C6: neutral "not supported" declarations are limitations.
    neutral = [p for p in pros if NEUTRAL_PRO.search(p)]
    if neutral and len(pros) > len(neutral):
        pros = [p for p in pros if p not in neutral]
        cons = cons + [n for n in neutral if n not in cons]
    # C5: description that only repeats the agent name.
    match = _agent_name_only_description(r, md)
    if match:
        md = md[:match.start()] + match.group(1) + EMPTY_DESCRIPTION + md[match.end():]
    if EMPTY_DESCRIPTION.lower() in md.lower() and not any('description' in c.lower() for c in cons):
        cons = cons + [EMPTY_DESCRIPTION_CON]
    md, pros, cons = extra_fix(r, md, pros, cons)
    r['pros'], r['cons'] = json.dumps(pros, ensure_ascii=False), json.dumps(cons, ensure_ascii=False)

    # C1: sections follow the fields.
    if pros:
        md = _replace_body(md, '### Pros', _bullets(pros))
    if cons:
        md = _replace_body(md, '### Cons', _bullets(cons))
    workflow = str(r.get('workflow_recommendation') or '').strip()
    if workflow:
        md = _replace_body(md, '## Recommended Workflow Integration', workflow)

    # C2: prose score equals the field and names the grade.
    score, grade = r.get('eval_score'), r.get('eval_grade')
    if score is not None:
        lines = md.split('\n')
        for idx, line in enumerate(lines):
            if line.lstrip().startswith('|') or 'AQEF-30 Score' not in line:
                continue
            line = SCORE_PROSE.sub(lambda m: m.group(1) + _score_text(score) + m.group(3), line)
            if grade and 'Grade' not in line:
                line = SCORE_PROSE.sub(lambda m: m.group(0) + f', Grade {grade}', line, count=1)
            lines[idx] = line
        md = '\n'.join(lines)

    # C3: transport scope sentence in the Scope section (or a new Scope section).
    if is_transport(r) and SCOPE_SENTENCE not in md:
        heading = '## Scope' if _section_span(md, '## Scope') else '### Scope'
        span = _section_span(md, heading)
        if span:
            body = md[span[0]:span[1]].strip()
            md = _replace_body(md, heading, (body + ' ' if body else '') + SCOPE_SENTENCE)
        elif '## Recommended Workflow Integration' in md:
            md = md.replace('## Recommended Workflow Integration',
                            f'## Scope\n\n{SCOPE_SENTENCE}\n\n## Recommended Workflow Integration', 1)
        else:
            md = md.rstrip() + f'\n\n## Scope\n\n{SCOPE_SENTENCE}\n'

    # C4: unrounded latency once, in the Measured Facts table when there is one.
    if _needs_exact_latency(r, md):
        row = f'| Recorded latency (unrounded) | {_fmt_ms(r["latency_ms"])} ms |'
        table = re.search(r'(?ms)^## Measured Facts[ \t]*\n\s*(\|[^\n]*\|\n)(\|[^\n]*\|\n)(?:\|[^\n]*\|\n)*', md + '\n')
        if table and table.end() <= len(md) + 1:
            end = min(table.end(), len(md))
            md = md[:end].rstrip('\n') + '\n' + row + '\n' + md[end:]
        else:
            # Never append after the last section: that would change the workflow section (C1).
            sentence = f'Recorded latency (unrounded): {_fmt_ms(r["latency_ms"])} ms.\n\n'
            anchor = re.search(r'(?m)^(?:#{1,3} .*Pros|### Pros|## Scope|## Recommended Workflow Integration)', md)
            md = md[:anchor.start()] + sentence + md[anchor.start():] if anchor else md.rstrip() + '\n\n' + sentence

    # C7: one-trial telemetry has no p95 or jitter.
    wire, tele = _telemetry(r)
    if tele and tele.get('trials') == 1 and (tele.get('p95_ms') is not None or tele.get('jitter_ms') is not None):
        tele['p95_ms'], tele['jitter_ms'], tele['note'] = None, None, SINGLE_TRIAL_NOTE
        r['output_wire'] = json.dumps(wire, ensure_ascii=False)

    # C8: restored record note.
    if r.get('evidence_scope') == 'legacy' and not re.search(r'(?i)restored|historical', md):
        md = RESTORED_NOTE + md

    # C14: provenance row, computed last so the hash covers the final stored capture.
    md = re.sub(r'(?m)^\| Evidence \| Probe executed [^\n]*\n', '', md)
    row = _evidence_row(r)
    if row:
        md = _add_row(md, row)
    r['content_md'] = md
    remaining = set(check(r))
    return r, sorted(applied - remaining)


# --- C10~C16: added after the 11-10 13:00 Opus re-score of 100 new reports (median 84) ---------------------
import hashlib  # noqa: E402

CORRECTION_MARK = 'AQEF-30 grade correction'
SCHEMA_CLAUSE = re.compile(r"(?<!')(?<!\d)(\d+) with input schemas\b(?! \(counted)(?!')(?!\))")
SCHEMA_NOTE = ' (counted from the live tools/list response; the stored capture keeps names and descriptions only)'
FLAT_LATENCY_ROW = re.compile(r'(?m)^\|([^|\n]*?)\s*\(p50 / p95 / jitter\)([^|\n]*)\|\s*(\d+(?:\.\d+)?) ms / \3 ms / ±0 ms[^|\n]*\|[ \t]*$')
FLAT_LATENCY_PROSE = re.compile(r' ?\(p95: (\d+(?:\.\d+)?) ms, jitter: ±0 ms\)')
PY_BOOL = re.compile(r'\| (False|True) \|')
SCORE_SLASH = re.compile(r'(?<![\d.])(\d{1,3}(?:\.\d+)?)(\s*/\s*100)\b')
OLD_GRADE_A = re.compile(r'(?i)((?:recorded|reported|stored|canonical) grade(?:\*\*)?:?\s*\**\s*\(?|grade is |grade \*\*|grade: \**)A\b(?! requires)')
# C17: the MCP "total" covers two calls, the step statistics cover three requests (with the notification), and
# with three samples the "p95" is the slowest one.
STEP_SENTENCE = re.compile(r'in (\d+(?:\.\d+)?) ms total \(step p50: (\d+(?:\.\d+)?) ms, p95: (\d+(?:\.\d+)?) ms(?:, jitter: ±(\d+(?:\.\d+)?) ms)?(?:[;,]? (?:over )?\d+ trials)?\)')
STEP_ROW = re.compile(r'(?m)^\| Step latency \(p50 / p95 / jitter\) \| (\d+(?:\.\d+)?) ms / (\d+(?:\.\d+)?) ms / ±(\d+(?:\.\d+)?) ms \((\d+) RPC steps\) \|')
TOTAL_PROSE = re.compile(r'(\d+(?:\.\d+)?) ms total(?= ?[,)])')


def fix_step_text(text, mcp=True):
    if not text or not mcp:
        return text
    text = STEP_SENTENCE.sub(lambda m: f'in {m.group(1)} ms for the two calls (across the handshake requests including the '
                                       f'initialized notification: median {m.group(2)} ms, slowest {m.group(3)} ms'
                                       + (f', range {m.group(4)} ms)' if m.group(4) else ')'), text)
    text = STEP_ROW.sub(lambda m: f'| Request latency (median / slowest / range) | {m.group(1)} ms / {m.group(2)} ms / '
                                  f'{m.group(3)} ms ({m.group(4)} requests) |', text)
    return TOTAL_PROSE.sub(lambda m: f'{m.group(1)} ms for initialize and tools/list', text)


SCORE_BASIS = ('| Score basis | Transport-only evidence cannot reach Grade A under AQEF-30, so the score is capped at '
               '89.4 (Grade B). |')


def _evidence_row(report):
    wire = str(report.get('output_wire') or '')
    when = report.get('executed_at')
    if not wire or not when:
        return None
    from datetime import datetime, timezone
    try:
        stamp = datetime.fromtimestamp(float(when), timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (TypeError, ValueError, OSError):
        return None
    digest = hashlib.sha256(wire.encode('utf-8')).hexdigest()[:16]
    return f'| Evidence | Probe executed {stamp}; stored capture SHA-256 {digest} |'


def _table_end(md):
    table = re.search(r'(?ms)^#{2,3} Measured Facts[ \t]*\n\s*(\|[^\n]*\|\n)(\|[^\n]*\|\n)(?:\|[^\n]*\|\n)*', md + '\n')
    return min(table.end(), len(md)) if table else None


def _add_row(md, row):
    end = _table_end(md)
    if end is None:
        return md
    return md[:end].rstrip('\n') + '\n' + row + '\n' + md[end:]


def extra_check(report, md, pros):
    found = []
    score = report.get('eval_score')
    texts = [md] + list(pros) + as_list(report.get('cons')) + [str(report.get(k) or '') for k in ('workflow_recommendation', 'summary')]
    if any(fix_score_text(t, report) != t for t in texts):
        found.append('C10')
    if FLAT_LATENCY_ROW.search(md) or FLAT_LATENCY_PROSE.search(md):
        found.append('C11')
    wire = str(report.get('output_wire') or '')
    if 'inputSchema' not in wire and 'with_input_schema' not in wire and any(SCHEMA_CLAUSE.search(p) for p in pros):  # cons already caveat it
        found.append('C12')
    if PY_BOOL.search(md):
        found.append('C13')
    row = _evidence_row(report)
    if row and _table_end(md) is not None and row not in md:
        found.append('C14')
    if (is_transport(report) and report.get('eval_grade') == 'B' and score is not None
            and abs(float(score) - 89.4) < 0.05 and _table_end(md) is not None and SCORE_BASIS not in md):
        found.append('C15')
    if CORRECTION_MARK in md and re.search(r'(?m)^> \*\*AQEF-30 (?:Quality )?Profile', md):
        found.append('C16')
    return found


def fix_score_text(text, report):
    """Old scores and an old Grade A left in sentences take the report's current values (C10, C17)."""
    score, grade = report.get('eval_score'), report.get('eval_grade')
    if not text:
        return text
    text = fix_step_text(text, mcp='mcp' in str(report.get('test_method') or '').lower())
    if score is not None:
        text = SCORE_SLASH.sub(lambda m: _score_text(score) + m.group(2), text)
    if grade and grade != 'A':
        text = OLD_GRADE_A.sub(lambda m: m.group(1) + grade, text)
    return text


def extra_fix(report, md, pros, cons):
    score = report.get('eval_score')
    md = fix_score_text(md, report)
    pros = [fix_score_text(p, report) for p in pros]
    cons = [fix_score_text(c, report) for c in cons]
    for key in ('workflow_recommendation', 'summary'):
        report[key] = fix_score_text(report.get(key), report)
    md = FLAT_LATENCY_ROW.sub(lambda m: f'|{m.group(1)} (single trial){m.group(2)}| {m.group(3)} ms (one trial; p95 and '
                                        'jitter not measurable) |', md)
    md = FLAT_LATENCY_PROSE.sub('', md)
    if not re.search(r'inputSchema|with_input_schema', str(report.get('output_wire') or '')):
        pros = [SCHEMA_CLAUSE.sub(lambda m: m.group(0) + SCHEMA_NOTE, p) for p in pros]
    md = PY_BOOL.sub(lambda m: f'| {m.group(1).lower()} |', md)
    if CORRECTION_MARK in md:
        # Drop the superseded quality-profile block; the correction note already states grade and score.
        md = re.sub(r'(?m)^(?:> \[!NOTE\]\n)?> \*\*AQEF-30 (?:Quality )?Profile[^\n]*\n(?:>[^\n]*\n)*\n?', '', md)
    if (is_transport(report) and report.get('eval_grade') == 'B' and score is not None
            and abs(float(score) - 89.4) < 0.05 and SCORE_BASIS not in md):
        md = _add_row(md, SCORE_BASIS)
    return md, pros, cons


COLUMNS = ('id', 'test_method', 'evidence_scope', 'eval_grade', 'eval_score', 'latency_ms', 'agent_name', 'pros',
           'cons', 'workflow_recommendation', 'content_md', 'output_wire', 'executed_at', 'summary', 'input_wire')
WRITABLE = ('content_md', 'pros', 'cons', 'output_wire', 'workflow_recommendation', 'summary')


def apply_all(conn, backup_path=None, write=True):
    """Normalize every stored report in the caller's transaction. Returns {rule: rows fixed, ...}.

    When backup_path is given, the old values of every changed row are written there first. The caller commits.
    """
    import time
    from collections import Counter
    cur = conn.cursor()
    cur.execute(f"select {', '.join(COLUMNS)} from agent_test_reports")
    counts, updates, backup = Counter(), [], []
    for row in cur.fetchall():
        report = dict(zip(COLUMNS, row))
        new, applied = normalize(report)
        changed = [k for k in WRITABLE if (new.get(k) or '') != (report.get(k) or '')]
        if not changed:
            continue
        counts.update(applied)
        counts['rows'] += 1
        backup.append({'id': report['id'], **{k: report.get(k) for k in WRITABLE}})
        updates.append((new['content_md'], new['pros'], new['cons'], new['output_wire'], new['workflow_recommendation'],
                        new['summary'], time.time(), report['id']))
    if write and updates:
        if backup_path:
            from pathlib import Path
            Path(backup_path).parent.mkdir(parents=True, exist_ok=True)
            with open(backup_path, 'w') as fh:
                for item in backup:
                    fh.write(json.dumps(item, ensure_ascii=False, default=str) + '\n')
        for start in range(0, len(updates), 500):
            cur.executemany('update agent_test_reports set content_md=%s, pros=%s, cons=%s, output_wire=%s, '
                            'workflow_recommendation=%s, summary=%s, updated_at=%s where id=%s', updates[start:start + 500])
    return dict(counts)


if __name__ == '__main__':
    import sys
    from datetime import datetime
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from remediate_all_test_reports import connect
    apply = '--apply' in sys.argv
    root = Path(__file__).resolve().parents[1]
    path = root / 'logs/ops/report-quality' / f'backup-consistency-{datetime.now():%Y%m%d-%H%M%S}.jsonl'
    conn = connect()
    print(json.dumps(apply_all(conn, path if apply else None, write=apply)))
    if apply:
        conn.commit()
        print(f'backup: {path.relative_to(root)}')


# --- C18: a transport label on a report whose stored request is a real call (11-10 second re-score) ---------
_TRANSPORT_REQUEST = re.compile(r'^(?:GET|POST|tools/list|initialize|POST initialize.*|GET \(3-probe burst\))?$')
_CALL_IN_BODY = re.compile(r'tools/call|message/send|SendMessage')


def executed_method(report):
    """'MCP Tool Call' / 'A2A Message' when a transport-labelled report's input_wire shows a real call, else None."""
    method = str(report.get('test_method') or '')
    if method.lower() not in ('a2a agent card', 'mcp tools list'):
        return None
    try:
        wire = json.loads(report.get('input_wire') or '{}')
    except (TypeError, ValueError):
        return None
    if not isinstance(wire, dict) or not wire:
        return None
    called = str(wire.get('method') or '')
    body = wire.get('body')
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            pass
    body_method = str(body.get('method') or '') if isinstance(body, dict) else ''
    if body is not None and (_CALL_IN_BODY.search(json.dumps(body)) or
                             (body_method and not _TRANSPORT_REQUEST.match(body_method))):
        real = True
    elif called:
        real = not _TRANSPORT_REQUEST.match(called)
    else:
        real = method.lower() == 'mcp tools list'  # tool arguments only, no protocol method
    if not real:
        return None
    return 'MCP Tool Call' if method.lower() == 'mcp tools list' else 'A2A Message'
