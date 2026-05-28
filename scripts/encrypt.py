#!/usr/bin/env python3
"""
Encrypt a JSON records file back into the dashboard HTML.

Reads JSON, normalizes schema, encrypts with fresh salt/IV, and writes the new
encrypted block into BOTH index.html and campaign_schedule_outreach.html.

Usage:
    export FL_AG_PIN=040476
    python scripts/encrypt.py                  # reads data/records.json
    python scripts/encrypt.py custom_path.json # reads from a custom path
"""
import json, sys
from pathlib import Path
from _common import HTML_FILES, REPO_ROOT, SCHEMA, get_pin, encrypt_records, replace_encrypted_block

def normalize(records):
    """Ensure every record has exactly the 20 canonical fields in order."""
    normalized = []
    for r in records:
        out = {}
        for k in SCHEMA:
            val = r.get(k, 0 if k == "Priority_Tier" else "")
            out[k] = val
        normalized.append(out)
    return normalized

def main():
    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "data" / "records.json"
    if not in_path.exists():
        sys.exit(f"ERROR: input file not found: {in_path}")
    records = json.loads(in_path.read_text())
    records = normalize(records)
    block = encrypt_records(records, get_pin())
    for html in HTML_FILES:
        replace_encrypted_block(html, block)
        print(f"updated {html.relative_to(REPO_ROOT)} ({html.stat().st_size:,} bytes)")
    print(f"encrypted {len(records)} records into {len(HTML_FILES)} HTML files")

if __name__ == "__main__":
    main()
