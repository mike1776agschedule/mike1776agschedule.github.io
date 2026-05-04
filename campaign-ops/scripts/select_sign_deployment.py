#!/usr/bin/env python3
"""
Select the actual 2,000 sign deployment plan from the (POC-enriched) candidate
pool, plus a replacement bench for refusal recovery. Writes to a new sheet
`Sign_Deployment_Plan`.

Per-county allocation = (county Suggested 4x8 Goal / 367) * 2000, rounded.
Plus a per-county replacement bench of ~25% of the primary count for refusals.

Composite score (higher = pick first):
  + 10 * tier_multiplier (A=1.0, B=0.8, C=0.6, D=0.5)
  + Score (from Sign_Location_Candidates, already category-weighted)
  + 3 if has verified phone, +1 if has verified email
  - 5 if Name suggests still-chain residual (defensive)

Usage:
    python scripts/select_sign_deployment.py
    python scripts/select_sign_deployment.py --primary-total 2000
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
DEFAULT_PRIMARY = 2000
REPLACEMENT_RATIO = 0.25
TIER_MULT = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.5}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Select 2000 primary + ~500 replacement sign sites.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--primary-total", type=int, default=DEFAULT_PRIMARY,
                   help=f"Total primary sites to select (default: {DEFAULT_PRIMARY}).")
    p.add_argument("--replacement-ratio", type=float, default=REPLACEMENT_RATIO,
                   help=f"Replacement bench size as fraction of primary (default: {REPLACEMENT_RATIO}).")
    p.add_argument("--min-per-county", type=int, default=4,
                   help="Floor primary picks per county (default: 4).")
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

    master = Path(args.master)
    if not master.exists():
        print(f"ERROR: master not found: {master}", file=sys.stderr)
        return 1

    slc = mio.read_sheet_safe(master, "Sign_Location_Candidates")
    cm = mio.read_sheet_safe(master, "County_Master")
    if slc.empty or cm.empty:
        print("ERROR: missing Sign_Location_Candidates or County_Master.", file=sys.stderr)
        return 1

    cm["County"] = cm["County"].astype(str).str.strip()
    cm["Suggested 4x8 Goal"] = pd.to_numeric(cm["Suggested 4x8 Goal"], errors="coerce").fillna(0)
    total_goal = float(cm["Suggested 4x8 Goal"].sum())
    if total_goal <= 0:
        print("ERROR: Suggested 4x8 Goal sums to zero.", file=sys.stderr)
        return 1
    scale = args.primary_total / total_goal
    print(f"Per-county primary allocation = Suggested 4x8 Goal * {scale:.2f} (target {args.primary_total})")

    # Per-county quotas
    cm["__primary__"] = (cm["Suggested 4x8 Goal"] * scale).apply(math.ceil).clip(lower=args.min_per_county).astype(int)
    cm["__replacement__"] = (cm["__primary__"] * args.replacement_ratio).apply(math.ceil).astype(int)

    # Compute composite score on candidates
    slc = slc.copy()
    slc["County"] = slc["County"].astype(str).str.strip()
    slc["Tier"] = slc["Tier"].astype(str).str.upper().str.strip()
    slc["Score"] = pd.to_numeric(slc["Score"], errors="coerce").fillna(0)

    # Name quality filter — reject placeholder / nonsense names that snuck through
    # OSM (single letters, digits-only, two-letter codes like "BP" / "A1", parenthetical
    # fallbacks like "intersection (see Maps_Link)", raw OSM tag leaks like
    # "traffic_signals on E").
    import re as _re
    name_strip = slc["Name"].fillna("").astype(str).str.strip()
    name_lower = name_strip.str.lower()
    bad_name = (
        # Single letter (A, B, C, ...)
        name_strip.str.match(r"^[A-Za-z]$")
        # Single digit / pure number (3, 4a, 5b)
        | name_strip.str.match(r"^\d+[a-z]?$", case=False)
        # Two-letter all-caps placeholders (BP, AA, 1A, etc — likely petroleum or grid markers)
        | name_strip.str.match(r"^[A-Z0-9]{1,2}$")
        # Names that are pure fallbacks
        | name_lower.str.contains(r"\(no name\)|\(see maps_link\)|\(highway corridor\)", regex=True)
        # Raw OSM tag leaks — names starting with snake_case OSM tag values
        | name_lower.str.match(r"^(traffic_signals|stop|motorway_junction|fuel|fast_food)\b")
        # Empty
        | (name_strip == "")
    )
    n_bad = int(bad_name.sum())
    if n_bad:
        print(f"Filtered {n_bad} candidates with placeholder/nonsense names "
              f"(A, B, C, D, single digits, 'BP', etc).")
        slc = slc[~bad_name].copy()

    def composite(row):
        s = float(row["Score"])
        tier_m = TIER_MULT.get(row["Tier"], 0.5)
        s += 10 * tier_m
        phone = str(row.get("Phone") or "").strip()
        email = str(row.get("Email") or "").strip()
        if phone:
            s += 3
        if email:
            s += 1
        # Highway corridor visibility boost
        hwy_flag = row.get("Highway_Adjacent", False)
        try:
            hwy = (hwy_flag.strip().lower() in ("true", "1", "yes")
                   if isinstance(hwy_flag, str) else bool(hwy_flag))
        except Exception:
            hwy = False
        if hwy:
            s += 5
        # AADT-based traffic boost: log10-scaled.
        # 1k AADT = +0, 10k = +2, 50k = +3.4, 100k = +4, 200k = +4.6
        try:
            aadt = float(row.get("AADT") or 0)
        except (TypeError, ValueError):
            aadt = 0.0
        if aadt >= 1000:
            s += 2.0 * math.log10(aadt / 1000.0)
        return s

    slc["Composite_Score"] = slc.apply(composite, axis=1)

    # Per-county selection
    primary_rows = []
    replacement_rows = []

    quotas = cm.set_index("County")[["__primary__", "__replacement__"]].to_dict(orient="index")

    for county, group in slc.groupby("County"):
        q = quotas.get(county, {"__primary__": args.min_per_county, "__replacement__": 1})
        n_primary = q["__primary__"]
        n_replace = q["__replacement__"]

        # Sort: composite desc; ties broken by Type preference (commercial first, then agri_civic, then intersection)
        type_order = {"commercial": 0, "agri_civic": 1, "intersection": 2}
        sorted_group = group.assign(__type_pref__=group["Type"].map(type_order).fillna(3)).sort_values(
            ["Composite_Score", "__type_pref__"], ascending=[False, True]
        ).drop(columns="__type_pref__")

        prim = sorted_group.head(n_primary).copy()
        prim["Plan"] = "primary"
        prim["Rank_in_County"] = range(1, len(prim) + 1)
        primary_rows.append(prim)

        repl = sorted_group.iloc[n_primary:n_primary + n_replace].copy()
        repl["Plan"] = "replacement"
        repl["Rank_in_County"] = range(1, len(repl) + 1)
        replacement_rows.append(repl)

    primary_df = pd.concat(primary_rows, ignore_index=True) if primary_rows else pd.DataFrame()
    replacement_df = pd.concat(replacement_rows, ignore_index=True) if replacement_rows else pd.DataFrame()

    # If under target, fill from replacements (highest composite first)
    deficit = args.primary_total - len(primary_df)
    if deficit > 0 and not replacement_df.empty:
        promoted = replacement_df.sort_values("Composite_Score", ascending=False).head(deficit).copy()
        promoted["Plan"] = "primary"
        replacement_df = replacement_df.drop(promoted.index)
        primary_df = pd.concat([primary_df, promoted], ignore_index=True)

    # If over target, demote lowest composite primaries to replacement
    overage = len(primary_df) - args.primary_total
    if overage > 0:
        primary_df = primary_df.sort_values("Composite_Score", ascending=False).reset_index(drop=True)
        demoted = primary_df.tail(overage).copy()
        demoted["Plan"] = "replacement"
        primary_df = primary_df.head(args.primary_total).reset_index(drop=True)
        replacement_df = pd.concat([replacement_df, demoted], ignore_index=True)

    plan_df = pd.concat([primary_df, replacement_df], ignore_index=True)

    # Final column order
    cols = ["Plan", "Rank_in_County", "Composite_Score",
            "Candidate_ID", "County", "Tier", "Type", "Category",
            "Name", "Address", "Lat", "Lon", "Maps_Link", "Score",
            "Highway_Adjacent", "Nearest_Highway",
            "AADT", "AADT_Year", "AADT_Road", "AADT_Distance_M",
            "Phone", "Phone_Source", "Email", "Email_Source",
            "Website", "Website_Source", "POC_Status",
            "Google_Search_URL", "Yelp_Search_URL", "Sunbiz_Search_URL",
            "OSM_URL", "OSM_Element", "OSM_ID",
            "Field_Status", "Owner_Contact", "Notes"]
    for c in cols:
        if c not in plan_df.columns:
            plan_df[c] = ""
    plan_df = plan_df[cols]

    # Sort: primary first, then by Tier, County, Rank
    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    plan_df = plan_df.assign(
        __plan_order__=plan_df["Plan"].map({"primary": 0, "replacement": 1}),
        __tier_order__=plan_df["Tier"].map(tier_order).fillna(9),
    ).sort_values(
        ["__plan_order__", "__tier_order__", "County", "Rank_in_County"]
    ).drop(columns=["__plan_order__", "__tier_order__"]).reset_index(drop=True)

    n_primary_final = int((plan_df["Plan"] == "primary").sum())
    n_replace_final = int((plan_df["Plan"] == "replacement").sum())
    prim_only = plan_df[plan_df["Plan"] == "primary"]
    has_phone = (prim_only["Phone"].fillna("").astype(str).str.len() > 0).sum()
    has_email = (prim_only["Email"].fillna("").astype(str).str.len() > 0).sum()

    print(f"\nDeployment plan:")
    print(f"  Primary:     {n_primary_final}")
    print(f"  Replacement: {n_replace_final}")
    print(f"  Primary with phone: {has_phone}/{n_primary_final} ({has_phone/max(n_primary_final,1):.0%})")
    print(f"  Primary with email: {has_email}/{n_primary_final} ({has_email/max(n_primary_final,1):.0%})")
    print(f"\nPrimary by Tier:")
    print(plan_df[plan_df["Plan"] == "primary"]["Tier"].value_counts().sort_index().to_string())
    print(f"\nPrimary by Type:")
    print(plan_df[plan_df["Plan"] == "primary"]["Type"].value_counts().to_string())

    print(f"\nWriting Sign_Deployment_Plan to {master} ...")
    mio.replace_sheet(master, "Sign_Deployment_Plan", plan_df,
                      color_col="Plan",
                      color_map={"primary": "D4EDDA", "replacement": "FFF3CD"})
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
