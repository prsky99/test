import sqlite3
import re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, content_md FROM agent_test_reports')
rows = cur.fetchall()

hosts = set()
for rid, md in rows:
    for m in re.finditer(r'Host:\s*([^\s\r\n]+)', md, re.IGNORECASE):
        h = m.group(1).strip()
        hosts.add(h)

print(f'Distinct Host headers found: {len(hosts)}')
print('Sample hosts:', sorted(list(hosts))[:25])
conn.close()
