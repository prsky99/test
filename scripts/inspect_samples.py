#!/usr/bin/env python3
import sqlite3
import json

conn_col = sqlite3.connect('gateway-data/collector.sqlite3')
conn_gw = sqlite3.connect('gateway-data/gateway.sqlite3')

cur_col = conn_col.cursor()
cur_gw = conn_gw.cursor()

print("=== INSPECTING REPORTS 378 & 384 DIFF ===")
for rid in [378, 384]:
    cur_col.execute("SELECT content_md, pros, cons, tags FROM agent_test_reports WHERE id = ?", (rid,))
    col_data = cur_col.fetchone()
    cur_gw.execute("SELECT content_md, pros, cons, tags FROM agent_test_reports WHERE id = ?", (rid,))
    gw_data = cur_gw.fetchone()
    print(f"Report #{rid} in Collector:")
    print(f"  Pros: {col_data[1]}")
    print(f"  Cons: {col_data[2]}")
    print(f"Report #{rid} in Gateway:")
    print(f"  Pros: {gw_data[1]}")
    print(f"  Cons: {gw_data[2]}")
    print(f"  Content length diff: len(col)={len(col_data[0])}, len(gw)={len(gw_data[0])}")

print("\n=== INSPECTING KOREAN IN REPORT 36, 54 ===")
for rid in [36, 54]:
    cur_col.execute("SELECT title, content_md FROM agent_test_reports WHERE id = ?", (rid,))
    r = cur_col.fetchone()
    print(f"--- Report #{rid} ({r[0]}) ---")
    lines = [line for line in r[1].split("\n") if any(ord(c) >= 0xac00 and ord(c) <= 0xd7af for c in line)]
    print(f"Total lines with Korean: {len(lines)}")
    for l in lines[:5]:
        print("  KR line:", l[:100])

print("\n=== INSPECTING MISSING PROS/CONS IN REPORT 87, 88 ===")
for rid in [87, 88]:
    cur_col.execute("SELECT title, content_md, pros, cons FROM agent_test_reports WHERE id = ?", (rid,))
    r = cur_col.fetchone()
    print(f"--- Report #{rid} ({r[0]}) ---")
    print(f"Pros field: {r[2]}")
    print(f"Cons field: {r[3]}")
    # print last 10 lines of content_md
    print("End of content_md:")
    for l in r[1].split("\n")[-15:]:
        print("  ", l)

conn_col.close()
conn_gw.close()
