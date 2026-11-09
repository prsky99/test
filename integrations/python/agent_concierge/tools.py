"""Framework tools. Each import is optional: install the matching extra first."""
from __future__ import annotations

from .client import AgentConcierge, MCP_URL

DESCRIPTION = ('Find existing AI agents, MCP servers or x402 APIs for a task. Input: a short task phrase. '
               'Returns up to five candidates with their latest recorded check; checks show what happened when they ran.')


def _run(task: str, client: AgentConcierge | None = None, limit: int = 5) -> str:
    agents = (client or AgentConcierge()).search(task, limit=limit)
    return '\n'.join(a.summary() for a in agents) or 'No listed agent matched this task.'


def langchain_tool(client: AgentConcierge | None = None):
    """A LangChain StructuredTool (pip install "agent-concierge[langchain]")."""
    from langchain_core.tools import StructuredTool
    return StructuredTool.from_function(func=lambda task: _run(task, client), name='find_agents', description=DESCRIPTION)


def crewai_tool(client: AgentConcierge | None = None):
    """A CrewAI tool (pip install "agent-concierge[crewai]")."""
    from crewai.tools import tool

    @tool('find_agents')
    def find_agents(task: str) -> str:
        """Find existing AI agents, MCP servers or x402 APIs for a task, with their latest recorded check."""
        return _run(task, client)
    return find_agents


def openai_agents_tool(client: AgentConcierge | None = None):
    """A function tool for the OpenAI Agents SDK (pip install "agent-concierge[openai-agents]")."""
    from agents import function_tool

    @function_tool
    def find_agents(task: str) -> str:
        """Find existing AI agents, MCP servers or x402 APIs for a task, with their latest recorded check."""
        return _run(task, client)
    return find_agents


def openai_agents_mcp_server():
    """The full Agent Concierge MCP server for the OpenAI Agents SDK (use with `async with`)."""
    from agents.mcp import MCPServerStreamableHttp
    return MCPServerStreamableHttp(name='Agent Concierge', params={'url': MCP_URL}, cache_tools_list=True)
