import sqlite3
import re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, resource_id, content_md FROM agent_test_reports')
rows = cur.fetchall()

no_proto_urls = []
for rid, resid, md in rows:
    lines = md.split('\n')
    for line in lines[:10]:
        m = re.search(r'\(`?([a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+/[^\`\)\s]+)`?\)', line)
        if m:
            val = m.group(1)
            if not val.startswith('http'):
                no_proto_urls.append((rid, val))

print(f'Reports with domain/path without protocol: {len(no_proto_urls)}')
for rid, val in no_proto_urls[:10]:
    print(f'  [{rid}] {val}')

conn.close()
