#!/usr/bin/env python3
"""
Single-command cascade: read Settings sheet → re-run every downstream step.

Reads input values from the Settings sheet inside the master workbook, then
executes the full pipeline so a change to TOTAL_4X8_PRIMARY or TOTAL_YARD_SIGNS
propagates everywhere.

Pipeline order:
  1.  allocate_yard_signs.py       --plan-total <TOTAL_YARD_SIGNS>
  2.  select_sign_deployment.py    --primary-total <TOTAL_4X8_PRIMARY>
                                   --replacement-ratio <REPLACEMENT_RATIO>
                                   --min-per-county <MIN_PER_COUNTY_4X8>
  3.  add_storefront_suggestions.py
  4.  seed_operational_sheets.py   --force
  5.  build_action_workbook.py     (preserves field-staff edits)
  6.  build_executive_summary.py
  7.  build_candidate_map.py       --with-heatmap
  8.  refresh_status_map.py
  9.  qc_report.py
  10. refresh_master.py
  11. build_settings_sheet.py      --preserve-existing  (updates Last_Regenerated)

~60-90 seconds total runtime. Skips OSM pulls / phone-enrichment (those are
data-collection runs, not allocation cascades).

Usage:
    python scripts/regenerate_plans.py
    python scripts/regenerate_plans.py --skip-maps          # skip slow map rebuilds
    python scripts/regenerate_plans.py --skip-storefronts   # skip storefront recompute
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Single-command pipeline cascade.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--skip-maps", action="store_true")
    p.add_argument("--skip-storefronts", action="store_true")
    p.add_argument("--skip-qc", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(SCRIPT_DIR))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    if not master.exists():
        print(f"ERROR: master not found: {master}", file=sys.stderr)
        return 1

    settings = mio.read_settings(master)
    print("="*70)
    print("REGENERATE_PLANS — driving values from Settings sheet")
    print("="*70)
    for k, v in settings.items():
        print(f"  {k:25s} {v}")
    print()

    py = sys.executable  # use same venv

    steps: list[tuple[str, list[str]]] = [
        ("allocate_yard_signs",     [py, str(SCRIPT_DIR / "allocate_yard_signs.py"),
                                     "--plan-total", str(settings["TOTAL_YARD_SIGNS"])]),
        ("select_sign_deployment",  [py, str(SCRIPT_DIR / "select_sign_deployment.py"),
                                     "--primary-total",   str(settings["TOTAL_4X8_PRIMARY"]),
                                     "--replacement-ratio", str(settings["REPLACEMENT_RATIO"]),
                                     "--min-per-county",  str(settings["MIN_PER_COUNTY_4X8"])]),
    ]
    if not args.skip_storefronts:
        steps.append(("add_storefront_suggestions",
                      [py, str(SCRIPT_DIR / "add_storefront_suggestions.py")]))
    steps += [
        ("seed_operational_sheets", [py, str(SCRIPT_DIR / "seed_operational_sheets.py"), "--force"]),
        ("build_action_workbook",   [py, str(SCRIPT_DIR / "build_action_workbook.py")]),
        ("build_executive_summary", [py, str(SCRIPT_DIR / "build_executive_summary.py")]),
    ]
    if not args.skip_maps:
        steps += [
            ("build_candidate_map",  [py, str(SCRIPT_DIR / "build_candidate_map.py"), "--with-heatmap"]),
            ("refresh_status_map",   [py, str(SCRIPT_DIR / "refresh_status_map.py")]),
        ]
    if not args.skip_qc:
        steps.append(("qc_report",   [py, str(SCRIPT_DIR / "qc_report.py")]))
    steps += [
        ("refresh_master",          [py, str(SCRIPT_DIR / "refresh_master.py")]),
        ("rebuild_settings_sheet",  [py, str(SCRIPT_DIR / "build_settings_sheet.py"),
                                     "--preserve-existing"]),
    ]

    n_steps = len(steps)
    overall_start = time.time()
    failures = []
    for i, (name, cmd) in enumerate(steps, start=1):
        t0 = time.time()
        print(f"[{i}/{n_steps}] {name} ...", flush=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - t0
        if result.returncode != 0:
            print(f"  ✗ FAILED ({elapsed:.1f}s)")
            tail = (result.stdout + result.stderr).strip().split("\n")[-15:]
            for line in tail:
                print(f"    {line}")
            failures.append(name)
            continue
        # Success — show the last meaningful line
        out_lines = [l for l in result.stdout.split("\n") if l.strip() and "WARN" not in l]
        last = out_lines[-1] if out_lines else "(no output)"
        print(f"  ✓ {elapsed:.1f}s  — {last[:100]}")

    total = time.time() - overall_start
    print()
    print("="*70)
    if failures:
        print(f"REGENERATE FAILED: {len(failures)}/{n_steps} steps failed: {failures}")
        print(f"Total time: {total:.1f}s")
        return 1
    print(f"REGENERATE COMPLETE: {n_steps} steps in {total:.1f}s")
    print("="*70)

    # Final verification snapshot
    try:
        import pandas as pd
        sdp = mio.read_sheet_safe(master, "Sign_Deployment_Plan")
        ysa = mio.read_sheet_safe(master, "Yard_Sign_Allocation")
        n_primary = int((sdp["Plan"] == "primary").sum()) if not sdp.empty else 0
        n_repl = int((sdp["Plan"] == "replacement").sum()) if not sdp.empty else 0
        yard_total = int(ysa["Plan_4000"].fillna(0).sum()) if not ysa.empty else 0
        print(f"\nFinal state:")
        print(f"  4×8 primary:   {n_primary:,}  (target {settings['TOTAL_4X8_PRIMARY']:,})  "
              f"{'✓' if n_primary == settings['TOTAL_4X8_PRIMARY'] else '✗'}")
        print(f"  4×8 replacement: {n_repl:,}")
        print(f"  Yard signs:    {yard_total:,}  (target {settings['TOTAL_YARD_SIGNS']:,})  "
              f"{'✓' if yard_total == settings['TOTAL_YARD_SIGNS'] else '✗'}")
    except Exception as e:
        print(f"WARN: snapshot failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
