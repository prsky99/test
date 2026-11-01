"""Bounded next-tool suggestions; neither execution approval nor compatibility proof."""

import json
import logging
import re
from typing import Any
from ..gateway.store import Store
from .discovery_state import execution_state, registered_tools
from .execution_policy import safe_registered_tool
from .protocols import search_protocols
from .recommendation_security import public_schema
from .connections import gateway_agent_url

log = logging.getLogger("agent_market.concierge.inertia")

# Cold-start natural tool affinity patterns (when empirical transitions are sparse)
AFFINITY_RULES = {
    "geocode": ["route", "weather", "map", "direction", "places", "timezone"],
    "address": ["route", "distance", "navigate", "weather"],
    "search": ["scrape", "fetch", "read", "extract", "summarize"],
    "browse": ["extract", "summarize", "parse", "save"],
    "balance": ["transfer", "quote", "swap", "price"],
    "token": ["balance", "price", "allowance", "transfer"],
    "sql": ["describe", "query", "export", "analyze"],
    "database": ["table", "schema", "query", "select"],
    "pdf": ["convert", "markdown", "ocr", "extract", "table"],
    "weather": ["forecast", "alerts", "stations", "hourly"],
}


class InertiaGraph:
    def __init__(self, store: Store):
        self.store = store

    def record_transition(self, from_rid: int, from_tool: str, to_rid: int, to_tool: str) -> None:
        """Records a tool transition observed during an agent session."""
        try:
            self.store.record_tool_transition(from_rid, from_tool, to_rid, to_tool)
        except Exception:
            log.exception("Failed to record tool transition %s:%s -> %s:%s", from_rid, from_tool, to_rid, to_tool)

    def predict_next(self, from_rid: int, from_tool: str, limit: int = 2, *, protocol=None, exclude=None) -> list[dict[str, Any]]:
        """Optional metadata errors cannot interrupt a successful discovery or call."""
        if type(limit) is not int or not 1 <= limit <= 2:
            return []
        try:
            return self._predict_next(from_rid, from_tool, limit, protocol, set(exclude or ()))
        except Exception as exc:
            # This optional boundary includes storage failures. Never log provider
            # bodies, credentials or exception messages from untrusted metadata.
            log.warning('Next-tool suggestions unavailable (%s)', type(exc).__name__)
            return []

    def _predict_next(self, from_rid, from_tool, limit, protocol, excluded):
        prefetched: list[dict[str, Any]] = []
        transitions = self.store.get_tool_transitions(from_rid, from_tool, limit=20)
        seen_targets = set()
        states = {}
        allowed = search_protocols(protocol)

        def append(resource, tool, probability, source):
            if (not resource or resource['id'] in excluded or resource.get('kind') not in allowed
                    or not isinstance(tool.get('name'), str)
                    or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', tool['name'])
                    or not safe_registered_tool(tool)):
                return
            if resource['id'] not in states:
                states[resource['id']] = execution_state(self.store, resource)
            if not states[resource['id']]['verified']:
                return
            prefetched.append({'resource_id': resource['id'], 'server_name': resource['name'],
                'url': gateway_agent_url(resource['id'], resource['kind']), 'kind': resource['kind'],
                'tool': public_schema(self._format_schema(tool)), 'probability': probability,
                'source': source, 'follow_up_query': 'Find an agent for ' + tool['name'].replace('_', ' '),
                'revalidate_after_sec': 3600, 'execution_authorized': False,
                'connection_version_id': states[resource['id']]['version_id']})

        for t in transitions:
            to_rid = t["to_resource_id"]
            to_tool_name = t["to_tool"]
            seen_targets.add((to_rid, to_tool_name))
            res = self.store.resource(to_rid)
            if not res:
                continue
            tool = next((t for t in registered_tools(res) if t.get('name') == to_tool_name), None)
            if tool:
                append(res, tool, t['probability'], 'empirical_markov')

        # 2. Cold-start fallback (Intra-server & affinity graph)
        if len(prefetched) < limit:
            current_res = self.store.resource(from_rid)
            if current_res and current_res.get("usage_tools"):
                tools = registered_tools(current_res)
                words = set(re.findall(r'[a-z]+', from_tool.lower()))
                related = {term for key, values in AFFINITY_RULES.items() if key in from_tool.lower() for term in values}
                for t in tools:
                    name = t.get("name")
                    if (isinstance(name, str) and name != from_tool and (from_rid, name) not in seen_targets
                            and (words.intersection(re.findall(r'[a-z]+', name.lower()))
                                 or any(term in name.lower() for term in related))):
                        seen_targets.add((from_rid, name))
                        append(current_res, t, None, 'intra_server_affinity')
                        if len(prefetched) >= limit:
                            break

        prefetched.sort(key=lambda item: allowed.index(item['kind']))
        return prefetched[:limit]

    def _extract_tool_schema(self, res: dict, tool_name: str) -> dict[str, Any] | None:
        raw_tools = registered_tools(res)
        target = next((t for t in raw_tools if t.get("name") == tool_name), None)
        if target:
            return self._format_schema(target)
        return None

    @staticmethod
    def _format_schema(t: dict) -> dict[str, Any]:
        schema = {
            "name": t.get("name"),
            "description": (t.get("description") or "")[:240],
        }
        if "params" in t:
            schema["parameters"] = t["params"]
            schema["inputSchema"] = {"type": "object", "properties": t["params"]}
        elif "inputSchema" in t:
            schema["inputSchema"] = t["inputSchema"]
            if isinstance(t["inputSchema"], dict) and "properties" in t["inputSchema"]:
                schema["parameters"] = t["inputSchema"]["properties"]
        if "required" in t:
            schema["required"] = t["required"]
        return schema

    @staticmethod
    def generate_code_mode_template(steps: list[dict[str, Any]], base_url: str = "https://localhost:443/mcp") -> str:
        """Generates an executable Python script template for batch/sequential tool orchestration (Code Mode)."""
        calls_code = []
        for idx, step in enumerate(steps, 1):
            rid = step.get("resource_id")
            tool_name = step.get("tool", {}).get("name") or step.get("name")
            if type(rid) is not int or rid <= 0 or not isinstance(tool_name, str):
                raise ValueError('A registered resource and tool are required.')
            calls_code.append(f"""    # Step {idx}: review inputs and authorize this call before running.
    res_{idx} = client.post(GATEWAY_URL, json={{
        "jsonrpc": "2.0", "id": {idx}, "method": "tools/call",
        "params": {{"name": "call", "arguments": {{"resource_id": {rid}, "tool": {tool_name!r}, "arguments": {{}}}}}}
    }}).json()
    print("Step {idx} result:", res_{idx}["result"]["structuredContent"]["execution"].get("ok"))""")

        body = "\n\n".join(calls_code)
        base_literal = json.dumps(base_url)
        return f'''# Auto-generated Nexus-A2A Code Mode Pipeline
import httpx

GATEWAY_URL = {base_literal}

def run_pipeline():
    client = httpx.Client(timeout=30.0)
{body}

if __name__ == "__main__":
    run_pipeline()
'''
