#!/usr/bin/env python3
"""Wait for scheduled batch to trigger at 03:58:54 and finish, then output details."""
import getpass
from pathlib import Path
import os, sys, time, psycopg

LOG_FILE = str(Path(__file__).resolve().parents[1] / 'gateway-data/daemon_report_loop.log')

def main():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Monitoring daemon log for next batch execution...")
    
    conn = psycopg.connect(
        host=str(Path(__file__).resolve().parents[1] / 'gateway-data/postgres18/run'),
        port=55432,
        dbname='agentcon_cutover_20261020_191757',
        user=getpass.getuser()
    )
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM agent_test_reports")
        initial_max_id = cur.fetchone()[0]
    conn.close()
    
    print(f"Initial max report ID before batch: {initial_max_id}")

    start_pos = 0
    if os.path.exists(LOG_FILE):
        start_pos = os.path.getsize(LOG_FILE)

    triggered = False
    finished = False
    timeout = time.time() + 2200  # 36 minutes timeout to comfortably cover daemon sleep (28.5m) + batch run (4m)

    while time.time() < timeout:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(start_pos)
                new_text = f.read()
                if new_text:
                    for line in new_text.splitlines():
                        print(line)
                    start_pos = f.tell()
                    if 'Triggering batch_report_runner.py' in new_text:
                        triggered = True
                    if triggered and ('Batch run finished successfully' in new_text or 'Batch run failed' in new_text):
                        finished = True
                        break
        time.sleep(3)

    if not finished:
        print("Timeout waiting for batch run completion!")
        return 1

    print("\nBatch execution completed! Querying PostgreSQL for new reports...")
    conn = psycopg.connect(
        host=str(Path(__file__).resolve().parents[1] / 'gateway-data/postgres18/run'),
        port=55432,
        dbname='agentcon_cutover_20261020_191757',
        user=getpass.getuser()
    )
    with conn.cursor() as cur:
        cur.execute("""
            SELECT rep.id, rep.resource_id, rep.kind, rep.agent_name, rep.test_method, rep.eval_grade, 
                   rep.status_code, rep.latency_ms, rep.title, to_timestamp(rep.created_at)
            FROM agent_test_reports rep
            WHERE rep.id > %s
            ORDER BY rep.id ASC
        """, (initial_max_id,))
        new_reports = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*), 
                   COUNT(CASE WHEN kind='a2a' THEN 1 END),
                   COUNT(CASE WHEN kind='mcp' THEN 1 END),
                   COUNT(CASE WHEN kind='x402' THEN 1 END)
            FROM agent_test_reports
        """)
        total, a2a_cnt, mcp_cnt, x402_cnt = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*)
            FROM agent_test_reports rep
            JOIN resources r ON r.id = rep.resource_id
            WHERE rep.id > %s
              AND (r.active != 1 OR r.eval_security IN ('quarantine', 'review') OR r.inactive_reason IS NOT NULL)
        """, (initial_max_id,))
        excluded_violations = cur.fetchone()[0]

    conn.close()

    print(f"\n=== NEW REPORTS GENERATED IN THIS BATCH: {len(new_reports)} ===")
    for r in new_reports:
        print(f"ID #{r[0]}: [{r[2].upper()}] {r[3]} | Method: {r[4]} | Grade: {r[5]} | Status: {r[6]} | Latency: {r[7]}ms | Title: {r[8]}")

    print(f"\n=== CUMULATIVE STATUS ===")
    print(f"Total Reports: {total}")
    print(f"  A2A: {a2a_cnt}")
    print(f"  MCP: {mcp_cnt}")
    print(f"  x402: {x402_cnt}")
    print(f"Excluded Target Violations in New Reports: {excluded_violations}")
    assert excluded_violations == 0, "Violation: Excluded agents detected in new reports!"
    return 0

if __name__ == '__main__':
    sys.exit(main())
