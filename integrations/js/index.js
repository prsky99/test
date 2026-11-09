// Read-only client for the Agent Concierge Explore API. Nothing here calls the agents it finds.
export const BASE_URL = 'https://agentconcierge.biz';
export const MCP_URL = `${BASE_URL}/mcp`;

export async function searchAgents(task, { protocol, checkedOnly = false, noAuth = false, limit = 5, baseUrl = BASE_URL, fetchImpl = fetch } = {}) {
  if (!task || !String(task).trim()) throw new Error('Describe the task, for example "weather forecast for Seoul".');
  if (protocol && !['a2a', 'mcp', 'x402'].includes(protocol)) throw new Error('protocol must be a2a, mcp or x402');
  const params = new URLSearchParams({ q: String(task).trim().slice(0, 500), limit: String(Math.max(1, Math.min(limit, 45))) });
  if (protocol) params.set('kind', protocol);
  if (checkedOnly) params.set('verified', '1');
  if (noAuth) params.set('no_auth', '1');
  const response = await fetchImpl(`${baseUrl}/api/explore?${params}`, { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`Agent Concierge returned ${response.status}`);
  const body = await response.json();
  return (body.items || []).map((item) => {
    const r = item.connection_readiness || {};
    return {
      id: item.id, name: item.name, protocol: item.kind, description: item.description || '',
      qualityGrade: item.eval_grade || null, healthStatus: item.health_status || null,
      lastHealthCheck: item.last_check_at ? new Date(item.last_check_at * 1000).toISOString() : null,
      executionCheckedAt: r.verified_callable && r.evidence_scope === 'execution' && r.verified_at ? new Date(r.verified_at * 1000).toISOString() : null,
      trialCallOk: Boolean(item.trial_ok), authRequired: Boolean(item.auth_required),
      exploreUrl: `${baseUrl}/new/en/explore.html#explore?q=${encodeURIComponent(item.name || '')}`,
    };
  });
}

// Settings for clients that take an MCP server entry (Cursor, VS Code, Claude Code .mcp.json).
export const mcpServerConfig = { type: 'http', url: MCP_URL };
