import sqlite3
import re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute("SELECT id, content_md FROM agent_test_reports")
rows = cur.fetchall()

print("=== Remaining Non-Gateway Bullet Lines ===")
bullets = set()
for rid, md in rows:
    for line in md.split('\n'):
        if line.strip().startswith('- **') and 'http' in line and 'agentconcierge.biz' not in line:
            bullets.add((line.split('**')[1] if len(line.split('**'))>1 else line, line.strip()))

for key, line in sorted(list(bullets))[:30]:
    print(f"  [{key}] {line}")

print("\n=== Remaining Non-Gateway Host Headers ===")
for rid, md in rows:
    for line in md.split('\n'):
        if re.search(r'Host:\s*(?!agentconcierge\.biz)[a-zA-Z0-9.-]+', line, re.I):
            print(f"  Report {rid}: {line.strip()}")

conn.close()
