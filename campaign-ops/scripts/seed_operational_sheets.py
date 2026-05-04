#!/usr/bin/env python3
"""
Pre-fill the user-edited operational sheets with seeded work-queue rows so the
campaign starts with a complete, actionable workbook.

Sheets seeded (only if they currently have ZERO real user data — never overwrites):
  - Large_Sign_Locations  ← one row per Sign_Deployment_Plan primary site
  - Yard_Sign_Deliveries  ← one row per REC (67) from Yard_Sign_Allocation
  - Outreach_Log          ← one row per primary 4×8 site (initial call queue)

Idempotent: detects existing user data by checking if any non-template row has
a populated 'County' field. If yes, this script refuses to clobber.

Usage:
    python scripts/seed_operational_sheets.py
    python scripts/seed_operational_sheets.py --force   # overwrite anyway
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"

# ── Status taxonomies (used for Excel dropdown validation + Dashboard rollups) ──
INSTALL_STATUS = [
    "Pending",          # initial state (haven't called yet)
    "Approved",         # owner said yes, ready to install
    "Declined",         # owner said no — drop this site
    "Installed",        # sign physically on the property
    "Removed",          # sign taken down
    "Damaged",
    "Site Issue",       # some problem with the site itself (zoning, etc.)
]
APPROVAL_STATUS = [
    "Pending",
    "Approved",
    "Declined",
    "Awaiting Permit",
    "Permit Denied",
]
DELIVERY_STATUS = [
    "Scheduled",
    "Confirmed",        # REC chair confirmed delivery date
    "In Transit",
    "Delivered",
    "Issue",            # something went wrong (no-show, weather, etc.)
    "Cancelled",
]
OUTREACH_STATUS = [
    "To Call",          # initial state — main work queue
    "Voicemail",        # left voicemail
    "No Answer",        # phone rang out
    "Reached - Pending",# spoke to someone, awaiting their decision
    "Approved",         # got permission
    "Declined",
    "Wrong Number",
    "Do Not Contact",
    "Closed",           # site closed/out of business
]
SIGN_TYPES = ["4x8", "Yard", "Other"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed user-edited operational sheets with work queue.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--force", action="store_true",
                   help="Overwrite even if user data is present (USE WITH CAUTION).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import pandas as pd
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}).", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    sdp = mio.read_sheet_safe(master, "Sign_Deployment_Plan")
    ysa = mio.read_sheet_safe(master, "Yard_Sign_Allocation")
    if sdp.empty or ysa.empty:
        print("ERROR: Sign_Deployment_Plan or Yard_Sign_Allocation is empty.", file=sys.stderr)
        return 1

    today = datetime.now().strftime("%Y-%m-%d")

    # ── 1. Large_Sign_Locations
    print("Seeding Large_Sign_Locations ...")
    existing = mio.read_sheet_safe(master, "Large_Sign_Locations")
    if _has_user_data(existing, "County") and not args.force:
        print(f"  SKIP — {(existing['County'].fillna('').astype(str).str.strip() != '').sum()} "
              f"user rows present. Use --force to overwrite.")
    else:
        primary = sdp[sdp["Plan"] == "primary"].copy()
        rows = []
        for _, r in primary.iterrows():
            aadt_val = _to_int(r.get("AADT"))
            visibility_bits = []
            if _truthy(r.get("Highway_Adjacent")):
                visibility_bits.append(f"Highway: {_str(r.get('Nearest_Highway'))}")
            if aadt_val > 0:
                visibility_bits.append(f"AADT {aadt_val:,}")
            rows.append({
                "County": _str(r.get("County")),
                "City": _city_from_address(_str(r.get("Address"))),
                "Site Name": _str(r.get("Name")),
                "Address": _str(r.get("Address")),
                "Lat": r.get("Lat"),
                "Lon": r.get("Lon"),
                "Maps_Link": _str(r.get("Maps_Link")),
                "Road / Corridor": _str(r.get("Nearest_Highway")),
                "AADT": aadt_val,
                "Visibility Notes": " · ".join(visibility_bits),
                "Landowner / Approver": "",
                "Contact": "",
                "Phone": _str(r.get("Phone")),
                "Email": _str(r.get("Email")),
                "Website": _str(r.get("Website")),
                "Sign Type": "4x8",
                "Size": "4x8",
                "Permit Needed": "TBD",
                "Approval Status": "Pending",
                "Install Status": "Pending",
                "Install Date": "",
                "Removal Date": "",
                "Candidate_ID": _str(r.get("Candidate_ID")),
                "Tier": _str(r.get("Tier")),
                "Composite_Score": r.get("Composite_Score"),
                "Notes": f"Seeded {today} from Sign_Deployment_Plan",
            })
        df = _pd_df(rows)
        mio.replace_sheet(
            master, "Large_Sign_Locations", df,
            color_col="Install Status",
            color_map={
                "Pending":     "FFF8E1",
                "Approved":    "EAF3FB",
                "Installed":   "D4EDDA",
                "Declined":    "F8D7DA",
                "Removed":     "F8D7DA",
                "Damaged":     "F8D7DA",
                "Site Issue":  "FFF3CD",
            },
            dropdowns={
                "Install Status":  INSTALL_STATUS,
                "Approval Status": APPROVAL_STATUS,
                "Sign Type":       SIGN_TYPES,
            },
        )
        print(f"  Wrote {len(df)} primary sign-site rows (status=Pending).")

    # ── 2. Yard_Sign_Deliveries
    print("\nSeeding Yard_Sign_Deliveries ...")
    existing = mio.read_sheet_safe(master, "Yard_Sign_Deliveries")
    if _has_user_data(existing, "County") and not args.force:
        print(f"  SKIP — {(existing['County'].fillna('').astype(str).str.strip() != '').sum()} "
              f"user rows present. Use --force to overwrite.")
    else:
        rows = []
        for _, r in ysa.iterrows():
            rec_name = _str(r.get("County")) + " REC"
            contact = _str(r.get("Chair")) or _str(r.get("Primary_Delivery_Contact"))
            phone = _str(r.get("Chair_Phone")) or _str(r.get("Primary_Delivery_Phone"))
            email = _str(r.get("Chair_Email")) or _str(r.get("Primary_Delivery_Email")) or _str(r.get("REC_General_Email"))
            qty_plan = _to_int(r.get("Plan_4000"))
            qty_boss = _to_int(r.get("Suggested_Yard_Signs_Boss"))
            rows.append({
                "County": _str(r.get("County")),
                "Recipient / Organization": rec_name,
                "Delivery Location": _str(r.get("Meeting_Delivery_Location")),
                "Address": _str(r.get("Meeting_Delivery_Location")),
                "Contact": contact,
                "Phone": phone,
                "Email": email,
                "Qty Delivered": 0,
                "Qty Planned (Plan_4000)": qty_plan,
                "Qty Suggested (Boss 7485)": qty_boss,
                "Delivery Date": "",
                "Follow-Up Date": "",
                "Inventory Source": "",
                "Status": "Scheduled",
                "Notes": f"Seeded {today} from Yard_Sign_Allocation. POC status: "
                         f"{_str(r.get('POC_Status_Yard'))}",
            })
        df = _pd_df(rows)
        mio.replace_sheet(
            master, "Yard_Sign_Deliveries", df,
            color_col="Status",
            color_map={
                "Scheduled":  "FFF8E1",
                "Confirmed":  "EAF3FB",
                "In Transit": "FFF3CD",
                "Delivered":  "D4EDDA",
                "Issue":      "F8D7DA",
                "Cancelled":  "F8D7DA",
            },
            dropdowns={"Status": DELIVERY_STATUS},
        )
        print(f"  Wrote {len(df)} REC delivery rows (status=Scheduled).")

    # ── 3. Outreach_Log
    print("\nSeeding Outreach_Log ...")
    existing = mio.read_sheet_safe(master, "Outreach_Log")
    if _has_user_data(existing, "County") and not args.force:
        print(f"  SKIP — {(existing['County'].fillna('').astype(str).str.strip() != '').sum()} "
              f"user rows present. Use --force to overwrite.")
    else:
        # One outreach row per primary 4×8 site + 67 REC chair rows
        rows = []
        # 4×8 calls
        primary = sdp[sdp["Plan"] == "primary"].copy()
        for _, r in primary.iterrows():
            phone = _str(r.get("Phone"))
            email = _str(r.get("Email"))
            method = "phone" if phone else ("email" if email else "lookup-needed")
            rows.append({
                "Date": "",
                "County": _str(r.get("County")),
                "Contact Name": _str(r.get("Owner_Contact")),
                "Organization": _str(r.get("Name")),
                "Contact Type": "4x8 Site Owner",
                "Method": method,
                "Phone / Email Used": phone or email,
                "Purpose": "Cold ask: 4x8 sign placement permission",
                "Result Status": "To Call",
                "Signs Requested": 1,
                "4x8 Leads": 1,
                "Next Step": "Initial call",
                "Next Step Date": today,
                "Owner": "",
                "Notes": f"Seeded {today}. Tier {_str(r.get('Tier'))}, "
                         f"{_str(r.get('Category'))}, score {_str(r.get('Composite_Score'))}",
                "Source / Related Record": _str(r.get("Candidate_ID")),
            })
        # REC delivery coordination calls
        for _, r in ysa.iterrows():
            phone = _str(r.get("Chair_Phone")) or _str(r.get("Primary_Delivery_Phone"))
            email = _str(r.get("Chair_Email")) or _str(r.get("Primary_Delivery_Email"))
            method = "phone" if phone else "email"
            rows.append({
                "Date": "",
                "County": _str(r.get("County")),
                "Contact Name": _str(r.get("Chair")) or _str(r.get("Primary_Delivery_Contact")),
                "Organization": _str(r.get("County")) + " REC",
                "Contact Type": "REC Chair / Delivery",
                "Method": method,
                "Phone / Email Used": phone or email,
                "Purpose": "Coordinate yard sign delivery wave",
                "Result Status": "To Call",
                "Signs Requested": _to_int(r.get("Plan_4000")),
                "4x8 Leads": 0,
                "Next Step": "Confirm delivery window + handoff site",
                "Next Step Date": today,
                "Owner": "",
                "Notes": f"Seeded {today}. {_str(r.get('Wave'))}. "
                         f"Plan_4000={_to_int(r.get('Plan_4000'))}, Boss={_to_int(r.get('Suggested_Yard_Signs_Boss'))}",
                "Source / Related Record": "Yard_Sign_Allocation",
            })
        df = _pd_df(rows)
        mio.replace_sheet(
            master, "Outreach_Log", df,
            color_col="Result Status",
            color_map={
                "To Call":             "FFF8E1",
                "Voicemail":           "FFF3CD",
                "No Answer":           "FFF3CD",
                "Reached - Pending":   "EAF3FB",
                "Approved":            "D4EDDA",
                "Declined":            "F8D7DA",
                "Wrong Number":        "F8D7DA",
                "Do Not Contact":      "F8D7DA",
                "Closed":              "F8D7DA",
            },
            dropdowns={"Result Status": OUTREACH_STATUS},
        )
        n_4x8 = (df["Contact Type"] == "4x8 Site Owner").sum()
        n_rec = (df["Contact Type"] == "REC Chair / Delivery").sum()
        print(f"  Wrote {len(df)} outreach rows: {n_4x8} 4x8 calls + {n_rec} REC calls")

    print("\nAll operational sheets seeded.")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _has_user_data(df, key_col: str) -> bool:
    """True if the sheet has any non-template row with this key column populated."""
    if df is None or df.empty or key_col not in df.columns:
        return False
    return (df[key_col].fillna("").astype(str).str.strip() != "").any()


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    return str(v).strip()


def _to_int(v) -> int:
    try:
        if v is None:
            return 0
        f = float(v)
        if f != f:
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0 and v == v  # not NaN, not zero
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return False


def _city_from_address(addr: str) -> str:
    if not addr:
        return ""
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) < 2:
        return ""
    cand = parts[-2] if parts[-1].upper() in ("FL", "FLORIDA") else parts[-1]
    if cand and cand.upper() not in ("FL", "FLORIDA"):
        return cand
    return ""


def _pd_df(rows):
    import pandas as pd
    return pd.DataFrame(rows)


if __name__ == "__main__":
    sys.exit(main())
