#!/usr/bin/env python3
"""Audit and improve published agent test reports with Claude Opus 5.5 through the Message Batches API (11-10).

    report_quality_api.py sample N        stratified sample of N reports -> logs/ops/report-quality/sample.jsonl
    report_quality_api.py submit          one batch (claude-opus-5-5, effort medium) -> batch id in state.json
    report_quality_api.py collect         poll once; when ended, write results.jsonl and record cost
    report_quality_api.py summarize       issue counts and score distribution -> summary.json
    report_quality_api.py apply [--dry]   validate rewrites, back up originals, update agent_test_reports

The rubric is AQEF-30 (the existing framework document). Rewrites may only restate measured facts already in
the report or its output_wire; apply() rejects any rewrite that adds a number not present in the source, that
is not English, or that drops a field. Originals are saved to backup-<time>.jsonl before any UPDATE.
Runs from gateway-data/ops-llm-venv. Cost is logged to logs/ops/llm-usage.jsonl with purpose report_quality.
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ops_llm  # noqa: E402

OUT = ROOT / 'logs/ops/report-quality'
STATE = OUT / 'state.json'
RUBRIC = Path.home() / '.gemini/antigravity/brain/c483b1b9-b552-4e83-b78d-d6f36bf0128d/test_report_quality_evaluation_expert_framework.md'
MODEL = 'claude-opus-5-5'
BATCH_PRICE = {'input': 2.0, 'output': 10.0, 'cache_write': 2.5, 'cache_read': 0.10}  # Opus 5.5 at 50% batch rate
FIELDS = ('summary', 'pros', 'cons', 'workflow_recommendation', 'content_md')
PSQL = ['/opt/homebrew/opt/postgresql@18/bin/psql', '-h', str(ROOT / 'gateway-data/postgres18/run'), '-p', '55432',
        '-d', 'agentcon_cutover_20261020_191757', '-v', 'ON_ERROR_STOP=1', '-Atc']

INSTRUCTIONS = """You are a senior QA reviewer auditing one published AI agent test report against the AQEF-30
framework above. The report is public, English-only, and must state only what the measured probe showed.

Return ONLY one JSON object, no prose, with this shape:
{"scores": {"evidence": 0-20, "accuracy": 0-20, "clarity": 0-20, "actionability": 0-20, "safety": 0-20},
 "issues": [{"code": "<snake_case>", "severity": "high|medium|low", "field": "<field>", "note": "<short English>"}],
 "needs_rewrite": true|false,
 "rewrite": null | {"summary": "...", "pros": ["..."], "cons": ["..."], "workflow_recommendation": "...", "content_md": "..."}}

Issue codes to prefer (add others only when none fit): unsupported_claim, number_mismatch, missing_evidence,
grade_inconsistent, vague_language, marketing_tone, overclaim_capability, missing_limitation, wrong_test_scope,
stale_or_contradictory, non_english, formatting, upstream_leak (secrets, private hosts, internal paths), duplicate_text.

needs_rewrite is true only when the total score is below 85 or any high-severity issue exists. When rewriting:
- Use only facts present in the report fields or in output_wire. Never add numbers, tools, capabilities,
  customers or claims that are not in the input. Keep every measured number exactly as written.
- English only. Plain, neutral, specific. No hype words.
- pros and cons are JSON arrays of short sentences. cons must state what was not tested.
- Keep content_md in Markdown with the same section headings when they exist; keep it no longer than the original
  unless a missing limitation must be added.
