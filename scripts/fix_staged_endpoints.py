#!/usr/bin/env python3
import re

batch_files = [
    'scripts/insert_batch278.py',
    'scripts/insert_batch279.py',
    'scripts/insert_batch280.py'
]

for file_path in batch_files:
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # We will locate each report object by report id
    # Batch 278: 828 (118, x402), 829 (59853, a2a), 830 (41921, mcp)
    # Batch 279: 831 (125, x402), 832 (59873, a2a), 833 (38015, mcp)
    # Batch 280: 834 (12947, x402), 835 (87042, a2a), 836 (58882, mcp)
    
    meta = {
        828: (118, 'x402', 'https://api.nansen.ai/api/v1/profiler/address/current-balance'),
        829: (59853, 'a2a', 'https://datoka-agent.bhazarstudio.workers.dev/a2a'),
        830: (41921, 'mcp', 'https://whichli.com/api/mcp'),
        831: (125, 'x402', 'https://stableenrich.dev/api/pdl/people-enrich'),
        832: (59873, 'a2a', 'https://fiatdock.com/a2a'),
        833: (38015, 'mcp', 'https://www.gamedevoutsourcing.com/api/mcp'),
        834: (12947, 'x402', 'https://email.intel.rallylive.ca/watch/email/spf-authorizes/mailjet'),
        835: (87042, 'a2a', 'https://agenttrafficlab.com/a2a'),
        836: (58882, 'mcp', 'https://alan.recursive.support/mcp')
    }
    
    for rid, (res_id, kind, target_url) in meta.items():
        if f'"id": {rid},' in text:
            gw_url = f"https://agentconcierge.biz/api/gateway/{kind}/{res_id}"
            
            # 1. Fix agent_url
            text = re.sub(
                rf'("id":\s*{rid},\s*"resource_id":\s*{res_id},[\s\S]*?"agent_url":\s*")[^"]+(")',
                rf'\g<1>{gw_url}\g<2>',
                text
            )
            
            # 2. Fix input_wire url if present
            # We want to replace url inside this report's input_wire
            # 3. Fix content_md
            # For 829:
            if rid == 829:
                text = text.replace(
                    "- **Protocol**: A2A Specification v1.0.0 / JSON-RPC 2.0 Transport\n- **Card Endpoint**:",
                    f"- **Protocol**: A2A Specification v1.0.0 / JSON-RPC 2.0 Transport\n- **Managed Gateway Endpoint**: `{gw_url}`\n- **Upstream Target / Binding**: `{target_url}`\n- **Card Endpoint**:"
                )
            
            # Clean wrong gw_url replacements in 830, 832, 833, 835, 836
            # In 830:
            if rid == 830:
                text = text.replace(
                    "- **Managed Gateway Endpoint**: `https://agentconcierge.biz/api/gateway/x402/118`",
                    f"- **Managed Gateway Endpoint**: `{gw_url}`"
                )
            if rid in (832, 833):
                # Replace the wrong 831 gw_url
                text = text.replace(
                    "- **Managed Gateway Endpoint**: `https://agentconcierge.biz/api/gateway/x402/125`\n- **Upstream Agent Card**: `https://fiatdock.com/.well-known/agent-card.json`",
                    f"- **Managed Gateway Endpoint**: `{gw_url}`\n- **Upstream Agent Card**: `https://fiatdock.com/.well-known/agent-card.json`"
                )
                text = text.replace(
                    "- **Managed Gateway Endpoint**: `https://agentconcierge.biz/api/gateway/x402/125`\n- **Upstream Provider Target**: `https://www.gamedevoutsourcing.com/api/mcp`",
                    f"- **Managed Gateway Endpoint**: `{gw_url}`\n- **Upstream Provider Target**: `https://www.gamedevoutsourcing.com/api/mcp`"
                )
            if rid in (835, 836):
                text = text.replace(
                    "- **Managed Gateway Endpoint**: `https://agentconcierge.biz/api/gateway/x402/12947`\n- **Upstream Agent Card**: `https://agenttrafficlab.com/.well-known/agent-card.json`",
                    f"- **Managed Gateway Endpoint**: `{gw_url}`\n- **Upstream Agent Card**: `https://agenttrafficlab.com/.well-known/agent-card.json`"
                )
                text = text.replace(
                    "- **Managed Gateway Endpoint**: `https://agentconcierge.biz/api/gateway/x402/12947`\n- **Upstream Provider Target**: `https://alan.recursive.support/mcp`",
                    f"- **Managed Gateway Endpoint**: `{gw_url}`\n- **Upstream Provider Target**: `https://alan.recursive.support/mcp`"
                )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"Finished fixing {file_path}")
