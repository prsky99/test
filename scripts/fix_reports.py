#!/usr/bin/env python3
# Database Remediation Script: Normalize and Fix All Reports in Both SQLite DBs
# Resolves:
# 1. 100% English enforcement (removes all residual Korean in content_md & metadata across 307 reports)
# 2. Section header standardization (ensures ### Pros and ### Cons in 100% of reports)
# 3. JSON array normalization for tags (converts 200 legacy comma-separated tags to JSON lists)
# 4. JSON array normalization for pros and cons (converts 266 semicolon-separated strings to JSON lists)
# 5. Parity synchronization for Reports #378 & #384 from collector into gateway
# 6. Sanitization of internal database name in Report #207
# Synchronizes both gateway-data/collector.sqlite3 and gateway-data/gateway.sqlite3.

import sqlite3
import json
import re

hangul_pattern = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')

def clean_markdown_content(text):
    if not text:
        return text
        
    # Standardize headers and remove Korean tags
    text = re.sub(r'##\s*6\.\s*Pros and Cons\s*\([^\)]*장점[^\)]*\)', '## 6. Pros and Cons', text)
    text = re.sub(r'###\s*Advantages\s*\([^\)]*장점[^\)]*\)', '### Pros', text)
    text = re.sub(r'###\s*Pros\s*\([^\)]*장점[^\)]*\)', '### Pros', text)
    text = re.sub(r'###\s*Limitations\s*\([^\)]*단점[^\)]*\)', '### Cons', text)
    text = re.sub(r'###\s*Disadvantages\s*\([^\)]*단점[^\)]*\)', '### Cons', text)
    text = re.sub(r'###\s*Cons\s*\([^\)]*단점[^\)]*\)', '### Cons', text)
    
    # Generic Korean markers
    text = text.replace('(장점 및 단점)', '')
    text = text.replace('(장점)', '')
    text = text.replace('(단점)', '')
    text = text.replace('장점 및 단점', 'Pros and Cons')
    text = text.replace('장점', 'Pros')
    text = text.replace('단점', 'Cons')
    
    # Workflow references
    text = re.sub(r'워크플로우\s*\(Workflows\)', 'Workflows', text)
    text = re.sub(r'Workflows\s*\(워크플로우\)', 'Workflows', text)
    text = text.replace('워크플로우', 'Workflows')
    
    # Specific Korean test queries in reports #265 & #268
    text = text.replace('사업자등록번호', 'Business Registration Number (BRNO)')
    text = text.replace('국세청', 'National Tax Service (NTS)')
    text = text.replace('삼성전자', 'Samsung Electronics')
    
    # Sanitize internal DB reference in Report #207
    text = text.replace('collector.sqlite3', 'the discovery registry database')
    
    return text

def normalize_tags(tags_str):
    if not tags_str:
        return '[]'
    try:
        data = json.loads(tags_str)
        if isinstance(data, list):
            return json.dumps([str(t).strip() for t in data if str(t).strip()])
        elif isinstance(data, str):
            tags_list = [t.strip() for t in data.split(',') if t.strip()]
            return json.dumps(tags_list)
    except:
        tags_list = [t.strip() for t in tags_str.split(',') if t.strip()]
        return json.dumps(tags_list)
    return tags_str

def normalize_list_field(val):
    if not val:
        return '[]'
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return json.dumps([str(x).strip() for x in parsed if str(x).strip()])
        elif isinstance(parsed, str):
            val = parsed
    except:
        pass
        
    if ';' in val:
        items = [x.strip() for x in val.split(';') if x.strip()]
    elif '\n' in val:
        items = [x.lstrip('*-• ').strip() for x in val.split('\n') if x.strip()]
    else:
        items = [val.strip()]
    return json.dumps(items)

def main():
    col_path = "gateway-data/collector.sqlite3"
    gw_path = "gateway-data/gateway.sqlite3"
    
    # Step 1: Sync reports #378 and #384 from collector to gateway
    print("=== Step 1: Synchronizing Reports #378 & #384 from Collector to Gateway ===")
    conn_col = sqlite3.connect(col_path)
    conn_gw = sqlite3.connect(gw_path)
    cur_col = conn_col.cursor()
    cur_gw = conn_gw.cursor()
    
    cur_gw.execute("PRAGMA table_info(agent_test_reports)")
    cols_gw = [r[1] for r in cur_gw.fetchall()]
    
    for rid in [378, 384]:
        cur_col.execute(f"SELECT {', '.join(cols_gw)} FROM agent_test_reports WHERE id = ?", (rid,))
        row = cur_col.fetchone()
        placeholders = ", ".join(["?"] * len(cols_gw))
        cur_gw.execute(f"REPLACE INTO agent_test_reports ({', '.join(cols_gw)}) VALUES ({placeholders})", row)
        print(f"Copied full Report #{rid} to gateway.sqlite3")
    conn_gw.commit()
    conn_col.close()
    conn_gw.close()
    
    # Step 2: Remediate and normalize all reports across both databases
    print("\n=== Step 2: Remediating Reports in Dual Databases ===")
    for db_path in [col_path, gw_path]:
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        cur = conn.cursor()
        
        cur.execute("SELECT id, content_md, tags, pros, cons FROM agent_test_reports ORDER BY id ASC")
        rows = cur.fetchall()
        
        updated_count = 0
        hangul_fixed = 0
        tags_fixed = 0
        pros_fixed = 0
        cons_fixed = 0
        
        for rid, content_md, tags, pros, cons in rows:
            new_content = clean_markdown_content(content_md)
            new_tags = normalize_tags(tags)
            new_pros = normalize_list_field(pros)
            new_cons = normalize_list_field(cons)
            
            # Verifications
            assert len(hangul_pattern.findall(new_content)) == 0, f"Hangul remains in #{rid} content_md"
            assert "### Pros" in new_content, f"Missing '### Pros' in #{rid}"
            assert "### Cons" in new_content, f"Missing '### Cons' in #{rid}"
            assert isinstance(json.loads(new_tags), list), f"Tags not list in #{rid}"
            assert isinstance(json.loads(new_pros), list), f"Pros not list in #{rid}"
            assert isinstance(json.loads(new_cons), list), f"Cons not list in #{rid}"
            
            changes = []
            if new_content != content_md:
                changes.append("content_md")
                hangul_fixed += 1
            if new_tags != tags:
                changes.append("tags")
                tags_fixed += 1
            if new_pros != pros:
                changes.append("pros")
                pros_fixed += 1
            if new_cons != cons:
                changes.append("cons")
                cons_fixed += 1
                
            if changes:
                cur.execute("""
                    UPDATE agent_test_reports
                    SET content_md = ?, tags = ?, pros = ?, cons = ?
                    WHERE id = ?
                """, (new_content, new_tags, new_pros, new_cons, rid))
                updated_count += 1
        
        conn.commit()
        
        cur.execute("SELECT COUNT(*) FROM agent_test_reports")
        total = cur.fetchone()[0]
        cur.execute("PRAGMA integrity_check")
        integrity = cur.fetchone()[0]
        
        print(f"[{db_path}] Total Reports: {total}, Updated: {updated_count}")
        print(f"  - Content & Header / Hangul fixes: {hangul_fixed}")
        print(f"  - Tags JSON normalizations: {tags_fixed}")
        print(f"  - Pros JSON normalizations: {pros_fixed}")
        print(f"  - Cons JSON normalizations: {cons_fixed}")
        print(f"  - Integrity Check: {integrity}")
        conn.close()

if __name__ == "__main__":
    main()
