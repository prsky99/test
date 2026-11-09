# Agent Concierge plugin for Claude Code

Adds the Agent Concierge remote MCP server and a `find-agent` skill, so Claude Code can look for an existing agent or MCP server before building one.

```bash
claude plugin marketplace add https://agentconcierge.biz/claude-plugins/marketplace.json
claude plugin install agent-concierge@agent-concierge
```

Without the plugin: `claude mcp add --transport http agent-concierge https://agentconcierge.biz/mcp`
