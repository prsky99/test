export declare const BASE_URL: string;
export declare const MCP_URL: string;
export interface Agent {
  id: number; name: string; protocol: 'a2a' | 'mcp' | 'x402'; description: string;
  qualityGrade: string | null; healthStatus: string | null; lastHealthCheck: string | null;
  executionCheckedAt: string | null; trialCallOk: boolean; authRequired: boolean; exploreUrl: string;
}
export declare function searchAgents(task: string, options?: {
  protocol?: 'a2a' | 'mcp' | 'x402'; checkedOnly?: boolean; noAuth?: boolean; limit?: number; baseUrl?: string; fetchImpl?: typeof fetch;
}): Promise<Agent[]>;
export declare const mcpServerConfig: { type: 'http'; url: string };
