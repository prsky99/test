"""Approve reviewed workspace model contracts and verify them with one real public read each.

Usage: python -m scripts.approve_model_contracts

Uses the same Registry.approve and capability contract test as the administrator
screen. Only the fixed reviewed pairs below are approved; each is then checked
by one real informational call, which records execution and contract evidence.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAIRS = (
    ('mcp:app.openkrill/papers', 'Paper Finder', 'docs.search.v1', 'search_papers'),
    ('agentconcierge-owned:technology-news', 'Technology News', 'news.search.v1', 'search_technology_news'),
    ('agentconcierge-owned:research-papers', 'Research Papers', 'docs.search.v1', 'search_research_papers'),
    ('agentconcierge-owned:technical-docs', 'Technical Documentation', 'docs.search.v1', 'search_technical_docs'),
)
QUERIES = {'search_technical_docs': 'Kubernetes deployment rollout'}


def main():
    from scripts.apply_category_refresh import open_store
    from agent_market.capability_contracts import run_test
    from agent_market.capability_registry import Registry
    from agent_market.concierge.proxy import McpProxy
    from agent_market.concierge.execution_policy import safe_registered_tool, tools_for
    store, connection = open_store()
    results = []
    try:
        registry, proxy = Registry(store), McpProxy(store)
        for key, name, contract, tool in PAIRS:
            found = store.query('SELECT id FROM resources WHERE key=?', (key,))
            resource = store.resource(found[0]['id']) if found else None
            if (not resource or resource.get('name') != name or not resource.get('active') or resource.get('kind') != 'mcp'
                    or resource.get('price_usdc') or resource.get('auth_observed') or resource.get('auth_declared')):
                results.append({'agent': name, 'ok': False, 'reason': 'not an active public free MCP listing'})
                continue
            spec = next((item for item in tools_for(resource) if item.get('name') == tool), None)
            if not spec or not safe_registered_tool(spec):
                results.append({'agent': name, 'ok': False, 'reason': 'tool is not informational'})
                continue
            if tool == 'search_technical_docs':
                # Execution requires a health record; one real example read establishes it.
                from agent_market.owned_data_agents.docs import check_source
                if not check_source(store, resource['id']):
                    results.append({'agent': name, 'ok': False, 'reason': 'documentation sources unavailable'})
                    continue
            registry.approve(resource, contract, tool)
            arguments = {'query': QUERIES.get(tool) or ('machine learning' if contract == 'docs.search.v1' else 'artificial intelligence'),
                         'language': 'en', 'limit': 3}
            if contract == 'news.search.v1':
                arguments['from_utc'] = (datetime.now(timezone.utc) - timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')

            async def runner(rid, *, tool, arguments, expected_version):
                result = proxy.execute(rid, tool, arguments, public=True)
                return {'execution_succeeded': result.get('ok') is True, 'simulated': False, 'output': result.get('result')}
            checked = asyncio.run(run_test(registry, store.resource(resource['id']), contract, arguments, runner))
            projection = registry.projection(store.resource(resource['id']))
            results.append({'agent': name, 'resource_id': resource['id'], 'contract': contract, 'ok': checked['ok'],
                            'reason': checked.get('reason'),
                            'verified_callable': projection.get('connection_readiness', {}).get('verified_callable'),
                            'contracts': projection.get('capability_contracts')})
    finally:
        store.close()
        connection.close()
    print(json.dumps(results, indent=1))


if __name__ == '__main__':
    main()
