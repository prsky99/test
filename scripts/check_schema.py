import sqlite3

conn = sqlite3.connect('gateway-data/gateway.sqlite3')
cur = conn.cursor()
cur.execute('PRAGMA table_info(resources)')
print('resources columns:', [r[1] for r in cur.fetchall()])
cur.execute('PRAGMA table_info(agent_test_reports)')
print('agent_test_reports columns:', [r[1] for r in cur.fetchall()])
conn.close()
