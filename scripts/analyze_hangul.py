#!/usr/bin/env python3
import sqlite3
import re
from collections import Counter

conn = sqlite3.connect('gateway-data/collector.sqlite3')
cur = conn.cursor()

hangul_pattern = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]+')

cur.execute('SELECT id, content_md FROM agent_test_reports ORDER BY id ASC')
rows = cur.fetchall()

kr_words = Counter()
kr_by_report = {}

for rid, content in rows:
    matches = hangul_pattern.findall(content)
    if matches:
        kr_by_report[rid] = matches
        for m in matches:
            kr_words[m] += 1

print(f"Total reports with Hangul: {len(kr_by_report)}")
print(f"Total Hangul occurrences: {sum(kr_words.values())}")
print("\nTop 30 most frequent Hangul words:")
for word, count in kr_words.most_common(30):
    print(f"  {word}: {count}")

print("\nSample lines containing Hangul across various report IDs:")
for rid in list(kr_by_report.keys())[::25]:
    cur.execute("SELECT content_md FROM agent_test_reports WHERE id = ?", (rid,))
    c = cur.fetchone()[0]
    lines = [line for line in c.split("\n") if hangul_pattern.search(line)]
    print(f"\nReport #{rid}:")
    for l in lines[:3]:
        print(f"  {l.strip()[:100]}")

conn.close()
