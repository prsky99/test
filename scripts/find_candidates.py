import sqlite3

conn = sqlite3.connect('gateway-data/collector.sqlite3')
cur = conn.cursor()

# Get already tested IDs
cur.execute('SELECT kind, resource_id FROM agent_test_reports')
tested = set((str(r[0]), str(r[1])) for r in cur.fetchall())

# Check staged in batches 303, 304, 305, 306
staged = {
    ('x402', '109626'), ('a2a', '61343'), ('mcp', '113736'), # 303
    ('x402', '109623'), ('a2a', '87531'), ('mcp', '84736'), # 304
    ('x402', '109619'), ('a2a', '65425'), ('mcp', '58183'), # 305
    ('x402', '109611'), ('a2a', '61103'), ('mcp', '47825'), # 306
}

for item in staged:
    tested.add(item)

print('Total tested + staged:', len(tested))

for kind in ['x402', 'a2a', 'mcp']:
    cur.execute(f'''
        SELECT id, name, eval_grade, eval_score, health_status, category, description
        FROM resources
        WHERE kind = ? AND eval_grade IN ('A', 'B') AND health_status IN ('healthy', 'reachable')
        ORDER BY eval_score DESC
    ''', (kind,))
    cands = [r for r in cur.fetchall() if (kind, str(r[0])) not in tested]
    print(f'Un-tested {kind} A/B reachable/healthy candidates: {len(cands)}')
    for r in cands[:5]:
        print(f'  {kind}: ID={r[0]}, Name={r[1]}, Grade={r[2]}, Score={r[3]}, Cat={r[5]}')
