#!/usr/bin/env python3
import sqlite3
import json
import re

hangul_pattern = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')

conn_col = sqlite3.connect('gateway-data/collector.sqlite3')
conn_gw = sqlite3.connect('gateway-data/gateway.sqlite3')

cur_col = conn_col.cursor()
cur_gw = conn_gw.cursor()

print("=== SENSITIVE LEAKS INSPECTION ===")
leak_ids = [21, 178, 207, 422, 447, 545, 557, 559, 579, 724]
for rid in leak_ids:
    cur_col.execute("SELECT id, title, summary, content_md, workflow_recommendation FROM agent_test_reports WHERE id = ?", (rid,))
    r = cur_col.fetchone()
    if r:
        rid, title, summary, content_md, wf_rec = r
        full_text = f"{title}\n{summary}\n{content_md}\n{wf_rec}"
        lines = [line for line in full_text.split("\n") if re.search(r'(localhost|127\.0\.0\.1|0\.0\.0\.0|:8200|:8400|/Users/|collector\.sqlite3|gateway\.sqlite3)', line, re.I)]
        print(f"Report #{rid} ({title}):")
        for line in lines[:3]:
            print(f"   MATCH: {line.strip()[:140]}")

print("\n=== DISCREPANCY BETWEEN COLLECTOR AND GATEWAY ===")
cur_col.execute("SELECT id, content_md, tags, pros, cons FROM agent_test_reports ORDER BY id ASC")
rows_col = {r[0]: r[1:] for r in cur_col.fetchall()}

cur_gw.execute("SELECT id, content_md, tags, pros, cons FROM agent_test_reports ORDER BY id ASC")
rows_gw = {r[0]: r[1:] for r in cur_gw.fetchall()}

diff_ids = []
for rid, data_col in rows_col.items():
    if rid not in rows_gw:
        diff_ids.append((rid, "missing in gateway"))
    elif rows_gw[rid] != data_col:
        diff_ids.append((rid, "data mismatch"))

print(f"Total different reports between collector and gateway: {len(diff_ids)}")
for diff in diff_ids[:10]:
    print(f"   Diff Report #{diff[0]}: {diff[1]}")

print("\n=== TAGS FORMAT INSPECTION (first 5 non-JSON tags) ===")
cur_col.execute("SELECT id, tags FROM agent_test_reports ORDER BY id ASC")
non_json_tags = []
for rid, tags in cur_col.fetchall():
    if tags:
        try:
            json.loads(tags)
        except:
            non_json_tags.append((rid, tags))
print(f"Total non-JSON tags: {len(non_json_tags)}")
for rid, tags in non_json_tags[:5]:
    print(f"   Report #{rid} tags: {repr(tags)}")

print("\n=== HANGUL DISTRIBUTION ===")
cur_col.execute("SELECT id, title, summary, content_md, pros, cons, workflow_recommendation FROM agent_test_reports ORDER BY id ASC")
hangul_by_col = {"title": 0, "summary": 0, "content_md": 0, "pros": 0, "cons": 0, "workflow_recommendation": 0}
hangul_report_ids = set()
for r in cur_col.fetchall():
    rid = r[0]
    has_h = False
    for i, col_name in enumerate(["title", "summary", "content_md", "pros", "cons", "workflow_recommendation"], start=1):
        if r[i] and hangul_pattern.search(r[i]):
            hangul_by_col[col_name] += 1
            has_h = True
    if has_h:
        hangul_report_ids.add(rid)

print(f"Total reports with Hangul: {len(hangul_report_ids)}")
print("Hangul occurrences by column:", hangul_by_col)
print(f"Sample report IDs with Hangul: {sorted(list(hangul_report_ids))[:15]}")

conn_col.close()
conn_gw.close()
