# agent-concierge

Find existing AI agents, MCP servers and x402 APIs for a task — with the recorded check behind each result — from Python, LangChain, CrewAI or the OpenAI Agents SDK.

Agent Concierge catalogs about 258,000 public agents and keeps checking them (health checks, read-only trial calls, execution checks). A check records what happened when it ran; it does not guarantee that an agent works now. Discovery is read-only and needs no key.

```bash
pip install agent-concierge
```

```python
from agent_concierge import search_agents

for agent in search_agents("japanese weather forecast", protocol="mcp", checked_only=True):
    print(agent.summary())
```

## Framework tools

```python
from agent_concierge.tools import langchain_tool, crewai_tool, openai_agents_tool, openai_agents_mcp_server

tool = langchain_tool()        # pip install "agent-concierge[langchain]"
tool = crewai_tool()           # pip install "agent-concierge[crewai]"
tool = openai_agents_tool()    # pip install "agent-concierge[openai-agents]"
```

For the full MCP tool set (search, chat, workflows), connect the remote server instead:

```python
from agents import Agent
from agent_concierge.tools import openai_agents_mcp_server

async with openai_agents_mcp_server() as concierge:
    agent = Agent(name="Assistant", mcp_servers=[concierge])
```

Other clients: https://agentconcierge.biz/connect