"""


def psql(sql):
    return subprocess.run(PSQL + [sql], capture_output=True, text=True, check=True).stdout


def sample(n):
    OUT.mkdir(parents=True, exist_ok=True)
    sql = f"""select row_to_json(t) from (
      select id, kind, eval_grade, eval_score, is_success, status_code, latency_ms, test_method, tool_name,
             agent_name, summary, pros, cons, workflow_recommendation, content_md, left(output_wire, 2500) output_wire
      from (select r.*, row_number() over (partition by kind, coalesce(eval_grade,'-'), is_success,
                   date_trunc('week', to_timestamp(created_at)) order by md5(id::text || 'aqef')) rn
            from agent_test_reports r) x
      where rn <= 40 order by md5(id::text || 'pick') limit {int(n)}) t"""
    rows = [line for line in psql(sql).splitlines() if line.strip()]
    (OUT / 'sample.jsonl').write_text('\n'.join(rows) + '\n')
    kinds = {}
    for line in rows:
        kinds[json.loads(line)['kind']] = kinds.get(json.loads(line)['kind'], 0) + 1
    print(json.dumps({'sampled': len(rows), 'by_kind': kinds}))


def client():
    import anthropic
    return anthropic.Anthropic(api_key=ops_llm.KEY_FILE.read_text().strip(), max_retries=3, timeout=120.0)


def submit():
    rows = [json.loads(line) for line in (OUT / 'sample.jsonl').read_text().splitlines() if line.strip()]
    system = [{'type': 'text', 'text': RUBRIC.read_text() + '\n\n' + INSTRUCTIONS, 'cache_control': {'type': 'ephemeral'}}]
    requests = []
    for row in rows:
        payload = {k: row.get(k) for k in ('kind', 'eval_grade', 'eval_score', 'is_success', 'status_code', 'latency_ms',
                                           'test_method', 'tool_name', 'agent_name', *FIELDS, 'output_wire')}
        requests.append({'custom_id': f"r{row['id']}", 'params': {
            'model': MODEL, 'max_tokens': 6000, 'output_config': {'effort': 'medium'}, 'system': system,
            'messages': [{'role': 'user', 'content': 'Report JSON:\n' + json.dumps(payload, ensure_ascii=False)}]}})
    batch = client().messages.batches.create(requests=requests)
    STATE.write_text(json.dumps({'batch_id': batch.id, 'submitted': datetime.now().isoformat(), 'count': len(requests)}))
    print(json.dumps({'batch_id': batch.id, 'count': len(requests), 'status': batch.processing_status}))


def _cost(usage):
    return ((usage.input_tokens or 0) * BATCH_PRICE['input'] + (usage.output_tokens or 0) * BATCH_PRICE['output']
            + (usage.cache_creation_input_tokens or 0) * BATCH_PRICE['cache_write']
            + (usage.cache_read_input_tokens or 0) * BATCH_PRICE['cache_read']) / 1_000_000


def _json_object(text):
    start, end = text.find('{'), text.rfind('}')
    return json.loads(text[start:end + 1]) if start >= 0 and end > start else None


def collect():
    state = json.loads(STATE.read_text())
    c = client()
    batch = c.messages.batches.retrieve(state['batch_id'])
    print(json.dumps({'status': batch.processing_status, 'counts': batch.request_counts.to_dict()}))
    if batch.processing_status != 'ended' or state.get('collected'):
        return
    total, out = 0.0, []
    for item in c.messages.batches.results(state['batch_id']):
        rid = int(item.custom_id[1:])
        if item.result.type != 'succeeded':
            out.append({'id': rid, 'error': item.result.type})
            continue
        message = item.result.message
        total += _cost(message.usage)
        text = ''.join(b.text for b in message.content if b.type == 'text')
        try:
            parsed = _json_object(text)
        except ValueError:
            parsed = None
        out.append({'id': rid, 'stop': message.stop_reason, 'result': parsed} if parsed else
                   {'id': rid, 'stop': message.stop_reason, 'unparsed': text[:500]})
    (OUT / 'results.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in out) + '\n')
    with ops_llm.USAGE.open('a') as fh:
        fh.write(json.dumps({'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'purpose': 'report_quality_batch',
                             'model': MODEL, 'outcome': 'batch_ended', 'usd': round(total, 4),
                             'batch_id': state['batch_id']}) + '\n')
    state.update(collected=True, usd=round(total, 4))
    STATE.write_text(json.dumps(state))
    print(json.dumps({'collected': len(out), 'usd': round(total, 2)}))


def summarize():
    rows = [json.loads(l) for l in (OUT / 'results.jsonl').read_text().splitlines() if l.strip()]
    sample_rows = {json.loads(l)['id']: json.loads(l) for l in (OUT / 'sample.jsonl').read_text().splitlines() if l.strip()}
    codes, sev, totals, by_kind, rewrite = {}, {}, [], {}, 0
    for row in rows:
        res = row.get('result')
        if not res:
            continue
        total = sum((res.get('scores') or {}).values())
        totals.append(total)
        kind = sample_rows.get(row['id'], {}).get('kind', '?')
        by_kind.setdefault(kind, []).append(total)
        rewrite += bool(res.get('needs_rewrite'))
        for issue in res.get('issues') or []:
            codes[issue.get('code')] = codes.get(issue.get('code'), 0) + 1
            sev[issue.get('severity')] = sev.get(issue.get('severity'), 0) + 1
    totals.sort()
    summary = {'audited': len(totals), 'failed_or_unparsed': len(rows) - len(totals), 'needs_rewrite': rewrite,
               'score_median': totals[len(totals) // 2] if totals else None,
               'score_p10': totals[len(totals) // 10] if totals else None,
               'below_85': sum(t < 85 for t in totals),
               'mean_by_kind': {k: round(sum(v) / len(v), 1) for k, v in by_kind.items()},
               'severity': sev, 'top_issues': sorted(codes.items(), key=lambda x: -x[1])[:20]}
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False))


NUM = re.compile(r'\d+(?:[.,]\d+)?')


def _numbers(text):
    return {n.replace(',', '') for n in NUM.findall(text or '')}


def _valid(original, rewrite):
    if not isinstance(rewrite, dict) or any(k not in rewrite or rewrite[k] in (None, '', []) for k in FIELDS):
        return 'missing_field'
    source = ' '.join(str(original.get(k) or '') for k in (*FIELDS, 'output_wire', 'eval_score', 'latency_ms', 'status_code'))
    new_text = ' '.join(json.dumps(rewrite[k], ensure_ascii=False) if isinstance(rewrite[k], list) else str(rewrite[k])
                        for k in FIELDS)
    if re.search(r'[ㄱ-힝]', new_text):
        return 'non_english'
    added = _numbers(new_text) - _numbers(source) - {'0', '1', '2', '3', '4', '5', '30', '100'}
    if added:
        return 'new_numbers:' + ','.join(sorted(added)[:5])
    if not all(isinstance(rewrite[k], list) for k in ('pros', 'cons')):
        return 'pros_cons_not_list'
    return None


def _quote(value):
    return "'" + value.replace("'", "''") + "'"


def apply(dry):
    rows = [json.loads(l) for l in (OUT / 'results.jsonl').read_text().splitlines() if l.strip()]
    originals = {json.loads(l)['id']: json.loads(l) for l in (OUT / 'sample.jsonl').read_text().splitlines() if l.strip()}
    accepted, rejected = [], {}
    for row in rows:
        res = row.get('result') or {}
        if not res.get('needs_rewrite') or not res.get('rewrite'):
            continue
        reason = _valid(originals[row['id']], res['rewrite'])
        if reason:
            rejected[reason.split(':')[0]] = rejected.get(reason.split(':')[0], 0) + 1
            continue
        accepted.append((row['id'], res['rewrite']))
    report = {'accepted': len(accepted), 'rejected': rejected}
    if dry or not accepted:
        print(json.dumps(report))
        return
    ids = ','.join(str(i) for i, _ in accepted)
    backup = OUT / f'backup-{datetime.now().strftime("%Y%m%d-%H%M%S")}.jsonl'
    backup.write_text(psql(f"select row_to_json(t) from (select id, {', '.join(FIELDS)}, updated_at from "
                           f"agent_test_reports where id in ({ids})) t"))
    statements = ['BEGIN;']
    for rid, rw in accepted:
        sets = ', '.join(f"{k} = {_quote(json.dumps(rw[k], ensure_ascii=False) if isinstance(rw[k], list) else rw[k])}"
                         for k in FIELDS)
        statements.append(f'UPDATE agent_test_reports SET {sets}, updated_at = {time.time()} WHERE id = {rid};')
    statements.append('COMMIT;')
    sql_file = OUT / f'apply-{datetime.now().strftime("%Y%m%d-%H%M%S")}.sql'
    sql_file.write_text('\n'.join(statements))
    subprocess.run(PSQL[:-1] + ['-q', '-f', str(sql_file)], check=True)
    report.update(backup=str(backup.relative_to(ROOT)), sql=str(sql_file.relative_to(ROOT)))
    print(json.dumps(report))


if __name__ == '__main__':
    cmd = sys.argv[1:] or ['']
    {'sample': lambda: sample(cmd[1] if len(cmd) > 1 else 1500), 'submit': submit, 'collect': collect,
     'summarize': summarize, 'apply': lambda: apply('--dry' in cmd)}[cmd[0]]()
