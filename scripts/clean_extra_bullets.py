import sqlite3
import re

ADDITIONAL_KEYS = [
    'Agent Card', 'Alternative Discovery URL', 'Alternative x402 Gateway', 
    'Fallback REST Endpoint'
]

pattern = r'^[ \t]*-[ \t]*\*\*(?:' + '|'.join(re.escape(k) for k in ADDITIONAL_KEYS) + r')\*\*:[^\n]*\n?'

for db_path in ['gateway-data/gateway.sqlite3', 'gateway-data/collector.sqlite3']:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, content_md FROM agent_test_reports")
    rows = cur.fetchall()
    updated = 0
    for rid, md in rows:
        if re.search(pattern, md, flags=re.MULTILINE):
            new_md = re.sub(pattern, '', md, flags=re.MULTILINE)
            new_md = re.sub(r'\n{3,}', '\n\n', new_md)
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = ?", (new_md, rid))
            updated += 1
    conn.commit()
    print(f"[{db_path}] cleaned additional raw endpoint bullets: {updated}")
    conn.close()
