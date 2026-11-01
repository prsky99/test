#!/usr/bin/env python3
"""Classify and quarantine catalog agents according to security, spam, promotion, and health policies.

This script executes prior to test report drafting in the 30-minute recurring cycle.
It audits the resources catalog, marks policy-violating agents as inactive/quarantined,
and purges any associated test reports to guarantee zero contaminated reports.
"""

import getpass
from pathlib import Path
import argparse
import os
import re
import sys
import time
import psycopg

LEAD_GEN_RE = re.compile(
    r'\b(cold\s+(?:email|outreach|calling|prospecting)|b2b\s+prospecting|b2b\s+lead(?:\s+intelligence|\s+scraping|\s+enrichment|\s+search)?|lead\s+scraping|prospecting\s+and\s+cold|cold\s+call(?:ing)?\s+campaigns?)\b',
    re.I
)

SPAM_RE = re.compile(
    r'\b(launchpad\s+on\s+(?:bsc|solana|bnb)|bonding\s+curve\s+launchpad|memecoin\s+(?:launchpad|calls|pump|shill)|affiliate\s+(?:partners?\s+)?traffic|referral\s+(?:traffic|code\s+injection))\b',
    re.I
)

SECURITY_EXPLOIT_RE = re.compile(
    r'\b(prompt\s+injection\s+exploit|private\s+key\s+extractor|credential\s+harvesting)\b',
    re.I
)

ABUSIVE_RE = re.compile(
    r'\b(fuck|pussy|cunt|blowjob|handjob)\b',
    re.I
)


def is_security_exploit(text: str) -> bool:
    if SECURITY_EXPLOIT_RE.search(text):
        return True
    if 'wallet drainer' in text.lower():
        if not re.search(r'\b(protection|detector|detect|detection|detects|scan|scanner|blacklist|shield|guard|threat|phishing)\b', text, re.I):
            return True
    return False


def classify_agent(name: str, desc: str, health_status: str | None) -> tuple[bool, str | None]:
    text = f"{name or ''} {desc or ''}"
    
    # 1. Abusive or profane content
    if ABUSIVE_RE.search(text):
        return True, "policy_violation_abusive_content"

    # 2. Malicious security exploit
    if is_security_exploit(text):
        return True, "security_quarantine"

    # 3. Commercial lead generation and cold outreach
    if LEAD_GEN_RE.search(text):
        return True, "policy_violation_commercial_lead_gen"

    # 4. Commercial spam, token pump, or affiliate traffic
    if SPAM_RE.search(text):
        return True, "policy_violation_commercial_spam"

    # 5. Persistent retired state
    if health_status in ('retired', 'quarantined'):
        return True, f"unhealthy:{health_status}"

    return False, None


def main():
    parser = argparse.ArgumentParser(description="Classify and quarantine catalog agents against policies.")
    parser.add_argument("--dry-run", action="store_true", help="Perform audit without committing database updates.")
    args = parser.parse_args()

    conn = psycopg.connect(
        host=str(Path(__file__).resolve().parents[1] / 'gateway-data/postgres18/run'),
        port=55432,
        dbname='agentcon_cutover_20261020_191757',
        user=getpass.getuser()
    )

    t0 = time.time()
    print("=== AGENT POLICY CLASSIFICATION & QUARANTINE AUDIT ===")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, name, description, health_status
            FROM resources
            WHERE active = 1
        """)
        active_agents = cur.fetchall()

    print(f"Loaded {len(active_agents)} active catalog resources in {time.time() - t0:.2f}s.")

    to_quarantine: list[tuple[int, str, str]] = []
    category_counts: dict[str, int] = {}

    for r in active_agents:
        rid, name, desc, health = r
        violates, reason = classify_agent(name, desc, health)
        if violates and reason:
            to_quarantine.append((rid, reason, name))
            category_counts[reason] = category_counts.get(reason, 0) + 1

    print("\nPolicy violation classification results:")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} agents")

    if not to_quarantine:
        print("\nAll active resources comply with security, spam, and promotion policies!")
        conn.close()
        return 0

    print(f"\nTotal agents identified for quarantine: {len(to_quarantine)}")

    # Check for any test reports linked to policy violation targets (quarantine/lead_gen/spam/abusive)
    policy_violation_ids = [
        q[0] for q in to_quarantine 
        if not q[1].startswith("unhealthy:")
    ]
    linked_reports = []
    if policy_violation_ids:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, resource_id, agent_name, title
                FROM agent_test_reports
                WHERE resource_id = ANY(%s)
            """, (policy_violation_ids,))
            linked_reports = cur.fetchall()

    print(f"Linked policy-violating test reports to be purged: {len(linked_reports)}")
    for lr in linked_reports[:10]:
        print(f"  Report #{lr[0]} (Agent #{lr[1]}: {lr[2]}): {lr[3]}")

    if args.dry_run:
        print("\n[Dry run] Skipping database modifications. Rolling back.")
        conn.rollback()
        conn.close()
        return 0

    print("\n[Production] Applying quarantine updates and purging linked reports...")
    with conn.cursor() as cur:
        # 1. Update resources to inactive and quarantined
        for rid, reason, _ in to_quarantine:
            cur.execute("""
                UPDATE resources
                SET active = 0,
                    eval_security = CASE 
                        WHEN %s LIKE 'unhealthy:%%' THEN eval_security 
                        ELSE 'quarantine' 
                    END,
                    inactive_reason = %s
                WHERE id = %s
            """, (reason, reason, rid))

        # 2. Delete linked test report subject claims
        if linked_reports:
            report_ids = [lr[0] for lr in linked_reports]
            cur.execute("""
                DELETE FROM test_report_subject_claims
                WHERE report_id = ANY(%s)
            """, (report_ids,))
            deleted_claims = cur.rowcount
            print(f"Deleted {deleted_claims} test_report_subject_claims.")

            # 3. Delete linked agent test reports
            cur.execute("""
                DELETE FROM agent_test_reports
                WHERE id = ANY(%s)
            """, (report_ids,))
            deleted_reports = cur.rowcount
            print(f"Deleted {deleted_reports} agent_test_reports.")

    conn.commit()
    conn.close()
    print("Policy classification and quarantine successfully committed to database!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
