import test from 'node:test';
import assert from 'node:assert/strict';
import { searchAgents } from './index.js';

test('builds a read-only query and parses evidence', async () => {
  let seen;
  const fetchImpl = async (url) => { seen = url; return { ok: true, json: async () => ({ items: [{ id: 7, kind: 'mcp', name: 'Weather', eval_grade: 'A', trial_ok: 1, connection_readiness: { verified_callable: true, evidence_scope: 'execution', verified_at: 1794222288 } }] }) }; };
  const [agent] = await searchAgents('weather forecast', { protocol: 'mcp', checkedOnly: true, limit: 99, fetchImpl });
  assert.match(seen, /kind=mcp/); assert.match(seen, /verified=1/); assert.match(seen, /limit=45/);
  assert.equal(agent.qualityGrade, 'A'); assert.ok(agent.executionCheckedAt.startsWith('2026-11-'));
});

test('rejects an empty task', async () => {
  await assert.rejects(searchAgents('  '), /Describe the task/);
});
