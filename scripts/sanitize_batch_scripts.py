import re

files_to_clean = [
    'scripts/insert_batch280.py',
    'scripts/insert_batch281.py',
    'scripts/insert_batch282.py'
]

raw_bullet_keys = [
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
    'Complementary MCP Server', 'MCP Server Companion', 'Agent Card'
]

pattern_bullets = r'^[ \t]*-[ \t]*\*\*(?:' + '|'.join(re.escape(k) for k in raw_bullet_keys) + r')\*\*:[^\n]*\n?'

for fpath in files_to_clean:
    with open(fpath, 'r', encoding='utf-8') as f:
        code = f.read()

    # 1. Remove raw upstream and endpoint bullets
    code = re.sub(pattern_bullets, '', code, flags=re.MULTILINE)
    
    # 2. In HTTP blocks, replace Host: headers with agentconcierge.biz
    def fix_host(match):
        h = match.group(1).strip()
        if h == 'agentconcierge.biz':
            return match.group(0)
        return 'Host: agentconcierge.biz'
    code = re.sub(r'Host:\s*([a-zA-Z0-9.-]+)', fix_host, code)
    
    # 3. Clean up excessive newlines
    code = re.sub(r'\n{3,}', '\n\n', code)
    
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(code)
        
    print(f"Sanitized {fpath}")
