import sqlite3
import re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, resource_id, kind, content_md FROM agent_test_reports')
rows = cur.fetchall()

missing_upstream = []
found = 0
for rid, resid, kind, md in rows:
    m = re.search(r'-\s*\*\*Upstream[^\*]+\*\*:\s*`?([^\`\n\r]+)`?', md)
    if not m:
        missing_upstream.append(rid)
    else:
        found += 1

print(f'Total reports: {len(rows)}')
print(f'Found Upstream line: {found}')
print(f'Missing Upstream line: {len(missing_upstream)}')
if missing_upstream:
    print('Missing IDs:', missing_upstream)
conn.close()
