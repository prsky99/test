#!/usr/bin/env python3
"""Execute safe reclassification of catalog resources to Classifier Version 7."""

import json
import logging
import sqlite3
import sys
import time
from collections import Counter

from agent_market.broker.categories import CATEGORIES, LEGACY_ALIASES
from agent_market.gateway.classify import VERSION as CLASSIFIER_VERSION, classify
from agent_market.gateway.store import extract_tool_search_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reclassify_v7")


def run(db_path: str = "gateway-data/collector.sqlite3") -> None:
    log.info("Connecting to database: %s", db_path)
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")

    row = conn.execute("SELECT value FROM meta WHERE key='classifier_version'").fetchone()
    current_ver = json.loads(row["value"]) if row else None
    log.info("Current DB classifier_version: %s (Target version: %d)", current_ver, CLASSIFIER_VERSION)

    log.info("Loading all resources for reclassification...")
    rows = conn.execute(
        "SELECT id, source, kind, name, description, category, usage_tools FROM resources"
    ).fetchall()
    total = len(rows)
    log.info("Loaded %d resources.", total)

    old_counts = Counter()
    new_counts = Counter()
    updates = []

    for r in rows:
        old_cat = r["category"]
        old_counts[old_cat] += 1

        if r["source"] == "registered":
            new_cat = LEGACY_ALIASES.get(old_cat, old_cat)
        else:
            name = r["name"] or ""
            desc = r["description"] or ""
            text = f"{name} {desc}"
            tool_text = extract_tool_search_text(r["usage_tools"])
            if tool_text:
                text += f" {tool_text}"
            new_cat = classify(text)

        new_counts[new_cat] += 1
        if new_cat != old_cat:
            updates.append((new_cat, r["id"]))

    log.info("Reclassification computed: %d of %d items to update (%.1f%%).",
             len(updates), total, (len(updates) / total * 100) if total else 0)

    # Batch update
    batch_size = 2000
    now_ts = time.time()
    for i in range(0, len(updates), batch_size):
        chunk = updates[i:i + batch_size]
        with conn:
            conn.executemany("UPDATE resources SET category=? WHERE id=?", chunk)
            conn.executemany(
                "INSERT OR REPLACE INTO vec_outbox (resource_id, enqueued_at, reason) VALUES (?, ?, 'reclassified')",
                [(rid, now_ts) for _, rid in chunk]
            )
        log.info("Applied batch %d/%d updates...", min(i + batch_size, len(updates)), len(updates))

    # Clean legacy categories in needs table
    with conn:
        for old, new in LEGACY_ALIASES.items():
            conn.execute("UPDATE needs SET category=? WHERE category=?", (new, old))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('classifier_version', ?)", (json.dumps(CLASSIFIER_VERSION),))

    log.info("Updated meta.classifier_version to %d.", CLASSIFIER_VERSION)

    print("\n" + "=" * 70)
    print(f"{'Category':28} | {'Old Count':>10} | {'New Count':>10} | {'Delta':>10}")
    print("-" * 70)
    all_cats = set(old_counts) | set(new_counts)
    for cat in sorted(all_cats, key=lambda c: new_counts[c], reverse=True):
        old = old_counts[cat]
        new = new_counts[cat]
        diff = new - old
        print(f"{cat:28} | {old:10d} | {new:10d} | {diff:+10d}")
    print("=" * 70)


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "gateway-data/collector.sqlite3"
    run(db)
