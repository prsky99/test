import sqlite3
import re
from urllib.parse import urlparse

def clean_report_markdown(md, kind, resid):
    gateway_url = f"https://agentconcierge.biz/api/gateway/{kind}/{resid}"
    
    # 1. Extract upstream targets before removing
    upstream_urls = []
    # Match any bullet with upstream or endpoint
    for m in re.finditer(r'-\s*\*\*Upstream[^\*]+\*\*:\s*`?([^\`\n\r\s]+)`?', md):
        u = m.group(1).strip()
        if u and 'agentconcierge.biz' not in u:
            upstream_urls.append(u)
            
    # Also find any other endpoint bullets that leak raw url
    for m in re.finditer(r'-\s*\*\*(?:Endpoint URL|Canonical Endpoint|Agent Card URL|Card Endpoint|Execution Endpoint|Oracle Endpoint|Server Endpoint|MCP Endpoint|A2A Endpoint|Discovery Endpoint|Service Endpoint|Primary Endpoint URL|Invocation Endpoint)\*\*:\s*`?([^\`\n\r\s]+)`?', md):
        u = m.group(1).strip()
        if u and 'agentconcierge.biz' not in u and u.startswith('http'):
            upstream_urls.append(u)

    # 2. Remove all Upstream bullet lines
    # e.g. - **Upstream Provider Target**: `...`
    #      - **Upstream Target / Binding**: `...`
    #      - **Upstream Agent Card**: `...`
    md = re.sub(r'^[ \t]*-[ \t]*\*\*Upstream[^\*\n]+\*\*:[^\n]*\n?', '', md, flags=re.MULTILINE)
    
    # Also remove duplicate raw endpoint bullets if they just repeat the raw upstream url
    raw_endpoint_keys = [
        'Endpoint URL', 'Canonical Endpoint', 'Agent Card URL', 'Card Endpoint', 
        'Execution Endpoint', 'Oracle Endpoint', 'Free Sample Endpoint',
        'Server Endpoint', 'MCP Endpoint', 'A2A Endpoint', 'Discovery Endpoint',
        'Service Endpoint', 'Primary Endpoint URL', 'Invocation Endpoint',
        'A2A Endpoint URL', 'Server Endpoint URL', 'MCP Endpoint URL',
        'A2A Runtime URL', 'Agent Service URL', 'Runtime Interface URL',
        'Public Agent Card', 'Execution Gateway', 'Per-Agent Dedicated Endpoints',
        'Primary Transport URL', 'Catalog Endpoint', 'Agent URL', 'Primary Agent URL',
        'A2A Service Endpoint', 'Well-Known Discovery URI', 'Runtime Interface',
        'Runtime Container', 'Dual MCP Interface', 'Runtime Endpoint', 'Supported Interface',
        'Complementary MCP Server', 'MCP Server Companion'
    ]
    pattern_raw_bullets = r'^[ \t]*-[ \t]*\*\*(?:' + '|'.join(re.escape(k) for k in raw_endpoint_keys) + r')\*\*:[^\n]*\n?'
    md = re.sub(pattern_raw_bullets, '', md, flags=re.MULTILINE)

    # 3. Replace all discovered upstream URLs with gateway_url
    for u in upstream_urls:
        u_clean = u.rstrip('/')
        # Replace occurrences in text, curl, backticks, parentheses
        md = md.replace(u_clean + '/', gateway_url)
        md = md.replace(u_clean, gateway_url)
        
        # Also replace host in wire headers if found
        try:
            parsed = urlparse(u_clean)
            if parsed.netloc and parsed.netloc != 'agentconcierge.biz':
                md = re.sub(r'Host:\s*' + re.escape(parsed.netloc), 'Host: agentconcierge.biz', md, flags=re.IGNORECASE)
        except Exception:
            pass

    # Clean up any potential double empty lines created by bullet deletion
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()

for test_id in [1, 2, 3, 18, 500, 805, 830]:
    cur.execute('SELECT id, resource_id, kind, content_md FROM agent_test_reports WHERE id=?', (test_id,))
    row = cur.fetchone()
    if row:
        rid, resid, kind, old_md = row
        new_md = clean_report_markdown(old_md, kind, resid)
        print(f"==================== REPORT {rid} (Resource {resid}, Kind {kind}) ====================")
        # Print lines around specifications/protocol
        lines = new_md.split('\n')
        for i, l in enumerate(lines[:35]):
            print(f"{i+1:2d}: {l}")

conn.close()
