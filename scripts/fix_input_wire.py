#!/usr/bin/env python3
import sqlite3
import json

db_paths = ['gateway-data/collector.sqlite3', 'gateway-data/gateway.sqlite3']

for path in db_paths:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    
    # 1. Fix Report 724
    cur.execute("SELECT input_wire FROM agent_test_reports WHERE id = 724")
    r = cur.fetchone()
    if r and not r[0].startswith('{'):
        new_wire = json.dumps({
            "method": "GET",
            "url": "https://paylyte.ai/v1/data/fema/disasters?state=FL&limit=2",
            "headers": {
                "Host": "paylyte.ai",
                "User-Agent": "A2A-Discovery-Bench/1.0",
                "Accept": "application/json"
            }
        })
        cur.execute("UPDATE agent_test_reports SET input_wire = ? WHERE id = 724", (new_wire,))
        print(f"[{path}] Fixed input_wire for #724")
        
    # 2. Fix Reports 737, 740, 746
    for rid, uuid in [
        (737, "b3152bf7-0038-430d-8925-e2ca6337e96b"),
        (740, "5908ebfe-aee3-4946-9be3-6e64485c5acf"),
        (746, "09fac0f0-a462-4b57-b3b9-d861a1f90b38")
    ]:
        cur.execute("SELECT input_wire FROM agent_test_reports WHERE id = ?", (rid,))
        r = cur.fetchone()
        if r and not r[0].startswith('{'):
            new_wire = json.dumps({
                "method": "GET",
                "url": f"https://centralcity.ai/a2a/{uuid}/.well-known/agent-card.json",
                "headers": {
                    "Host": "centralcity.ai",
                    "User-Agent": "A2A-Discovery-Bench/1.0",
                    "Accept": "application/json"
                }
            })
            cur.execute("UPDATE agent_test_reports SET input_wire = ? WHERE id = ?", (new_wire, rid))
            print(f"[{path}] Fixed input_wire for #{rid}")
            
    # 3. Sanitize Report 447 :8400 string literal
    cur.execute("SELECT content_md FROM agent_test_reports WHERE id = 447")
    r = cur.fetchone()
    if r and ":8400:base" in r[0]:
        new_content = r[0].replace(":8400:base", ":amount_atomic:base")
        cur.execute("UPDATE agent_test_reports SET content_md = ? WHERE id = 447", (new_content,))
        print(f"[{path}] Sanitized :8400 in #447")

    conn.commit()
    conn.close()

print("Input wire and port sanitization complete.")
