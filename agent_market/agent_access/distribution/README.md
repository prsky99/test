# Agent Concierge remote connection

These files are submission drafts, not proof of a published package, registered
namespace, approved plugin or service-level agreement. Validate the target
registry's current schema and the selected client's configuration before use.
No npm/PyPI launcher is required for a client supporting remote HTTP MCP.

Connect to `https://agentconcierge.biz/mcp/compact` after operating rollout.
The stable tools are `discover`, `describe`, `execute`, `resume`, and `report`.
The established `/mcp` interface remains available.
The small REST schema is `/api/agent/v1/openapi.json`. It reuses the app's
public routes and the same closed discovery/report input contracts.

Preserve the returned `Mcp-Session-Id` in transport. Never copy it into prompts,
query strings, screenshots, logs, or source control. Discovery and preparation
do not authorize execution. Review current evidence and use a separate,
customer-approved single-use grant for a prepared informational task.
Default discovery prefers A2A and then MCP; x402 needs an explicit choice.

For Python, use `agent_market.agent_access.client.DiscoveryClient`. It supports
bounded GET backoff and never automatically retries an execution POST.
No model or billing credential is required for discovery. Host authentication
and workspace permissions remain independent of the visitor session.

Before an OpenAI submission, review the current remote MCP plugin submission
requirements and complete the operator's account/namespace verification and
review. This draft does not add `ai-plugin.json` or claim automatic approval.
