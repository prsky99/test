"""PM 11-18: the official MCP Registry entry and the server version move together."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_registry_entry_carries_the_server_version_and_the_approved_description():
    """PM 11-18 19:3x: the official Registry entry 1.2.0 says what the server does in the approved words (82 characters, no gate claim),
    and its version is the serverInfo version the MCP endpoint reports; they move together (README section 4)."""
    from agent_market.concierge.front import MCP_SERVER_VERSION
    path = ROOT/'deploy/mcp-registry/server.json'
    if not path.exists():
        pytest.skip('release copies do not carry deploy/mcp-registry')
    data = json.loads(path.read_text())
    assert data['version'] == MCP_SERVER_VERSION == '1.2.0'
    assert data['description'] == 'Find AI agents for a task; run workflows built from agents we tested, in one call.'
    assert len(data['description']) <= 100 and 'x402' not in data['description'] and 'verified' not in data['description'].lower()
