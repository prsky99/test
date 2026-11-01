#!/usr/bin/env python3
import sqlite3
import re
import json

conn = sqlite3.connect("gateway-data/gateway.sqlite3")
cur = conn.cursor()
cur.execute("""
    SELECT id, resource_id, kind, title, slug, agent_name, agent_url,
           category, eval_grade, eval_score, status_code, latency_ms,
           is_success, test_method, tool_name, input_wire, output_wire,
           summary, content_md, pros, cons, workflow_recommendation,
           tags, author, created_at, updated_at
    FROM agent_test_reports
    ORDER BY id ASC
""")
rows = cur.fetchall()

hangul_re = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
upstream_bullet_re = re.compile(r"^\s*[-*]\s+\*\*Upstream.*Target", re.I)
upstream_binding_re = re.compile(r"^\s*[-*]\s+\*\*Upstream.*Binding", re.I)
localhost_re = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])", re.I)
intro_paren_url_re = re.compile(r"\(\s*`?(https?://(?!agentconcierge\.biz)[^\s`\"\')]+)`?\s*\)")

whitelisted_domains = [
    "agentconcierge.biz", "github.com", "eips.ethereum.org",
    "json-schema.org", "w3.org", "orcid.org", "doi.org",
    "nist.gov", "cve.mitre.org", "python.org", "golang.org",
    "rust-lang.org", "npmjs.com", "pypi.org", "wikipedia.org",
    "example.com", "base.org", "ethereum.org", "solana.com",
    "polygonscan.com", "basescan.org", "etherscan.io", "arbiscan.io"
]

upstream_bullets = []
localhost_leaks = []
intro_paren_urls = []
hangul_leaks = []
missing_pros_cons = []
invalid_agent_urls = []
invalid_json = []

for r in rows:
    rid = r[0]
    res_id = r[1]
    kind = r[2]
    title = r[3]
    agent_url = r[6]
    content_md = r[18]
    pros = r[19]
    cons = r[20]
    tags = r[22]
    
    # 1. Hangul
    for idx, col_val in enumerate(r):
        if isinstance(col_val, str) and hangul_re.search(col_val):
            hangul_leaks.append((rid, idx))
            
    # 2. Agent URL
    if not agent_url or not agent_url.startswith("https://agentconcierge.biz/api/gateway/"):
        invalid_agent_urls.append((rid, agent_url))
        
    # 3. Content MD
    if content_md:
        if "### Pros" not in content_md or "### Cons" not in content_md:
            missing_pros_cons.append(rid)
        for line in content_md.splitlines():
            if upstream_bullet_re.search(line) or upstream_binding_re.search(line):
                upstream_bullets.append((rid, line.strip()))
            if localhost_re.search(line):
                localhost_leaks.append((rid, line.strip()))
                
        # Check intro paren url
        m = intro_paren_url_re.search(content_md)
        if m:
            clean_url = m.group(1).rstrip(".,;:\"')")
            if not any(w in clean_url for w in whitelisted_domains):
                intro_paren_urls.append((rid, clean_url))
                
    # 4. JSON
    for jn, jv in [("pros", pros), ("cons", cons), ("tags", tags)]:
        try:
            p = json.loads(jv)
            if not isinstance(p, list) or len(p) == 0:
                invalid_json.append((rid, jn, "empty or non-list"))
        except Exception as e:
            invalid_json.append((rid, jn, str(e)))

conn.close()

print(f"=== Quality Audit Results across {len(rows)} Reports ===")
print(f"1. Hangul violations: {len(hangul_leaks)}")
print(f"2. Invalid agent_url values: {len(invalid_agent_urls)}")
print(f"3. Reports missing ### Pros or ### Cons: {len(missing_pros_cons)}")
print(f"4. Invalid JSON fields (pros, cons, tags): {len(invalid_json)}")
print(f"5. Explicit Upstream Target bullets: {len(upstream_bullets)}")
for item in upstream_bullets:
    print(f"   - Report #{item[0]}: {item[1]}")
print(f"6. Localhost / Internal IP exposures: {len(localhost_leaks)}")
for item in localhost_leaks:
    print(f"   - Report #{item[0]}: {item[1]}")
print(f"7. Raw parenthesized upstream target URLs in overview: {len(intro_paren_urls)}")
for item in intro_paren_urls:
    print(f"   - Report #{item[0]}: {item[1]}")
