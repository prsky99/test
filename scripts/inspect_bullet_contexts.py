import sqlite3
import re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, resource_id, content_md FROM agent_test_reports')
rows = cur.fetchall()

keys_to_inspect = ['Endpoint URL', 'Canonical Endpoint', 'Agent Card URL', 'Oracle Endpoint', 'Execution Endpoint', 'Card Endpoint']
samples = {k: [] for k in keys_to_inspect}

for rid, resid, md in rows:
    lines = md.split('\n')
    for i, line in enumerate(lines):
        for k in keys_to_inspect:
            if re.match(r'^\s*-\s*\*\*' + re.escape(k) + r'\*\*:', line):
                context = '\n'.join(lines[max(0, i-2):min(len(lines), i+3)])
                if len(samples[k]) < 2:
                    samples[k].append((rid, context))

for k in keys_to_inspect:
    print(f'=== Key: {k} ===')
    for rid, ctx in samples[k]:
        print(f'-- Report {rid} --\n{ctx}\n')

conn.close()
