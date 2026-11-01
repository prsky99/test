import sqlite3
import re

for db_path in ['gateway-data/gateway.sqlite3', 'gateway-data/collector.sqlite3']:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, content_md FROM agent_test_reports")
    rows = cur.fetchall()
    
    upstream_lines = 0
    non_gw_bullets = 0
    host_headers = 0
    
    for rid, md in rows:
        for line in md.split('\n'):
            if re.search(r'^\s*-\s*\*\*Upstream', line, re.I):
                upstream_lines += 1
            if line.strip().startswith('- **') and 'http' in line and 'agentconcierge.biz' not in line:
                non_gw_bullets += 1
            if re.search(r'Host:\s*(?!agentconcierge\.biz)[a-zA-Z0-9.-]+', line, re.I):
                host_headers += 1
                
    print(f"[{db_path}]")
    print(f"  Upstream bullet lines: {upstream_lines}")
    print(f"  Non-gateway bullet lines: {non_gw_bullets}")
    print(f"  Non-gateway Host headers: {host_headers}")
    conn.close()
