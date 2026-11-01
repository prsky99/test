import sqlite3
import re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, resource_id, content_md FROM agent_test_reports')
rows = cur.fetchall()

intro_urls = 0
for rid, resid, md in rows:
    # First few paragraphs
    lines = md.split('\n')
    header_found = False
    for line in lines[:15]:
        if 'This report' in line or 'The **' in line:
            if re.search(r'\(`?https?://[^`\s\)]+`?\)', line):
                intro_urls += 1
                break

print(f'Reports with raw URL in intro paragraph: {intro_urls} / {len(rows)}')
conn.close()
