import sqlite3
import re

EXTRA_TARGET_KEYS = [
    'Audit Record Archive', 'ERC-8004 Registration', 'Service Manifest',
    'Skill Documentation', 'Prover API Path', 'Identity Status URL', 'JWKS Endpoint'
]

pattern_del = r'^[ \t]*-[ \t]*\*\*(?:' + '|'.join(re.escape(k) for k in EXTRA_TARGET_KEYS) + r')\*\*:[^\n]*\n?'

for db_path in ['gateway-data/gateway.sqlite3', 'gateway-data/collector.sqlite3']:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, content_md FROM agent_test_reports")
    rows = cur.fetchall()
    updated = 0
    for rid, md in rows:
        new_md = re.sub(pattern_del, '', md, flags=re.MULTILINE)
        # Also clean getbody.md agent card mention
        new_md = new_md.replace('`https://getbody.md/.well-known/agent-card.json`', 'the Managed Gateway endpoint')
        new_md = re.sub(r'\n{3,}', '\n\n', new_md)
        if new_md != md:
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = ?", (new_md, rid))
            updated += 1
    conn.commit()
    print(f"[{db_path}] cleaned extra specific endpoint bullets: {updated}")
    conn.close()
