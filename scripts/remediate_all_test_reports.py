#!/usr/bin/env python3
"""Remediate quality issues across all historical reports in agent_test_reports:
1. Standardize test_method to 5 canonical names
2. Standardize eval_grade ('Grade A' -> 'A', etc.)
3. Eliminate A2A self-contradictions (cons claims no version, table declares version)
4. Backfill MCP descriptions from resources.description (replace false 'no description' text)
5. Clean up broken '[Retired gateway reference]' artifacts
6. Add target status alert banner for down/retired/inactive agents
7. Verify all reports against R1~R8 quality rules
"""
import json, os, re, sys, time, psycopg
sys.path.insert(0, os.path.dirname(__file__))
from report_pipeline_common import (
    lint, normalize_test_method, normalize_eval_grade, english_clean, CANONICAL_TEST_METHODS, CANONICAL_GRADES
)

PG_HOST = '/Users/kingstonelee/workspace/A2A_Discovery/gateway-data/postgres18/run'
PG_PORT = 55432
PG_DB = 'agentcon_cutover_20261020_191757'
PG_USER = 'kingstonelee'


def connect():
    return psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER
    )


def audit_existing(cur):
    """Scan and count quality defects in the current database."""
    stats = {}

    # 1. Total counts
    cur.execute("SELECT count(*) FROM agent_test_reports;")
    stats['total_reports'] = cur.fetchone()[0]

    # 2. Non-canonical test methods
    cur.execute("SELECT count(*) FROM agent_test_reports WHERE NOT (test_method = ANY(%s));", (list(CANONICAL_TEST_METHODS),))
    stats['non_canonical_methods'] = cur.fetchone()[0]

    # 3. Non-canonical eval_grades
    cur.execute("SELECT count(*) FROM agent_test_reports WHERE eval_grade IS NOT NULL AND NOT (eval_grade = ANY(%s));", (list(CANONICAL_GRADES),))
    stats['non_canonical_grades'] = cur.fetchone()[0]

    # 4. A2A contradictions
    cur.execute("""
        SELECT count(*) FROM agent_test_reports
        WHERE cons LIKE '%does not declare a protocol version%'
          AND content_md LIKE '%| Protocol | A2A v%';
    """)
    stats['a2a_contradictions'] = cur.fetchone()[0]

    # 5. MCP false 'no description'
    cur.execute("""
        SELECT count(*)
        FROM agent_test_reports r
        JOIN resources res ON r.resource_id = res.id
        WHERE r.kind = 'mcp'
          AND r.content_md LIKE '%The provider published no description.%'
          AND res.description IS NOT NULL AND length(trim(res.description)) > 0;
    """)
    stats['mcp_false_no_description'] = cur.fetchone()[0]

    # 6. Broken retired gateway references
    cur.execute("""
        SELECT count(*) FROM agent_test_reports
        WHERE content_md LIKE '%[Retired gateway reference]%'
           OR summary LIKE '%[Retired gateway reference]%';
    """)
    stats['retired_gateway_refs'] = cur.fetchone()[0]

    # 7. Reports for down/inactive agents without warning banner
    cur.execute("""
        SELECT count(*)
        FROM agent_test_reports r
        JOIN resources res ON r.resource_id = res.id
        WHERE res.active = 1
          AND res.health_status NOT IN ('healthy', 'reachable')
          AND COALESCE(res.eval_security, '') NOT IN ('quarantine', 'review')
          AND res.inactive_reason IS NULL
          AND r.content_md NOT LIKE '%[!WARNING]%';
    """)
    stats['down_agents_missing_banner'] = cur.fetchone()[0]

    # 8. Reports linked to excluded/inactive/quarantined resources
    cur.execute("""
        SELECT count(*)
        FROM agent_test_reports r
        JOIN resources res ON r.resource_id = res.id
        WHERE res.active != 1
           OR res.eval_security IN ('quarantine', 'review')
           OR res.inactive_reason IS NOT NULL;
    """)
    stats['excluded_agents_with_reports'] = cur.fetchone()[0]

    return stats


