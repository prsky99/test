"""Check whether directories that read the official MCP Registry list Agent Concierge (read-only, one GET each).

    .venv/bin/python -m scripts.directory_presence            # prints and appends one JSON line
    .venv/bin/python -m scripts.directory_presence --no-log

Appends to logs/growth/directory-presence.jsonl so the date each listing appeared can be compared
with the traffic counts (agent_market/concierge/traffic.py). Five public pages, once a day at most.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

NAME = 'biz.agentconcierge/agent-concierge'
USER_AGENT = 'Mozilla/5.0 (compatible; AgentConcierge-presence/1.0; site owner)'
CHECKS = [
    ('official_registry', 'https://registry.modelcontextprotocol.io/v0.1/servers?search=' + NAME, r'"name"\s*:\s*"biz\.agentconcierge/agent-concierge"'),
    ('glama', 'https://glama.ai/mcp/connectors/' + NAME, r'agentconcierge\.biz/mcp'),
    ('pulsemcp', 'https://www.pulsemcp.com/servers?q=agent+concierge', r'agentconcierge|biz\.agentconcierge'),
    ('mcpservers_org', 'https://mcpservers.org/search?query=agent+concierge', r'agentconcierge'),
    ('mcp_so', 'https://mcp.so/search?q=agent+concierge', r'agentconcierge'),
]


def check(url, pattern, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/json'})
    try:
        with opener(request, timeout=20) as response:
            body = response.read(3_000_000).decode('utf-8', 'replace')
            return {'status': response.status, 'listed': bool(re.search(pattern, body, re.I))}
    except Exception as error:  # a failed fetch is recorded, never guessed
        return {'status': getattr(error, 'code', None), 'listed': None, 'error': type(error).__name__}


def run(opener=urllib.request.urlopen):
    return {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            **{name: check(url, pattern, opener) for name, url, pattern in CHECKS}}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', default='logs/growth/directory-presence.jsonl')
    parser.add_argument('--no-log', action='store_true')
    args = parser.parse_args(argv)
    result = run()
    line = json.dumps(result, separators=(',', ':'))
    if not args.no_log:
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
        with open(args.log, 'a', encoding='utf-8') as out:
            out.write(line + '\n')
    print(json.dumps(result, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
