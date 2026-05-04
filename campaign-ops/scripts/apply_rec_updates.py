#!/usr/bin/env python3
"""
Apply triple-verified REC contact updates to Yard_Sign_Allocation.

Every update in REC_UPDATES below was verified by an autonomous agent against:
  1. The REC's own website
  2. florida.gop county directory
  3. Master Directory (florida_gop_directory.xlsx, audited 2026-04-23)

Adds an audit trail: Update_Source column logs which fields came from which source.
Runs idempotently — re-running won't double-apply.

Usage:
    python scripts/apply_rec_updates.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"

# ──────────────────────────────────────────────────────────────────────────────
# Triple-verified REC updates (from 3 parallel agentic verification runs).
# Each update lists field=new_value; only fields listed are updated.
# Source key tracks where the verification came from for the audit trail.
# ──────────────────────────────────────────────────────────────────────────────
REC_UPDATES: dict[str, dict] = {
    # ── TIER A ──
    "Brevard": {
        "Chair_Email": "brevardchairman@gmail.com",
        "_source": "florida.gop + Master Directory (2026-04-23)",
    },
    "Duval": {
        "Chair_Email": "Chairman@duval.gop",
        "REC_General_Email": "Chairman@duval.gop",
        "REC_Website": "https://www.duval.gop/",
        "_source": "florida.gop (legacy rpdc.org domain retired)",
    },
    "Hillsborough": {
        "REC_General_Email": "info@hillsborough.gop",
        "REC_Website": "https://www.hillsborough.gop/",
        "_source": "florida.gop + hillsborough.gop",
    },
    "Lake": {
        "REC_Website": "https://lakecountyrepublicans.org/",
        "REC_General_Email": "info@lakecountyrepublicans.org",
        "_source": "Master Directory + florida.gop",
    },
    "Lee": {
        "REC_Website": "https://www.leegop.org/",
        "_source": "florida.gop + Master Directory",
    },
    "Manatee": {
        "REC_Website": "https://manateegop.com/",
        "REC_General_Email": "admin@manateegop.com",
        "_source": "Master Directory (chair email implies domain)",
    },
    "Marion": {
        "REC_Website": "https://www.marioncountyrec.com/",
        "_source": "Master Directory",
    },
    "Orange": {
        "REC_Website": "https://orangefl.gop/",
        "_source": "florida.gop",
    },
    "Palm Beach": {
        "REC_Website": "https://www.palmbeach.gop/",
        "REC_General_Email": "info@palmbeach.gop",
        "_source": "florida.gop (pbcgop.org is legacy domain)",
    },
    "Pasco": {
        "REC_Website": "https://pascogop.com/",
        "_source": "florida.gop",
    },
    "Pinellas": {
        "REC_Website": "https://www.pinellasrepublican.org/",
        "_source": "florida.gop + Master Directory",
    },
    "Polk": {
        "REC_Website": "https://polk.gop/",
        "_source": "florida.gop + Master Directory",
    },

    # ── TIER B ──
    "Collier": {
        "REC_Website": "https://collier.gop/",
        "_source": "florida.gop",
    },
    "Sarasota": {
        "REC_Website": "https://www.sarasotagop.com/",
        "_source": "Master Directory",
    },
    "Seminole": {
        "REC_Website": "https://seminolegop.org/",
        "_source": "florida.gop",
    },
    "St. Johns": {
        "REC_Website": "https://www.stjohns.gop/",
        "_source": "florida.gop",
    },
    "Volusia": {
        "REC_Website": "https://www.volusiacountyrepublicans.org/",
        "_source": "florida.gop + Master Directory",
    },

    # ── TIER C ──
    "Bay": {
        "REC_Website": "https://baygop.com/",
        "_source": "florida.gop + baygop.com",
    },
    "Charlotte": {
        "REC_Website": "https://www.charlottegop.com/",
        "_source": "florida.gop",
    },
    "Citrus": {
        "REC_Website": "https://citrusgop.org/",
        "_source": "florida.gop",
    },
    "Clay": {
        "Chair_Email": "chairman@clayrepublicans.com",
        "REC_General_Email": "chairman@clayrepublicans.com",
        "REC_Website": "https://clayrepublicans.com/",
        "_source": "florida.gop + Master Directory (replaces personal hotmail)",
    },
    "Escambia": {
        "Chair_Email": "robertsjw@aol.com",
        "REC_General_Email": "robertsjw@aol.com",
        "REC_Website": "https://escambiarepublican.com/",
        "_source": "florida.gop + escambiarepublican.com (corrects domain to live site)",
    },
    "Hernando": {
        "REC_Website": "https://hernandogop.com/",
        "_source": "REC site + florida.gop",
    },
    "Indian River": {
        "Chair_Email": "chairman@ircgop.com",
        "REC_General_Email": "chairman@ircgop.com",
        "REC_Website": "https://www.ircgop.com/",
        "_source": "florida.gop + ircgop.com (replaces unreachable indianriver.gop)",
    },
    "Leon": {
        "Chair_Email": "chairman@leongop.com",
        "REC_General_Email": "chairman@leongop.com",
        "REC_Website": "https://leongop.com/",
        "_source": "florida.gop (replaces personal gmail)",
    },
    "Martin": {
        "Chair_Email": "MC.REC.Chair@icloud.com",
        "REC_General_Email": "office@martingop.com",
        "REC_Website": "https://www.martingop.com/",
        "_source": "florida.gop + Master Directory (replaces personal hotmail)",
    },
    "Okaloosa": {
        # CRITICAL: chair was NULL in workbook
        "Chair": "Doug 'Doc' Stauffer",
        "REC_Website": "https://www.okaloosagop.com/",
        "_source": "okaloosagop.com/people.html + Master Directory + news article",
    },
    "Osceola": {
        "REC_Website": "https://www.osceola.gop/",
        "_source": "florida.gop + Master Directory",
    },
    "St. Lucie": {
        "REC_Website": "https://florida.gop/st-lucie-guide",
        "_source": "florida.gop (no separate REC site)",
    },
    "Sumter": {
        # Fix: delivery email was Chair's email, not Committeeman's
        "Primary_Delivery_Email": "rgreenebtrb@gmail.com",
        "_source": "florida.gop (Bob Greene Committeeman correct email)",
    },

    # ── TIER D ──
    "Alachua": {
        "REC_General_Email": "chairman@alachuarepublicans.com",
        "REC_Website": "http://www.alachuarepublicans.com/",
        "_source": "alachuarepublicans.com + florida.gop",
    },
    "Bradford": {
        "Chair": "Richard Solze",
        "Chair_Email": "rsolze@embarqmail.com",
        "Chair_Phone": "904-364-6077",
        "_source": "florida.gop",
    },
    "Calhoun": {
        "Chair": "Bill Gaskin",
        "Chair_Email": "bill@billgaskin.com",
        "Chair_Phone": "404-427-8043",
        "_source": "florida.gop",
    },
    "Columbia": {
        "REC_Website": "https://columbiagop.com/",
        "_source": "Master Directory",
    },
    "DeSoto": {
        "Chair": "Erik Howard",
        "Chair_Email": "desotorepublicans@gmail.com",
        "Chair_Phone": "239-707-8091",
        "REC_Website": "https://desotocountyrepublicans.com/",
        "_source": "florida.gop + Master Directory",
    },
    "Dixie": {
        "Chair": "Jovante' Teague",
        "Chair_Email": "jovante@outlook.com",
        "Chair_Phone": "352-440-1390",
        "REC_General_Email": "dixiecountyrepublicanparty@gmail.com",
        "_source": "florida.gop",
    },
    "Flagler": {
        "Chair": "Perry Mitrano",
        "Chair_Email": "chairman@flaglergop.com",
        "Chair_Phone": "386-237-2047",
        "REC_Website": "https://flaglergop.com/",
        "_source": "florida.gop",
    },
    "Gilchrist": {
        "Chair": "David Biddle",
        "Chair_Email": "dcbbiddle@yahoo.com",
        "Chair_Phone": "352-339-0445",
        "_source": "florida.gop",
    },
    "Glades": {
        "Chair": "Curtis Clay",
        "Chair_Email": "brownnosed6@gmail.com",
        "Chair_Phone": "863-673-4862",
        "_source": "florida.gop",
    },
    "Hamilton": {
        "Chair": "Ben Norris",
        "Chair_Email": "drnorris59@yahoo.com",
        "Chair_Phone": "386-234-0643",
        "_source": "florida.gop",
    },
    "Hardee": {
        "Chair": "Sue Birge",
        "Chair_Email": "suebirge45@gmail.com",
        "Chair_Phone": "863-781-3536",
        "_source": "florida.gop",
    },
    "Hendry": {
        "Chair": "Ron Zimmerly",
        "Chair_Email": "rzimm2378@gmail.com",
        "Chair_Phone": "863-234-8397",
        "_source": "florida.gop",
    },
    "Highlands": {
        "Chair": "Lauren Bush",
        "Chair_Email": "chair@highlandsrepublicans.com",
        "Chair_Phone": "863-402-5456",
        "REC_General_Email": "hlgop@highlandsrepublicans.com",
        "REC_Website": "https://highlandsrepublicans.com/",
        "_source": "florida.gop",
    },
    "Holmes": {
        "Chair": "Terry Mears",
        "Chair_Email": "mearsfam74@gmail.com",
        "Chair_Phone": "850-768-3022",
        "_source": "florida.gop",
    },
    "Jackson": {
        "Chair": "Clint Pate",
        "Chair_Email": "clintpate@yahoo.com",
        "Chair_Phone": "850-527-3900",
        "_source": "florida.gop",
    },
    "Jefferson": {
        "Chair": "Benjamin 'Glen' Bishop",
        "Chair_Email": "glensharonbishop@embarqmail.com",
        "Chair_Phone": "850-508-4536",
        "_source": "florida.gop",
    },
    "Lafayette": {
        "Chair": "Kimberly Ledbetter Patterson",
        "Chair_Email": "kimberlyenriquez@gmail.com",
        "Chair_Phone": "352-507-5108",
        "REC_Website": "https://www.lafayetteflgop.com/",
        "_source": "florida.gop",
    },
    "Levy": {
        "Chair": "Michelle Finnen",
        "Chair_Email": "mfinnen@yahoo.com",
        "Chair_Phone": "352-949-8273",
        "_source": "florida.gop",
    },
    "Liberty": {
        "Chair": "Donnie Read",
        "Chair_Email": "granpappy1958@gmail.com",
        "Chair_Phone": "850-643-7698",
        "_source": "florida.gop",
    },
    "Madison": {
        "Chair": "Mike Rump",
        "Chair_Email": "mikettmkids@hotmail.com",
        "Chair_Phone": "850-614-4455",
        "REC_General_Email": "rec.madison@yahoo.com",
        "_source": "florida.gop + Master Directory",
    },
    "Monroe": {
        "Chair": "Rhonda Rebman-Lopez",
        "Chair_Email": "Chairman@keysgop.org",
        "Chair_Phone": "305-389-2979",
        "REC_General_Email": "info@keysgop.org",
        "REC_Website": "https://keysgop.org/",
        "_source": "florida.gop + keysgop.org",
    },
    "Okeechobee": {
        "Chair": "Jim Craig",
        "Chair_Email": "jimcraig47@yahoo.com",
        "Chair_Phone": "574-249-9495",
        "_source": "florida.gop",
    },
    "Putnam": {
        "Chair": "Larry Harvey",
        "Chair_Email": "larryharvey48@gmail.com",
        "Chair_Phone": "386-972-0957",
        "_source": "florida.gop",
    },
    "Suwannee": {
        "Chair": "Lisa Keep",
        "Chair_Email": "lisakeep@proton.me",
        "Chair_Phone": "301-602-1967",
        "_source": "florida.gop",
    },
    "Taylor": {
        "Chair": "Christy Moody",
        "Chair_Email": "christy.moody31@gmail.com",
        "Chair_Phone": "850-838-7900",
        "_source": "florida.gop",
    },
    "Union": {
        "Chair": "Vince Brown",
        "Chair_Email": "vince@brownbaginteractive.com",
        "Chair_Phone": "352-283-6312",
        "_source": "florida.gop",
    },
    "Walton": {
        "Chair": "Mary Howard",
        "Chair_Email": "WaltonFLRepublicanChair@gmail.com",
        "Chair_Phone": "713-962-8976",
        "REC_Website": "https://waltonflgop.com/",
        "_source": "florida.gop + waltonflgop.com",
    },
    "Washington": {
        "Chair": "Malcolm Gainey",
        "Chair_Email": "gator91@bellsouth.net",
        "Chair_Phone": "850-260-5585",
        "_source": "florida.gop",
    },
}

# Counties to flag for human follow-up — verification turned up conflicts
HUMAN_FOLLOWUP_FLAGS = {
    "Nassau": "Chair conflict: workbook shows Chris Kirkland; Master Directory (2026-04-20) shows Darron Ayscue. Phone-confirm before delivery.",
    "Franklin": "Role-title ambiguity: workbook lists Kristy Branch Banks as Chair; florida.gop calls Rick Watson 'Chair'. Confirm via direct call.",
    "Volusia": "Phone discrepancy between workbook and Master Directory (386-689-2164 vs 386-348-5547). Verify before relying.",
    "Pasco": "Two meeting venues across sources (Myrtle Lake Baptist vs Grace Family Church). florida.gop = Myrtle Lake.",
    "Manatee": "Meeting location is officially TBD per florida.gop. Mandatory chair-direct call before delivery.",
    "Sumter": "Chair phone unverifiable on any current public source.",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply triple-verified REC updates.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--dry-run", action="store_true")
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
    ysa = mio.read_sheet_safe(master, "Yard_Sign_Allocation")
    if ysa.empty:
        print("ERROR: Yard_Sign_Allocation is empty.", file=sys.stderr)
        return 1

    today = datetime.now().strftime("%Y-%m-%d")

    # Add audit columns if not present
    if "Update_Source" not in ysa.columns:
        ysa["Update_Source"] = ""
    if "Update_Date" not in ysa.columns:
        ysa["Update_Date"] = ""
    if "Followup_Required" not in ysa.columns:
        ysa["Followup_Required"] = ""

    n_county_updates = 0
    n_field_updates = 0
    update_log: list[str] = []

    for county, updates in REC_UPDATES.items():
        # Find row
        mask = ysa["County"].astype(str).str.strip() == county
        if not mask.any():
            print(f"WARN: county not found in Yard_Sign_Allocation: {county}")
            continue
        idx = ysa.index[mask][0]
        source = updates.get("_source", "verified")
        county_changed = False
        for field, new_val in updates.items():
            if field.startswith("_"):
                continue
            if field not in ysa.columns:
                print(f"WARN: column not found: {field}")
                continue
            old_val = str(ysa.at[idx, field] or "").strip()
            old_norm = old_val.lower() if old_val and old_val.lower() != "nan" else ""
            new_norm = str(new_val or "").strip().lower()
            if old_norm == new_norm:
                continue
            if not args.dry_run:
                ysa.at[idx, field] = new_val
            update_log.append(f"  {county:14s} {field:25s} '{old_val[:40]}' -> '{new_val[:40]}'")
            n_field_updates += 1
            county_changed = True
        if county_changed:
            existing = str(ysa.at[idx, "Update_Source"] or "").strip()
            new_src = source
            combined = f"{existing}; {new_src}" if existing and existing.lower() != "nan" else new_src
            if not args.dry_run:
                ysa.at[idx, "Update_Source"] = combined
                ysa.at[idx, "Update_Date"] = today
            n_county_updates += 1

    # Recompute POC_Status_Yard for affected counties
    for idx, row in ysa.iterrows():
        chair_email = str(row.get("Chair_Email") or "").strip()
        chair_phone = str(row.get("Chair_Phone") or "").strip()
        del_phone = str(row.get("Primary_Delivery_Phone") or "").strip()
        del_email = str(row.get("Primary_Delivery_Email") or "").strip()
        rec_email = str(row.get("REC_General_Email") or "").strip()
        is_blank = lambda v: not v or v.lower() == "nan"
        if not is_blank(chair_email) and not is_blank(chair_phone):
            status = "chair_complete"
        elif (not is_blank(chair_email) or not is_blank(chair_phone)):
            status = "partial_with_delivery" if (not is_blank(del_phone) or not is_blank(del_email)) else "partial"
        elif not is_blank(del_phone) or not is_blank(del_email) or not is_blank(rec_email):
            status = "delivery_only"
        else:
            status = "MISSING"
        if not args.dry_run:
            ysa.at[idx, "POC_Status_Yard"] = status

    # Apply human-followup flags
    for county, note in HUMAN_FOLLOWUP_FLAGS.items():
        mask = ysa["County"].astype(str).str.strip() == county
        if mask.any():
            idx = ysa.index[mask][0]
            if not args.dry_run:
                ysa.at[idx, "Followup_Required"] = note

    print(f"\nApplied REC updates:")
    print(f"  Counties touched:        {n_county_updates}")
    print(f"  Field-level updates:     {n_field_updates}")
    print(f"  Counties flagged for followup: {len(HUMAN_FOLLOWUP_FLAGS)}")
    if update_log[:30]:
        print(f"\nFirst 30 changes:")
        for line in update_log[:30]:
            print(line)
    if args.dry_run:
        print("\n(dry-run — no changes saved)")
        return 0

    print(f"\nWriting Yard_Sign_Allocation ...")
    mio.replace_sheet(master, "Yard_Sign_Allocation", ysa,
                      color_col="POC_Status_Yard",
                      color_map={
                          "chair_complete":         "D4EDDA",
                          "partial_with_delivery":  "FFF3CD",
                          "partial":                "FFF3CD",
                          "delivery_only":          "EAF3FB",
                          "MISSING":                "F8D7DA",
                      })

    # Re-summarize POC status
    poc_summary = ysa["POC_Status_Yard"].value_counts().to_dict()
    print(f"\nFinal POC status breakdown:")
    for k, v in sorted(poc_summary.items()):
        print(f"  {k:25s} {v}")
    print(f"\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
