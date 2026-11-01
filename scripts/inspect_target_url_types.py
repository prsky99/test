import sqlite3
import re

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, resource_id, kind, content_md FROM agent_test_reports')
rows = cur.fetchall()

occurrences_by_type = {
    'upstream_bullet': 0,
    'other_bullet': 0,
    'intro_paren': 0,
    'http_wire_or_curl': 0,
    'other': 0
}

sample_other = []

for rid, resid, kind, md in rows:
    # Find upstream target URL from bullet line
    m = re.search(r'-\s*\*\*Upstream[^\*]+\*\*:\s*`?([^\`\n\r\s]+)`?', md)
    if not m:
        continue
    target_url = m.group(1).strip()
    target_clean = target_url.rstrip('/')
    
    lines = md.split('\n')
    for line in lines:
        if target_clean in line:
            if re.search(r'^\s*-\s*\*\*Upstream', line, re.I):
                occurrences_by_type['upstream_bullet'] += 1
            elif re.search(r'^\s*-\s*\*\*', line):
                occurrences_by_type['other_bullet'] += 1
            elif re.search(r'^\s*(?:#|This report|The \*\*)', line):
                occurrences_by_type['intro_paren'] += 1
            elif 'Host:' in line or 'curl' in line or 'GET ' in line or 'POST ' in line:
                occurrences_by_type['http_wire_or_curl'] += 1
            else:
                occurrences_by_type['other'] += 1
                if len(sample_other) < 10:
                    sample_other.append((rid, line.strip()))

print('Occurrences of target URL by line type:')
for k, v in occurrences_by_type.items():
    print(f'  {k}: {v}')

print('\nSample "other" lines:')
for rid, l in sample_other:
    print(f'  [{rid}] {l[:100]}')

conn.close()
