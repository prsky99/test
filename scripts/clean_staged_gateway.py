#!/usr/bin/env python3
import re

configs = [
    ('scripts/insert_batch277.py', [
        (122, 'x402', 'https://readx.sh/api/search/tweets'),
        (59869, 'a2a', 'https://agenticsuperhero.com/.well-known/agent-card.json'),
        (46467, 'mcp', 'https://wealthville.net/mcp')
    ]),
    ('scripts/insert_batch278.py', [
        (118, 'x402', 'https://api.nansen.ai/api/v1/profiler/address/current-balance'),
        (59853, 'a2a', 'https://datoka.ai/a2a'),
        (41921, 'mcp', 'https://whichli.com/api/mcp')
    ]),
    ('scripts/insert_batch279.py', [
        (125, 'x402', 'https://stableenrich.dev/api/pdl/people-enrich'),
        (59873, 'a2a', 'https://fiatdock.com/.well-known/agent-card.json'),
        (38015, 'mcp', 'https://www.gamedevoutsourcing.com/api/mcp')
    ]),
    ('scripts/insert_batch280.py', [
        (12947, 'x402', 'https://email.intel.rallylive.ca/watch/email/spf-authorizes/mailjet'),
        (87042, 'a2a', 'https://agenttrafficlab.com/a2a'),
        (58882, 'mcp', 'https://alan.recursive.support/mcp')
    ])
]

for file_path, items in configs:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    for res_id, kind, raw_url in items:
        gw_url = f"https://agentconcierge.biz/api/gateway/{kind}/{res_id}"
        
        # Fix empty Managed Gateway Endpoint
        content = content.replace("- **Managed Gateway Endpoint**: \n", f"- **Managed Gateway Endpoint**: `{gw_url}`\n")
        content = content.replace("- **Managed Gateway Endpoint**:\n", f"- **Managed Gateway Endpoint**: `{gw_url}`\n")
        
        # Ensure agent_url
        content = re.sub(
            rf'"resource_id":\s*{res_id},\s*"title":\s*"([^"]+)",\s*"slug":\s*"([^"]+)",\s*"kind":\s*"{kind}",\s*"source":\s*"([^"]+)",\s*"agent_name":\s*"([^"]+)",\s*"agent_url":\s*"[^"]+"',
            rf'"resource_id": {res_id},\n        "title": "\1",\n        "slug": "\2",\n        "kind": "{kind}",\n        "source": "\3",\n        "agent_name": "\4",\n        "agent_url": "{gw_url}"',
            content
        )
        
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Cleaned and updated {file_path}")
