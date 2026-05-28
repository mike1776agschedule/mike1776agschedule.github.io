#!/usr/bin/env python3
"""
Decrypt the dashboard data to a JSON file for editing/auditing.

Usage:
    export FL_AG_PIN=040476
    python scripts/decrypt.py                  # writes to data/records.json
    python scripts/decrypt.py custom_path.json # writes to a custom path
"""
import json, sys
from pathlib import Path
from _common import HTML_FILES, REPO_ROOT, get_pin, decrypt_records

def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "data" / "records.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = decrypt_records(HTML_FILES[0], get_pin())
    out_path.write_text(json.dumps(records, indent=2))
    print(f"decrypted {len(records)} records -> {out_path.relative_to(REPO_ROOT)}")

if __name__ == "__main__":
    main()
