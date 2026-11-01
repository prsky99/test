import sqlite3, re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, resource_id, content_md FROM agent_test_reports')
rows = cur.fetchall()

bullets_by_key = {}
for rid, resid, md in rows:
    for line in md.split('\n'):
        m = re.match(r'^\s*-\s*\*\*([^*]+)\*\*:\s*`?(https?://[^`\s]+)`?', line)
        if m:
            key, url = m.group(1).strip(), m.group(2).strip()
            if 'agentconcierge.biz' not in url:
                bullets_by_key.setdefault(key, []).append((rid, url))

print(f'Distinct bullet keys with non-gateway URLs: {len(bullets_by_key)}')
for k, v in sorted(bullets_by_key.items(), key=lambda x: len(x[1]), reverse=True):
    print(f'  {k} ({len(v)} occurrences): sample URL = {v[0][1]}')
conn.close()