def remediate(conn, dry_run=False):
    now = time.time()
    changes = {
        'purged_excluded_reports': 0,
        'test_method_updated': 0,
        'eval_grade_updated': 0,
        'a2a_contradiction_fixed': 0,
        'mcp_description_backfilled': 0,
        'gateway_ref_cleaned': 0,
        'warning_banner_added': 0,
        'total_rows_modified': 0
    }

    with conn.cursor() as cur:
        # 0. Purge any historical reports linked to excluded/quarantined/review/inactive resources
        cur.execute("""
            SELECT r.id, r.resource_id, r.slug
            FROM agent_test_reports r
            JOIN resources res ON r.resource_id = res.id
            WHERE res.active != 1
               OR res.eval_security IN ('quarantine', 'review')
               OR res.inactive_reason IS NOT NULL;
        """)
        to_purge = cur.fetchall()
        changes['purged_excluded_reports'] = len(to_purge)
        if to_purge:
            purge_ids = [p[0] for p in to_purge]
            cur.execute("DELETE FROM test_report_subject_claims WHERE report_id = ANY(%s);", (purge_ids,))
            cur.execute("DELETE FROM agent_test_reports WHERE id = ANY(%s);", (purge_ids,))
            print(f"Purged {len(to_purge)} test reports associated with excluded/quarantined resources.")

        # Fetch all reports along with resource metadata
        cur.execute("""
            SELECT r.id, r.resource_id, r.kind, r.test_method, r.eval_grade,
                   r.summary, r.content_md, r.pros, r.cons,
                   res.description AS res_desc, res.health_status, res.active,
                   r.output_wire, res.eval_security, res.inactive_reason
            FROM agent_test_reports r
            LEFT JOIN resources res ON r.resource_id = res.id
            ORDER BY r.id ASC;
        """)
        rows = cur.fetchall()
        print(f"Loaded {len(rows)} reports for remediation analysis.")

        for row in rows:
            (rid, resource_id, kind, test_method, eval_grade,
             summary, content_md, pros_raw, cons_raw,
             res_desc, health_status, active, output_wire_raw,
             eval_sec, inact_reason) = row

            modified = False
            new_test_method = test_method
            new_eval_grade = eval_grade
            new_summary = summary
            new_content_md = content_md
            new_cons_raw = cons_raw

            # 1. Standardize test_method
            canon_method = normalize_test_method(kind, test_method)
            if test_method != canon_method:
                new_test_method = canon_method
                # Update summary if it contains old method name
                if test_method and test_method in new_summary:
                    new_summary = new_summary.replace(test_method, canon_method)
                changes['test_method_updated'] += 1
                modified = True

            # 2. Standardize eval_grade
            canon_grade = normalize_eval_grade(eval_grade)
            if eval_grade != canon_grade:
                new_eval_grade = canon_grade
                changes['eval_grade_updated'] += 1
                modified = True

            # 3. Fix A2A contradictions
            if kind == 'a2a':
                cons_str = str(cons_raw or '')
                if 'does not declare a protocol version' in cons_str.lower() and '| Protocol | A2A v' in new_content_md:
                    # Check if output_wire actually declared protocolVersion
                    wire = {}
                    if output_wire_raw:
                        try: wire = json.loads(output_wire_raw) if isinstance(output_wire_raw, str) else output_wire_raw
                        except Exception: pass
                    
                    if wire.get('protocolVersion'):
                        # Card DID declare protocolVersion, so remove the contradictory claim from cons
                        try:
                            cons_list = json.loads(cons_raw) if isinstance(cons_raw, str) else list(cons_raw)
                            cons_list = [c for c in cons_list if 'does not declare a protocol version' not in c.lower()]
                            new_cons_raw = json.dumps(cons_list)
                            # Also remove from content_md cons section
                            new_content_md = re.sub(r'-\s*The card does not declare a protocol version\.\n?', '', new_content_md)
                            changes['a2a_contradiction_fixed'] += 1
                            modified = True
                        except Exception:
                            pass
                    else:
                        # Card did NOT declare protocolVersion, so fix table to say A2A (Unspecified)
                        new_content_md = re.sub(r'\|\s*Protocol\s*\|\s*A2A v[0-9\.]+\s*\|', '| Protocol | A2A (Unspecified) |', new_content_md)
                        changes['a2a_contradiction_fixed'] += 1
                        modified = True

            # 4. Backfill MCP descriptions
            if kind == 'mcp' and 'The provider published no description.' in new_content_md:
                clean_desc = english_clean(' '.join(str(res_desc or '').split())[:400])
                if clean_desc:
                    new_content_md = new_content_md.replace(
                        'The provider published no description.',
                        f'Provider description: {clean_desc}'
                    )
                    changes['mcp_description_backfilled'] += 1
                    modified = True

            # 5. Clean up broken retired gateway reference artifacts
            if '[Retired gateway reference]' in new_content_md or '[Retired gateway reference]' in new_summary:
                new_content_md = new_content_md.replace('[Retired gateway reference]', '[Direct endpoint]')
                new_summary = new_summary.replace('[Retired gateway reference]', '[Direct endpoint]')
                changes['gateway_ref_cleaned'] += 1
                modified = True

            # 6. Add target status alert banner for down/retired agents that remain active
            if health_status and health_status not in ('healthy', 'reachable') and active == 1 and str(eval_sec or '').lower() not in ('quarantine', 'review'):
                if '[!WARNING]' not in new_content_md:
                    status_banner = f"> [!WARNING]\n> **Target Status Alert**: As of current verification, this agent status is '{health_status}' (active={active}). Verify endpoint availability prior to integration.\n\n"
                    new_content_md = status_banner + new_content_md
                    changes['warning_banner_added'] += 1
                    modified = True

            # Save updates inside transaction
            if modified:
                changes['total_rows_modified'] += 1
                cur.execute("""
                    UPDATE agent_test_reports
                    SET test_method = %s,
                        eval_grade = %s,
                        summary = %s,
                        content_md = %s,
                        cons = %s,
                        updated_at = %s
                    WHERE id = %s;
                """, (new_test_method, new_eval_grade, new_summary, new_content_md, new_cons_raw, now, rid))

    return changes


