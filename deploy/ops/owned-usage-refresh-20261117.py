"""Refresh the stored tool definitions of the two first-party data agents after r12 (11-17 20:2x, 운영·SRE).

r12 added an optional `note` to the output schema of research-papers (1fe699cd) and technology-news (1e03611a).
owned_data_agents.activation.install() only rewrites usage_full_tools when the hash is missing or the old 160-char
research form, so production still holds the old definitions and owned_capability_adapter.profile() refuses both
("The first-party research/news schema changed"); approve_model_contracts cannot run.

This does exactly what install() does for a missing hash (store.record_usage with the code's tool_spec) for these two
keys only, after checking source and url. Dry run by default; --apply is run by the PM. Before values go to
gateway-data/ops/owned-usage-1117/before.json (restore: --restore).
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
KEYS = ('research-papers', 'technology-news')
BACKUP = ROOT / 'gateway-data/ops/owned-usage-1117/before.json'


def main(argv):
    if 'PYTEST_CURRENT_TEST' in os.environ:
        print('refused under pytest'); return 2
    from scripts.apply_category_refresh import open_store
    from agent_market.collector import usage
    from agent_market.owned_data_agents.catalog import tool_spec
    store, connection = open_store()
    try:
        if '--restore' in argv:
            saved = json.loads(BACKUP.read_text())
            for rid, full in saved.items():
                tools = json.loads(full); compact = usage.compact_tools(tools)
                store.record_usage(int(rid), compact, usage.tools_hash(compact), {}, None, None, full_tools=tools)
                print('restored', rid)
            return 0
        plan, before = [], {}
        for identity in KEYS:
            rows = store.query('SELECT id FROM resources WHERE key=?', ('agentconcierge-owned:' + identity,))
            if len(rows) != 1:
                print(identity, 'not exactly one row; stop'); return 1
            resource = store.resource(rows[0]['id'])
            if resource.get('source') != 'agentconcierge-owned' or not str(resource.get('url', '')).endswith('/api/owned-data-agents/' + identity + '/mcp'):
                print(identity, 'unexpected source/url; stop'); return 1
            tools = [tool_spec(identity)]
            current = json.loads(resource.get('usage_full_tools') or '[]')
            same = current == tools
            print(f"{identity} id={resource['id']}: stored == code? {same}")
            if not same:
                before[str(resource['id'])] = resource.get('usage_full_tools') or '[]'
                plan.append((resource['id'], tools))
        if '--apply' not in argv:
            print('dry run; add --apply to write'); return 0
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        BACKUP.write_text(json.dumps(before, ensure_ascii=False))
        for rid, tools in plan:
            compact = usage.compact_tools(tools)
            store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, None, full_tools=tools)
            print('refreshed', rid)
        return 0
    finally:
        store.close(); connection.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
