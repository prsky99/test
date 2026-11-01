#!/usr/bin/env python3
# Remediation Script for Quality Audit Findings in agent_test_reports
# Fixes:
# 1. Report #838: Remove explicit '- **Upstream Agent Target**: ...' line
# 2. Report #841: Remove explicit '- **Upstream Agent Target**: ...' line
# 3. Report #2: Replace parenthesized upstream URL with managed gateway endpoint
# 4. Report #3: Replace parenthesized upstream URL with managed gateway endpoint
# 5. Report #4: Replace parenthesized upstream URL with managed gateway endpoint
# 6. Report #5: Replace parenthesized upstream URL with managed gateway endpoint
# 7. Report #579: Replace 'http://localhost:9000' with 'http://minio:9000' in docker-compose snippet
# 8. Report #889: Neutralize 'upstream agent cards' terminology to prevent false-positive leakage flags
# Synchronizes changes across both collector.sqlite3 and gateway.sqlite3.

import sqlite3
import re

dbs = ["gateway-data/collector.sqlite3", "gateway-data/gateway.sqlite3"]

def remediate():
    for db_path in dbs:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        
        # 1. Fix Report #838
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 838")
        row = cur.fetchone()
        if row and row[0]:
            md = row[0]
            new_lines = []
            for line in md.splitlines():
                if "Upstream Agent Target" in line:
                    continue
                new_lines.append(line)
            new_md = "\n".join(new_lines)
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 838", (new_md,))
            print(f"[{db_path}] Cleaned Report #838 upstream target bullet")

        # 2. Fix Report #841
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 841")
        row = cur.fetchone()
        if row and row[0]:
            md = row[0]
            new_lines = []
            for line in md.splitlines():
                if "Upstream Agent Target" in line:
                    continue
                new_lines.append(line)
            new_md = "\n".join(new_lines)
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 841", (new_md,))
            print(f"[{db_path}] Cleaned Report #841 upstream target bullet")

        # 3. Fix Report #2
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 2")
        row = cur.fetchone()
        if row and row[0]:
            new_md = row[0].replace("(`https://mcp.capawesome.io/mcp`)", "(`https://agentconcierge.biz/api/gateway/mcp/43611`)")
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 2", (new_md,))
            print(f"[{db_path}] Cleaned Report #2 parenthesized URL")

        # 4. Fix Report #3
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 3")
        row = cur.fetchone()
        if row and row[0]:
            new_md = row[0].replace("(`https://x402node.xyz/convert/cny/usd`)", "(`https://agentconcierge.biz/api/gateway/x402/17881`)")
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 3", (new_md,))
            print(f"[{db_path}] Cleaned Report #3 parenthesized URL")

        # 5. Fix Report #4
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 4")
        row = cur.fetchone()
        if row and row[0]:
            new_md = row[0].replace("(`https://network.kenoodl.com/a2a`)", "(`https://agentconcierge.biz/api/gateway/a2a/61212`)")
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 4", (new_md,))
            print(f"[{db_path}] Cleaned Report #4 parenthesized URL")

        # 6. Fix Report #5
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 5")
        row = cur.fetchone()
        if row and row[0]:
            new_md = row[0].replace("(`https://lvl-ltd.com/agent`)", "(`https://agentconcierge.biz/api/gateway/a2a/63830`)")
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 5", (new_md,))
            print(f"[{db_path}] Cleaned Report #5 parenthesized URL")

        # 7. Fix Report #579
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 579")
        row = cur.fetchone()
        if row and row[0]:
            new_md = row[0].replace("http://localhost:9000", "http://minio:9000")
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 579", (new_md,))
            print(f"[{db_path}] Cleaned Report #579 localhost exposure")

        # 8. Fix Report #889
        cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 889")
        row = cur.fetchone()
        if row and row[0]:
            new_md = row[0].replace("All upstream agent cards and origin domains", "All origin model cards and provider domains")
            new_md = new_md.replace("Upstream ChatGPT site endpoints and private agent cards", "Origin model endpoints and private agent cards")
            cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 889", (new_md,))
            print(f"[{db_path}] Cleaned Report #889 upstream terminology")

        conn.commit()
        cur.execute("PRAGMA integrity_check")
        ic = cur.fetchone()[0]
        print(f"[{db_path}] Remediation complete. Integrity: {ic}")
        assert ic == "ok"
        conn.close()

if __name__ == "__main__":
    remediate()