def main():
    dry_run = '--dry-run' in sys.argv
    conn = connect()

    print("=== TEST REPORT QUALITY AUDIT (PRE-REMEDIATION) ===")
    pre_stats = audit_existing(conn.cursor())
    for k, v in pre_stats.items():
        print(f"  {k}: {v}")

    print("\nApplying quality remediations across database...")
    changes = remediate(conn, dry_run=dry_run)
    for k, v in changes.items():
        print(f"  {k}: {v}")

    print("\n=== TEST REPORT QUALITY AUDIT (POST-REMEDIATION) ===")
    post_stats = audit_existing(conn.cursor())
    for k, v in post_stats.items():
        print(f"  {k}: {v}")

    # Full R1~R9 lint verification across entire table
    print("\nRunning R1~R9 full table lint audit...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT r.id, r.resource_id, r.kind, r.title, r.summary, r.content_md,
                   r.workflow_recommendation, r.tags, r.eval_grade, r.is_success,
                   r.test_method, r.pros, r.cons, r.executed_at, r.execution_finished_at, r.source,
                   res.active, res.eval_security, res.inactive_reason, res.health_status,
                   r.agent_name, r.agent_url
            FROM agent_test_reports r
            LEFT JOIN resources res ON r.resource_id = res.id;
        """)
        all_reports = cur.fetchall()
        lint_failures = 0
        now = time.time()
        for r in all_reports:
            pros_val = r[11]
            cons_val = r[12]
            try:
                pros_list = json.loads(pros_val) if isinstance(pros_val, str) else list(pros_val or [])
            except Exception:
                pros_list = []
            try:
                cons_list = json.loads(cons_val) if isinstance(cons_val, str) else list(cons_val or [])
            except Exception:
                cons_list = []

            rep_dict = {
                'id': r[0], 'resource_id': r[1], 'kind': r[2], 'title': r[3],
                'summary': r[4], 'content_md': r[5], 'workflow_recommendation': r[6],
                'tags': r[7], 'eval_grade': r[8], 'is_success': r[9],
                'test_method': r[10], 'pros': pros_list, 'cons': cons_list,
                'executed_at': r[13], 'execution_finished_at': r[14],
                'source': r[15],
                'target_active': r[16], 'target_eval_security': r[17],
                'target_inactive_reason': r[18], 'target_health_status': r[19],
                'agent_name': r[20], 'agent_url': r[21]
            }
            issues = lint(rep_dict, now=now)
            if issues:
                lint_failures += 1
                if lint_failures <= 5:
                    print(f"  Report #{r[0]} lint issues: {issues}")

        print(f"Total reports: {len(all_reports)}, Lint failures: {lint_failures}")
        assert lint_failures == 0, f"Quality audit failed: {lint_failures} reports have policy violations!"

    if dry_run:
        print("\n[Dry run] Rolling back database transaction. No changes committed to disk.")
        conn.rollback()
    else:
        print("\n[Production] Committing all quality remediations to database...")
        conn.commit()

    conn.close()
    print("\nAll quality improvements verified successfully!")


if __name__ == '__main__':
    main()
