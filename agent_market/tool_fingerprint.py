"""Tool definition fingerprint v1, the one definition every team uses (reports/tool-fingerprint-design-2026-11-14).

    tool_fp(tool)    sha256 of the canonical {name, description, inputSchema} of one MCP tool definition
    server_fp(tools) sha256 of the sorted [name, tool_fp] pairs of a server's tool list (order independent)

Only the name, the description and the input schema count (PM 04:3x scope). outputSchema and annotations are watched
separately as risk signals, so a changed annotation does not look like a changed definition. Canonical form is
capability_registry.canonical (sorted keys, no spaces, ASCII escapes), the same form as usage_full_hash.
"""
import hashlib

from .capability_registry import canonical

VERSION = 'fingerprint-v1'


def tool_fp(tool):
    if not isinstance(tool, dict) or not isinstance(tool.get('name'), str):
        raise ValueError('a tool definition with a name is required')
    return hashlib.sha256(canonical({k: tool.get(k) for k in ('name', 'description', 'inputSchema')}).encode()).hexdigest()


def server_fp(tools):
    pairs = sorted((t['name'], tool_fp(t)) for t in tools if isinstance(t, dict) and isinstance(t.get('name'), str))
    return hashlib.sha256(canonical(pairs).encode()).hexdigest()
