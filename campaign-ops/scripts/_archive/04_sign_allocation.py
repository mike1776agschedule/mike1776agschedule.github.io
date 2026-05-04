#!/usr/bin/env python3
"""
Phase 4 — Sign Allocation Plan

Reads `Contacts` and `Precincts` from the master workbook, allocates
2,000 4x8 signs and 4,000 yard signs across RECs (weighted by precinct
priority), and replaces the `Allocation` sheet in the master.

Usage:
    python scripts/04_sign_allocation.py
    python scripts/04_sign_allocation.py --total-4x8 2000 --total-yard 4000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
DEFAULT_TOTAL_4X8 = 2000
DEFAULT_TOTAL_YARD = 4000
MIN_4X8 = 10
MIN_YARD = 20


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 4 — Sign allocation plan -> master workbook.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--total-4x8", type=int, default=DEFAULT_TOTAL_4X8)
    p.add_argument("--total-yard", type=int, default=DEFAULT_TOTAL_YARD)
    p.add_argument("--min-4x8", type=int, default=MIN_4X8,
                   help=f"Minimum 4x8 signs per confirmed REC (default: {MIN_4X8}).")
    p.add_argument("--min-yard", type=int, default=MIN_YARD,
                   help=f"Minimum yard signs per confirmed REC (default: {MIN_YARD}).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import pandas as pd
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master_path = Path(args.master)
    mio.init_master(master_path)

    pri = mio.read_sheet_safe(master_path, "Precincts")
    contacts = mio.read_sheet_safe(master_path, "Contacts")

    if pri.empty:
        print("ERROR: Precincts sheet is empty. run Phase 2 first.", file=sys.stderr)
        return 1
    if contacts.empty:
        print("ERROR: Contacts sheet is empty. run Phase 1 first.", file=sys.stderr)
        return 1

    contacts["County"] = contacts["County"].astype(str).str.strip()
    contacts["REC"] = contacts["REC"].astype(str).str.strip()
    quality_rank = {"Complete": 0, "Partial": 1, "Broken": 2}
    contacts["__qrank__"] = contacts["Quality"].map(quality_rank).fillna(3)
    rec_per_county = (
        contacts.sort_values("__qrank__")
                .drop_duplicates(subset=["County"], keep="first")
                .set_index("County")
    )

    if "County" not in pri.columns:
        print("WARN: Precincts has no 'County' column; treating all precincts as one bucket.",
              file=sys.stderr)
        pri["County"] = "(unknown)"

    pri["County"] = pri["County"].astype(str).str.strip()
    pri["weight"] = 1.0 / pri["priority_score"].fillna(4)

    rec_weight = pri.groupby("County")["weight"].sum().to_frame("rec_weight").reset_index()

    rows = []
    for _, r in rec_weight.iterrows():
        county = r["County"]
        info = rec_per_county.loc[county] if county in rec_per_county.index else None
        rows.append({
            "REC_Name":     info["REC"]   if info is not None else "(no REC mapped)",
            "County":       county,
            "Contact_Name": info["Name"]  if info is not None else "",
            "Phone":        info["Phone"] if info is not None else "",
            "Email":        info["Email"] if info is not None else "",
            "Quality":      info["Quality"] if info is not None else "Broken",
            "rec_weight":   r["rec_weight"],
        })
    plan = pd.DataFrame(rows)

    plan["Confirmed_Y_N"] = plan["Quality"].apply(lambda q: "Y" if q in ("Complete", "Partial") else "N")
    blocked = plan["Quality"] == "Broken"
    plan.loc[blocked, "rec_weight"] = 0.0

    total_weight = plan["rec_weight"].sum()
    if total_weight <= 0:
        print("ERROR: zero total weight — no confirmed RECs to allocate to.", file=sys.stderr)
        return 1

    plan["4x8_qty"]  = (args.total_4x8  * plan["rec_weight"] / total_weight).round().astype(int)
    plan["yard_qty"] = (args.total_yard * plan["rec_weight"] / total_weight).round().astype(int)

    confirmed_mask = plan["Confirmed_Y_N"] == "Y"
    plan.loc[confirmed_mask & (plan["4x8_qty"]  < args.min_4x8),  "4x8_qty"]  = args.min_4x8
    plan.loc[confirmed_mask & (plan["yard_qty"] < args.min_yard), "yard_qty"] = args.min_yard
    plan.loc[~confirmed_mask, ["4x8_qty", "yard_qty"]] = 0

    def reconcile(col: str, target: int) -> None:
        delta = target - int(plan[col].sum())
        if delta == 0:
            return
        idx_order = plan[confirmed_mask].sort_values("rec_weight", ascending=False).index.tolist()
        if not idx_order:
            return
        i = 0
        step = 1 if delta > 0 else -1
        floor = args.min_4x8 if col == "4x8_qty" else args.min_yard
        while delta != 0:
            row = idx_order[i % len(idx_order)]
            new_val = plan.at[row, col] + step
            if new_val >= floor:
                plan.at[row, col] = new_val
                delta -= step
            i += 1
            if i > 10_000:
                break

    reconcile("4x8_qty", args.total_4x8)
    reconcile("yard_qty", args.total_yard)

    plan["Notes"] = plan["Quality"].apply(
        lambda q: "BLOCKED — confirm contact" if q == "Broken" else ""
    )

    plan = plan.sort_values("4x8_qty", ascending=False).reset_index(drop=True)
    cols = ["REC_Name", "County", "Contact_Name", "Phone", "Email", "Quality",
            "4x8_qty", "yard_qty", "Confirmed_Y_N", "Notes"]
    plan_out = plan[cols]

    print("\nAllocation summary:")
    print(f"  RECs total:               {len(plan_out)}")
    print(f"  Confirmed:                {(plan['Confirmed_Y_N'] == 'Y').sum()}")
    print(f"  Blocked (Broken contact): {(plan['Quality'] == 'Broken').sum()}")
    print(f"  4x8 allocated:            {plan_out['4x8_qty'].sum()} / {args.total_4x8}")
    print(f"  Yard allocated:           {plan_out['yard_qty'].sum()} / {args.total_yard}")

    print(f"\nReplacing Allocation sheet in {master_path} ...")
    mio.replace_sheet(master_path, "Allocation", plan_out, quality_color_col="Quality")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
