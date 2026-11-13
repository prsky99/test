#!/usr/bin/env python3
"""Run one batch of 30 probed reports (15 A2A + 15 MCP, x402 excluded) safely via admin session."""
import fcntl, hashlib, os, secrets, subprocess, sys, time, psycopg

LOCK_PATH = '/tmp/agentcon_batch_runner.lock'

def main():
    lock_file = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Another batch runner process is currently active. Exiting cleanly.")
        return 0

    conn = psycopg.connect(
        host='/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/postgres18/run',
        port=55432,
        dbname='agentcon_cutover_20261020_191757',
        user='kingstonelee'
    )
    with conn.cursor() as cur:
        cur.execute("SELECT id, username, role, name FROM admin_users WHERE username=%s AND active=1", ('sadmin',))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("sadmin user not found")
        uid, uname, role, name = row
        tok = secrets.token_hex(32)
        ref = 'sha256:' + hashlib.sha256(tok.encode()).hexdigest()
        now = time.time()
        cur.execute(
            "INSERT INTO admin_sessions (token, user_id, username, role, name, created_at, expires_at, ip, user_agent) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (ref, uid, uname, role, name, now, now + 3600, '127.0.0.1', 'AgentConcierge-ScheduledRunner/1.0')
        )
    conn.commit()
    conn.close()

    batch_id = int(time.time())
    folder = f'/Users/kingstonelee/.gemini/antigravity/brain/c483b1b9-b552-4e83-b78d-d6f36bf0128d/scratch/scheduled_batch_{batch_id}'
    # PM 11-14 06:1x: pearl candidates first, 30 a day (MCP 25 + A2A 5), per-provider limits (scripts/pearl_batch.py).
    env = dict(os.environ, ADMIN_SESSION_TOKEN=tok, REPORT_KINDS='a2a,mcp', PEARL_BATCH='1', REPORT_PER_KIND='mcp=25,a2a=5')
    env.update({
        'APPLICATION_STORE_BACKEND': 'postgresql',
        'APPLICATION_POSTGRES_DSN_FILE': '/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/postgres18/application.dsn',
        'APPLICATION_WORKFLOW_KEY_FILE': '/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/collector.sqlite3.updates-key',
    })

    try:
        # Step 1: Classify and quarantine agents against security, spam, and promotion policies
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Step 1: Classifying catalog agents against security, advertising, and promotion policies...")
        subprocess.run([sys.executable, 'scripts/classify_and_quarantine_agents.py'], env=env, check=True)

        # Step 2: Audit and remediate existing test reports
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Step 2: Running full table report quality remediation audit...")
        subprocess.run([sys.executable, 'scripts/remediate_all_test_reports.py'], env=env, check=True)

        # Step 3: Probe clean candidates and draft reports
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Step 3: Starting probed report draft generation for {folder}...")
        subprocess.run([sys.executable, 'scripts/build_probed_report_drafts.py', '15', folder], env=env, check=True)

        # Step 4: Submit verified drafts
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Step 4: Submitting verified drafts to catalog...")
        subprocess.run([sys.executable, 'scripts/submit_report_drafts.py', folder], env=env, check=True)

        # Step 5: Post-submission AQEF-30 quality verification and remediation
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Step 5: Verifying post-submission AQEF-30 report quality...")
        subprocess.run([sys.executable, 'scripts/remediate_all_test_reports.py'], env=env, check=True)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Batch {batch_id} completed successfully.")
    finally:
        c2 = psycopg.connect(
            host='/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/postgres18/run',
            port=55432,
            dbname='agentcon_cutover_20261020_191757',
            user='kingstonelee'
        )
        with c2.cursor() as cur:
            cur.execute("DELETE FROM admin_sessions WHERE token=%s", (ref,))
        c2.commit()
        c2.close()

if __name__ == '__main__':
    main()
