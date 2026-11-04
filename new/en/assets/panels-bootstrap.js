/* Restore inactive panels before the shared operating handlers attach. */
(() => { for (const node of document.querySelectorAll('template[data-inactive-panel]')) node.replaceWith(node.content); })();

/* WebMCP (11-04): when the browser offers navigator.modelContext, an agent working in this page can
   call two read-only catalog tools instead of reading the screen. Nothing runs without that API. */
(() => {
  const context = typeof navigator === "object" ? navigator.modelContext : null;
  if (!context || (typeof context.registerTool !== "function" && typeof context.provideContext !== "function")) return;
  const protocols = ["a2a", "mcp", "x402"];
  const text = value => ({ content: [{ type: "text", text: JSON.stringify(value) }] });
  const read = async (path, init) => {
    const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json", ...(init?.headers || {}) }, ...init });
    if (!response.ok) throw new Error("Request failed with status " + response.status);
    return response.json();
  };
  const tools = [
    {
      name: "search_agent_catalog",
      description: "Search the Agent Concierge catalog of A2A agents, MCP servers and x402 APIs. Read-only; returns listings with health and grade.",
      inputSchema: { type: "object", properties: {
        query: { type: "string", minLength: 2, maxLength: 200, description: "Words describing the capability, e.g. weather forecast" },
        protocol: { type: "string", enum: protocols, description: "Limit results to one protocol" },
        limit: { type: "integer", minimum: 1, maximum: 20, default: 10 } }, required: ["query"] },
      annotations: { readOnlyHint: true },
      async execute({ query, protocol, limit }) {
        const params = new URLSearchParams({ q: String(query || "").slice(0, 200), limit: String(Math.min(Math.max(Number(limit) || 10, 1), 20)) });
        if (protocols.includes(protocol)) params.set("kind", protocol);
        const data = await read("/api/explore?" + params);
        return text({ total: data.total, items: (data.items || []).map(item => ({ id: item.id, name: item.name, protocol: item.kind,
          url: item.url, description: item.description, health: item.health_status, grade: item.eval_grade })) });
      }
    },
    {
      name: "recommend_agents_for_task",
      description: "Recommend up to three checked agents for a task, with connection details. Read-only; it never runs the agent.",
      inputSchema: { type: "object", properties: {
        task: { type: "string", minLength: 3, maxLength: 500, description: "What the agent should do" },
        protocol: { type: "string", enum: protocols } }, required: ["task"] },
      annotations: { readOnlyHint: true },
      async execute({ task, protocol }) {
        const body = { task: String(task || "").slice(0, 500), ...(protocols.includes(protocol) ? { protocol } : {}) };
        return text(await read("/api/agent/v1/discover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
      }
    }
  ];
  try {
    if (typeof context.registerTool === "function") for (const tool of tools) context.registerTool(tool);
    else context.provideContext({ tools });
  } catch (error) { /* A browser that refuses the tools leaves the page unchanged. */ }
})();
