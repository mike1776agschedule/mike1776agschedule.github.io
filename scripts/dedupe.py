#!/usr/bin/env python3
"""
Remove exact duplicate records (same county + normalized org name + date).

Keeps the FIRST occurrence and drops the rest. Useful after roll_forward.py
when rolling a past date into a month that already has the same recurring
meeting.

Usage:
    python scripts/dedupe.py             # rewrites data/records.json
    python scripts/dedupe.py --dry-run   # report only
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
from _common import REPO_ROOT


def main():
    dry = "--dry-run" in sys.argv
    in_path = REPO_ROOT / "data" / "records.json"
    if not in_path.exists():
        sys.exit(f"ERROR: {in_path} not found. Run scripts/decrypt.py first.")

    records = json.loads(in_path.read_text())
    seen = {}
    to_drop = []
    for i, r in enumerate(records):
        norm_org = re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", r["Organization_or_Event_Name"].strip().lower()))
        date_key = r.get("Meeting_or_Event_Date", "").strip()
        if not date_key:
            continue  # don't dedupe blank-date records
        key = (r["County"].strip().lower(), norm_org, date_key)
        if key in seen:
            to_drop.append(i)
        else:
            seen[key] = i

    kept = [r for i, r in enumerate(records) if i not in set(to_drop)]
    print(f"dropped {len(to_drop)} duplicates")
    print(f"records: {len(records)} -> {len(kept)}")

    if to_drop and len(to_drop) <= 50:
        print("\nDropped indices:")
        for i in to_drop:
            r = records[i]
            print(f"  [{i}] {r['Organization_or_Event_Name']} ({r['County']}, {r['Meeting_or_Event_Date']})")

    if dry:
        print("\n(dry run — no files modified)")
        return

    in_path.write_text(json.dumps(kept, indent=2))
    print(f"\nwrote {in_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
