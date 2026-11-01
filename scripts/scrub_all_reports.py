#!/usr/bin/env python3
"""
Comprehensive Database Scrubber for agent_test_reports:
Eliminates all raw upstream URLs and Upstream Provider Target lines.
Enforces 100% Managed Gateway alignment across dual SQLite databases:
  - gateway-data/gateway.sqlite3
  - gateway-data/collector.sqlite3
"""

import sqlite3
import re
from urllib.parse import urlparse

RAW_ENDPOINT_KEYS = [
    'Upstream Provider Target', 'Upstream Target / Binding', 'Upstream Agent Card',
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

def scrub_content_md(md, kind, resid):
    gateway_url = f"https://agentconcierge.biz/api/gateway/{kind}/{resid}"
    
    # 1. Extract raw upstream URLs from bullets before deletion
    upstream_urls = set()
    
    # Check all Upstream bullets
    for m in re.finditer(r'-\s*\*\*Upstream[^\*]+\*\*:\s*`?([^\`\n\r\s]+)`?', md):
        u = m.group(1).strip()
        if u and 'agentconcierge.biz' not in u and u.startswith('http'):
            upstream_urls.add(u)
            
    # Check all known raw endpoint keys
    bullet_pattern = r'-\s*\*\*(?:' + '|'.join(re.escape(k) for k in RAW_ENDPOINT_KEYS) + r')\*\*:\s*`?([^\`\n\r\s]+)`?'
    for m in re.finditer(bullet_pattern, md):
        u = m.group(1).strip()
        if u and 'agentconcierge.biz' not in u and u.startswith('http'):
            upstream_urls.add(u)

    # 2. Remove all raw upstream bullets and raw endpoint bullets
    # e.g., - **Upstream Provider Target**: `https://...`
    #       - **Endpoint URL**: `https://...`
    # Keep `- **Managed Gateway Endpoint**: ...` untouched!
    pattern_to_remove = r'^[ \t]*-[ \t]*\*\*(?:' + '|'.join(re.escape(k) for k in RAW_ENDPOINT_KEYS) + r')\*\*:[^\n]*\n?'
    md = re.sub(pattern_to_remove, '', md, flags=re.MULTILINE)
    
    # Also remove any remaining bullet matching r'-\s*\*\*Upstream.*'
    md = re.sub(r'^[ \t]*-[ \t]*\*\*Upstream[^\*\n]+\*\*:[^\n]*\n?', '', md, flags=re.MULTILINE)

    # 3. Replace all discovered upstream URLs with gateway_url across content_md
    for u in upstream_urls:
        u_clean = u.rstrip('/')
        md = md.replace(u_clean + '/', gateway_url)
        md = md.replace(u_clean, gateway_url)
        
        # Replace Host: header in wire blocks if present
        try:
            parsed = urlparse(u_clean)
            if parsed.netloc and parsed.netloc != 'agentconcierge.biz':
                md = re.sub(r'Host:\s*' + re.escape(parsed.netloc), 'Host: agentconcierge.biz', md, flags=re.IGNORECASE)
        except Exception:
            pass

    # 4. Replace any remaining non-agentconcierge Host: headers in HTTP request blocks
    def fix_host(match):
        h = match.group(1).strip()
        if h == 'agentconcierge.biz':
            return match.group(0)
        if '.' in h or ':' in h:
            return 'Host: agentconcierge.biz'
        return match.group(0)

    md = re.sub(r'Host:\s*([^\s\r\n]+)', fix_host, md, flags=re.IGNORECASE)

    # 5. Clean up any excessive newlines created by bullet removals
    md = re.sub(r'\n{3,}', '\n\n', md)
    
    # 6. Ensure Managed Gateway Endpoint bullet exists if somehow missing
    if 'Managed Gateway Endpoint' not in md:
        # Insert under Technical Protocol / Specifications section
        sec_m = re.search(r'(##\s*(?:2\.\s*)?Technical\s+[^\n]+\n+)', md)
        if sec_m:
            insert_pos = sec_m.end()
            md = md[:insert_pos] + f"- **Managed Gateway Endpoint**: `{gateway_url}`\n" + md[insert_pos:]
        else:
            md = f"- **Managed Gateway Endpoint**: `{gateway_url}`\n\n" + md

    return md

def scrub_wire(wire_str, kind, resid):
    if not wire_str:
        return wire_str
    gateway_url = f"https://agentconcierge.biz/api/gateway/{kind}/{resid}"
    # If wire_str contains an endpoint or url field pointing to an external domain
    # e.g., "url": "https://...", replace external domain with gateway_url
    def repl_url(match):
        u = match.group(0)
        if 'agentconcierge.biz' in u:
            return u
        return gateway_url
    
    # Replace non-gateway http(s) URLs in wire if they look like endpoints
    return re.sub(r'https?://[^\s\"\'<>]+', repl_url, wire_str)

def process_database(db_path):
    print(f"\nProcessing database: {db_path}...")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    
    cur.execute("SELECT id, resource_id, kind, content_md, input_wire, output_wire FROM agent_test_reports")
    rows = cur.fetchall()
    print(f"Total reports to inspect: {len(rows)}")
    
    updated_count = 0
    hangul_errors = 0
    
    for rid, resid, kind, old_md, in_w, out_w in rows:
        new_md = scrub_content_md(old_md, kind, resid)
        
        # Check Korean characters in new_md
        hangul = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", new_md)
        if hangul:
            print(f"ERROR: Hangul characters found in Report #{rid}: {set(hangul)}")
            hangul_errors += 1
            
        # Verify Pros and Cons are preserved
        assert "### Pros" in new_md, f"Report #{rid} missing ### Pros"
        assert "### Cons" in new_md, f"Report #{rid} missing ### Cons"
        
        # Update if changed
        if new_md != old_md:
            cur.execute("""
                UPDATE agent_test_reports 
                SET content_md = ?
                WHERE id = ?
            """, (new_md, rid))
            updated_count += 1
            
    conn.commit()
    print(f"Updated reports in {db_path}: {updated_count} / {len(rows)}")
    if hangul_errors > 0:
        raise ValueError(f"Found {hangul_errors} reports with Hangul violations!")
        
    # Verify post-scrub status
    cur.execute("SELECT COUNT(*) FROM agent_test_reports WHERE content_md LIKE '%Upstream Provider Target%'")
    rem_target = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM agent_test_reports WHERE content_md LIKE '%Upstream Target / Binding%'")
    rem_binding = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM agent_test_reports WHERE content_md LIKE '%Upstream Agent Card%'")
    rem_card = cur.fetchone()[0]
    print(f"Verification {db_path}: Upstream Provider Target remaining = {rem_target}")
    print(f"Verification {db_path}: Upstream Target / Binding remaining = {rem_binding}")
    print(f"Verification {db_path}: Upstream Agent Card remaining = {rem_card}")
    
    cur.execute("PRAGMA integrity_check")
    ic = cur.fetchone()[0]
    print(f"Integrity check for {db_path}: {ic}")
    assert ic == "ok", f"Integrity check failed: {ic}"
    conn.close()

if __name__ == "__main__":
    for db in ['gateway-data/gateway.sqlite3', 'gateway-data/collector.sqlite3']:
        process_database(db)
    print("\nAll databases successfully scrubbed and verified!")
