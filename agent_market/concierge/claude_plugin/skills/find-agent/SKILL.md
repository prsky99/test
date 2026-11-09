---
name: find-agent
description: Find an existing AI agent, MCP server or x402 API for a task before building one. Use when the user asks for a tool, integration or data source that may already exist as an agent or MCP server.
---

1. Call the `agent-concierge` MCP tool `search` with a short task phrase (for example "japanese weather forecast").
2. Show up to three candidates with their protocol, latest recorded check and its date. Say that a check records what happened when it ran, not that the agent works now.
3. If the user picks one, show its connection details from the result. Do not call another agent until the user asks; calls through `call` or `run_workflow` are separate, user-started steps.
4. If nothing fits, say so and suggest building it, or listing it later at https://agentconcierge.biz/new/en/list-agent.html.
