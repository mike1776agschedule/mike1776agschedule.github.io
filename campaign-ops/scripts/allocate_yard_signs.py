#!/usr/bin/env python3
"""
Per-county yard sign allocation. Writes a new sheet `Yard_Sign_Allocation`
with one row per county and TWO allocation columns side-by-side:

  - Suggested_Yard_Signs_Boss : boss's plan from County_Master (sums to 7,485)
  - Plan_4000                 : re-allocated to a 4,000 total via 50%
                                tier-weight + 50% GOP-voter-weight,
                                with min-floor of 25 per Tier-D county

Also pulls all available Points-of-Contact (chair + delivery + REC general)
from County_Master and enriches missing chair info from the Master Directory
(florida_gop_directory.xlsx) for the 7 counties known to have gaps.

Every row gets a POC_Status_Yard label:
  - chair_complete : chair has both phone AND email
  - delivery_only  : chair lacks phone or email but delivery POC is usable
  - partial        : limited contact info, still has at least one path

Usage:
    python scripts/allocate_yard_signs.py
    python scripts/allocate_yard_signs.py --plan-total 4000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
DEFAULT_DIRECTORY = "data/raw/florida_gop_directory.xlsx"
DEFAULT_PLAN_TOTAL = 4000
TIER_WEIGHT = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0}
TIER_FLOOR = {"A": 100, "B": 60, "C": 40, "D": 25}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Per-REC yard sign allocation with POCs.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--directory", default=DEFAULT_DIRECTORY)
    p.add_argument("--plan-total", type=int, default=DEFAULT_PLAN_TOTAL,
                   help=f"Total yard signs in Plan_4000 (default: {DEFAULT_PLAN_TOTAL}).")
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
    cm = mio.read_sheet_safe(master, "County_Master")
    # Preserve geocoded Drop_Lat / Drop_Lon / Update_Source / Followup_Required
    # / Update_Date from the prior Yard_Sign_Allocation if it exists. These are
    # written by other scripts (geocode_yard_drops.py, apply_rec_updates.py)
    # and must survive a re-allocation cascade.
    prev_ysa = mio.read_sheet_safe(master, "Yard_Sign_Allocation")
    preserved: dict[str, dict] = {}
    if not prev_ysa.empty and "County" in prev_ysa.columns:
        for _, pr in prev_ysa.iterrows():
            county_key = str(pr.get("County") or "").strip()
            if not county_key:
                continue
            preserve_fields = {}
            for col in ("Drop_Lat", "Drop_Lon", "Drop_Geocode_Source",
                        "Drop_Geocoded_Address", "Update_Source", "Update_Date",
                        "Followup_Required"):
                if col in prev_ysa.columns:
                    val = pr.get(col)
                    if val is not None and not (isinstance(val, float) and val != val):
                        preserve_fields[col] = val
            if preserve_fields:
                preserved[county_key] = preserve_fields
    if cm.empty:
        print("ERROR: County_Master is empty.", file=sys.stderr)
        return 1

    cm["County"] = cm["County"].astype(str).str.strip()

    # Director enrichment for missing chair info
    md = pd.DataFrame()
    dpath = Path(args.directory)
    if dpath.exists():
        try:
            md = pd.read_excel(dpath, sheet_name="Master Directory")
            md["County"] = md["County"].astype(str).str.strip()
        except Exception as e:
            print(f"WARN: could not read directory: {e}")
    else:
        print(f"WARN: directory not found at {dpath}; skipping enrichment.")

    rows = []
    for _, c in cm.iterrows():
        county = c["County"]
        tier = str(c.get("Strategic Tier", "")).strip().upper() or "D"
        wave = str(c.get("Yard Sign Drop Priority", "")).strip()

        # Boss numbers
        boss_yard = _to_int(c.get("Suggested Yard Signs"))
        boss_4x8 = _to_int(c.get("Suggested 4x8 Goal"))
        gop_voters = _to_int(c.get("GOP Registered Voters"))
        active_voters = _to_int(c.get("Total Active Voters"))
        gop_share = _to_float(c.get("GOP Share"))

        # POCs from County_Master
        chair = _str(c.get("Chair"))
        chair_email = _str(c.get("Chair Email"))
        chair_phone = _str(c.get("Chair Phone"))
        del_contact = _str(c.get("Primary Delivery Contact"))
        del_phone = _str(c.get("Primary Delivery Phone"))
        del_email = _str(c.get("Primary Delivery Email"))
        rec_email = _str(c.get("REC General Email"))
        rec_website = _str(c.get("REC Website"))
        meeting_loc = _str(c.get("Meeting / Delivery Location"))
        hub = _str(c.get("Recommended Region / Hub"))

        # Directory enrichment for missing chair info
        chair_email_src = "County_Master" if chair_email else ""
        chair_phone_src = "County_Master" if chair_phone else ""
        if not md.empty and (not chair_email or not chair_phone):
            sub = md[(md["County"].str.lower() == county.lower()) &
                     (md.get("Category", pd.Series("", index=md.index)).astype(str)
                      .str.contains("REC Officer", na=False))]
            if not sub.empty:
                # Prefer the row whose Role mentions "Chair"
                chair_rows = sub[sub.get("Role", pd.Series("", index=sub.index)).astype(str)
                                 .str.contains("Chair", case=False, na=False)]
                pick = chair_rows.iloc[0] if not chair_rows.empty else sub.iloc[0]
                if not chair_email:
                    e = _str(pick.get("Email"))
                    if e and "@" in e:
                        chair_email = e
                        chair_email_src = "Directory"
                if not chair_phone:
                    p = _str(pick.get("Phone"))
                    if p:
                        chair_phone = p
                        chair_phone_src = "Directory"
                if not chair:
                    n = _str(pick.get("Name"))
                    if n:
                        chair = n

        # POC status
        if chair_email and chair_phone:
            poc_status = "chair_complete"
        elif chair_email or chair_phone:
            if del_phone or del_email:
                poc_status = "partial_with_delivery"
            else:
                poc_status = "partial"
        elif del_phone or del_email or rec_email:
            poc_status = "delivery_only"
        else:
            poc_status = "MISSING"  # should not happen on this dataset

        prev = preserved.get(county, {})
        # If chair fields were enriched into the prior YSA from agent verification
        # (Update_Source != ""), prefer those over freshly-computed ones — they're
        # the triple-verified versions.
        if prev.get("Update_Source") and prev_ysa is not None and "County" in prev_ysa.columns:
            row_match = prev_ysa[prev_ysa["County"].astype(str).str.strip() == county]
            if not row_match.empty:
                pr = row_match.iloc[0]
                for src_col, var_name in [
                    ("Chair", "chair"), ("Chair_Email", "chair_email"),
                    ("Chair_Phone", "chair_phone"), ("REC_General_Email", "rec_email"),
                    ("REC_Website", "rec_website"),
                ]:
                    pv = pr.get(src_col)
                    if pv and not (isinstance(pv, float) and pv != pv):
                        pv_s = str(pv).strip()
                        if pv_s and pv_s.lower() != "nan":
                            if src_col == "Chair":         chair = pv_s
                            elif src_col == "Chair_Email": chair_email = pv_s
                            elif src_col == "Chair_Phone": chair_phone = pv_s
                            elif src_col == "REC_General_Email": rec_email = pv_s
                            elif src_col == "REC_Website": rec_website = pv_s
            # recompute POC after override
            if chair_email and chair_phone:
                poc_status = "chair_complete"
            elif chair_email or chair_phone:
                poc_status = "partial_with_delivery" if (del_phone or del_email) else "partial"
            elif del_phone or del_email or rec_email:
                poc_status = "delivery_only"
            else:
                poc_status = "MISSING"

        rows.append({
            "County": county,
            "Strategic_Tier": tier,
            "Wave": wave,
            "GOP_Registered_Voters": gop_voters,
            "Total_Active_Voters": active_voters,
            "GOP_Share": gop_share,
            "Suggested_Yard_Signs_Boss": boss_yard,
            "Suggested_4x8_Goal": boss_4x8,
            "Plan_4000": 0,                # filled below
            "Chair": chair,
            "Chair_Email": chair_email,
            "Chair_Email_Source": chair_email_src,
            "Chair_Phone": chair_phone,
            "Chair_Phone_Source": chair_phone_src,
            "Primary_Delivery_Contact": del_contact,
            "Primary_Delivery_Phone": del_phone,
            "Primary_Delivery_Email": del_email,
            "REC_General_Email": rec_email,
            "REC_Website": rec_website,
            "Meeting_Delivery_Location": meeting_loc,
            "Region_Hub": hub,
            # Preserved fields (geocoded coords + audit trail + followup flags)
            "Drop_Lat": prev.get("Drop_Lat"),
            "Drop_Lon": prev.get("Drop_Lon"),
            "Drop_Geocode_Source": prev.get("Drop_Geocode_Source", ""),
            "Drop_Geocoded_Address": prev.get("Drop_Geocoded_Address", ""),
            "Update_Source": prev.get("Update_Source", ""),
            "Update_Date": prev.get("Update_Date", ""),
            "Followup_Required": prev.get("Followup_Required", ""),
            "POC_Status_Yard": poc_status,
        })

    df = pd.DataFrame(rows)

    # ── Plan_4000: 50% tier weight + 50% voter weight, with floors ─────────
    df["__tier_w__"] = df["Strategic_Tier"].map(TIER_WEIGHT).fillna(1.0)
    df["__voter_w__"] = df["GOP_Registered_Voters"].astype(float)
    if df["__voter_w__"].sum() > 0:
        df["__voter_norm__"] = df["__voter_w__"] / df["__voter_w__"].sum()
    else:
        df["__voter_norm__"] = 1.0 / len(df)
    if df["__tier_w__"].sum() > 0:
        df["__tier_norm__"] = df["__tier_w__"] / df["__tier_w__"].sum()
    else:
        df["__tier_norm__"] = 1.0 / len(df)
    df["__share__"] = 0.5 * df["__voter_norm__"] + 0.5 * df["__tier_norm__"]

    # First pass: raw allocation
    df["Plan_4000"] = (df["__share__"] * args.plan_total).round().astype(int)
    # Apply tier floor
    df["__floor__"] = df["Strategic_Tier"].map(TIER_FLOOR).fillna(25).astype(int)
    df["Plan_4000"] = df[["Plan_4000", "__floor__"]].max(axis=1)

    # Reconcile to exact total
    diff = args.plan_total - int(df["Plan_4000"].sum())
    if diff != 0:
        df = df.sort_values("__share__", ascending=(diff < 0)).reset_index(drop=True)
        i = 0
        step = 1 if diff > 0 else -1
        while diff != 0 and i < 100_000:
            row_i = i % len(df)
            new_v = int(df.at[row_i, "Plan_4000"]) + step
            if new_v >= int(df.at[row_i, "__floor__"]):
                df.at[row_i, "Plan_4000"] = new_v
                diff -= step
            i += 1

    # Drop helper cols
    df = df.drop(columns=[c for c in df.columns if c.startswith("__")])

    # Final column order
    cols = ["County", "Strategic_Tier", "Wave",
            "GOP_Registered_Voters", "Total_Active_Voters", "GOP_Share",
            "Suggested_Yard_Signs_Boss", "Plan_4000", "Suggested_4x8_Goal",
            "Chair", "Chair_Email", "Chair_Email_Source",
            "Chair_Phone", "Chair_Phone_Source",
            "Primary_Delivery_Contact", "Primary_Delivery_Phone", "Primary_Delivery_Email",
            "REC_General_Email", "REC_Website", "Meeting_Delivery_Location",
            "Region_Hub", "POC_Status_Yard",
            "Drop_Lat", "Drop_Lon", "Drop_Geocode_Source", "Drop_Geocoded_Address",
            "Update_Source", "Update_Date", "Followup_Required"]
    # Ensure all preserved columns exist (set to None if not in df)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]

    # Sort by Tier then GOP voters desc
    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    df = df.assign(__o__=df["Strategic_Tier"].map(tier_order).fillna(9)).sort_values(
        ["__o__", "GOP_Registered_Voters"], ascending=[True, False]
    ).drop(columns="__o__").reset_index(drop=True)

    print(f"\nYard sign allocation:")
    print(f"  Counties:                {len(df)}")
    print(f"  Suggested_Yard_Signs_Boss: {int(df['Suggested_Yard_Signs_Boss'].sum())} (boss's 7485 plan)")
    print(f"  Plan_4000:                 {int(df['Plan_4000'].sum())}")
    print(f"\nBy Tier (Plan_4000):")
    print(df.groupby("Strategic_Tier")["Plan_4000"].agg(["count", "sum", "mean"]).round(1).to_string())
    print(f"\nPOC status:")
    print(df["POC_Status_Yard"].value_counts().to_string())
    enriched = (df["Chair_Email_Source"] == "Directory").sum() + (df["Chair_Phone_Source"] == "Directory").sum()
    print(f"\nDirectory enrichment: {enriched} chair fields filled from Master Directory")

    print(f"\nWriting Yard_Sign_Allocation to {master} ...")
    mio.replace_sheet(master, "Yard_Sign_Allocation", df,
                      color_col="POC_Status_Yard",
                      color_map={
                          "chair_complete":         "D4EDDA",
                          "partial_with_delivery":  "FFF3CD",
                          "partial":                "FFF3CD",
                          "delivery_only":          "EAF3FB",
                          "MISSING":                "F8D7DA",
                      })
    print("Done.")
    return 0


def _str(v) -> str:
    """Safely stringify a cell value, treating NaN/None as ''."""
    if v is None:
        return ""
    try:
        # pandas NaN check — NaN is float and != itself
        if isinstance(v, float) and v != v:
            return ""
    except Exception:
        pass
    return str(v).strip()


def _to_int(v) -> int:
    try:
        if v is None:
            return 0
        f = float(v)
        if f != f:  # NaN
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def _to_float(v) -> float:
    try:
        if v is None:
            return 0.0
        f = float(v)
        if f != f:
            return 0.0
        return round(f, 4)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    sys.exit(main())
