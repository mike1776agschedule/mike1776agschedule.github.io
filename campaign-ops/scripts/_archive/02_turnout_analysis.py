#!/usr/bin/env python3
"""
Phase 2 — Precinct Turnout Analysis

Joins 2022 and 2024 precinct-level turnout, computes turnout rates and swing,
assigns priority tiers, and replaces the `Precincts` sheet in the master workbook.

Usage:
    python scripts/02_turnout_analysis.py \
        --turnout-2022 data/raw/turnout_2022.csv \
        --turnout-2024 data/raw/turnout_2024.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_2022 = "data/raw/turnout_2022.csv"
DEFAULT_2024 = "data/raw/turnout_2024.csv"
DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"

REQUIRED_COLS = ["precinct_id", "registered_voters", "votes_cast"]
OPTIONAL_PARTY_COLS = ["dem_votes", "rep_votes", "npa_votes"]
OPTIONAL_COUNTY_COL = "county"

COLUMN_HINTS = {
    "precinct_id": ["precinct", "precinct id", "precinct_id", "precinct number", "pct", "id"],
    "registered_voters": ["registered", "registered voters", "reg", "reg voters", "registered_voters"],
    "votes_cast": ["votes", "votes cast", "ballots", "ballots cast", "total votes", "votes_cast"],
    "dem_votes": ["dem", "democrat", "dem votes", "dem_votes"],
    "rep_votes": ["rep", "republican", "rep votes", "rep_votes", "gop"],
    "npa_votes": ["npa", "no party", "independent", "other", "npa_votes"],
    "county": ["county"],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 2 — Precinct turnout analysis -> master workbook.")
    p.add_argument("--turnout-2022", default=DEFAULT_2022)
    p.add_argument("--turnout-2024", default=DEFAULT_2024)
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--swing-threshold", type=float, default=5.0,
                   help="Swing in percentage points classifying a precinct as 'mobilize' (default: 5.0)")
    return p.parse_args()


def auto_map(columns) -> dict:
    lower = {str(c).strip().lower(): c for c in columns}
    out: dict = {}
    for canon in list(REQUIRED_COLS) + list(OPTIONAL_PARTY_COLS) + [OPTIONAL_COUNTY_COL]:
        for hint in COLUMN_HINTS[canon]:
            if hint in lower:
                out[canon] = lower[hint]
                break
    return out


def load_turnout(path: Path, label: str):
    import pandas as pd

    if not path.exists():
        print(f"ERROR: turnout file not found: {path}", file=sys.stderr)
        sys.exit(1)
    df = pd.read_csv(path)
    mapping = auto_map(df.columns)
    print(f"\n[{label}] Detected columns:")
    for canon in REQUIRED_COLS + OPTIONAL_PARTY_COLS + [OPTIONAL_COUNTY_COL]:
        print(f"  {canon:18s} -> {mapping.get(canon, '(missing)')}")
    missing = [c for c in REQUIRED_COLS if c not in mapping]
    if missing:
        print(f"ERROR: {label} CSV missing required columns: {missing}", file=sys.stderr)
        sys.exit(1)
    out = pd.DataFrame()
    out["precinct_id"] = df[mapping["precinct_id"]].astype(str).str.strip()
    out["registered_voters"] = pd.to_numeric(df[mapping["registered_voters"]], errors="coerce")
    out["votes_cast"] = pd.to_numeric(df[mapping["votes_cast"]], errors="coerce")
    for col in OPTIONAL_PARTY_COLS:
        if col in mapping:
            out[col] = pd.to_numeric(df[mapping[col]], errors="coerce")
    if OPTIONAL_COUNTY_COL in mapping:
        out["county"] = df[mapping[OPTIONAL_COUNTY_COL]].astype(str).str.strip()
    return out


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

    df22 = load_turnout(Path(args.turnout_2022), "2022")
    df24 = load_turnout(Path(args.turnout_2024), "2024")

    df22["turnout_22"] = (df22["votes_cast"] / df22["registered_voters"]).round(4)
    df24["turnout_24"] = (df24["votes_cast"] / df24["registered_voters"]).round(4)

    base_24_cols = ["precinct_id", "registered_voters", "votes_cast", "turnout_24"]
    if "county" in df24.columns:
        base_24_cols.append("county")
    df = df24[base_24_cols].rename(
        columns={"registered_voters": "reg_voters_24", "votes_cast": "votes_24"}
    )
    if "county" in df.columns:
        df = df.rename(columns={"county": "County"})
    df = df.merge(
        df22[["precinct_id", "turnout_22", "registered_voters", "votes_cast"]].rename(
            columns={"registered_voters": "reg_voters_22", "votes_cast": "votes_22"}
        ),
        on="precinct_id", how="outer",
    )
    df["swing"] = (df["turnout_24"] - df["turnout_22"]).round(4)

    has_party = "dem_votes" in df24.columns and "rep_votes" in df24.columns
    if has_party:
        df = df.merge(df24[["precinct_id", "dem_votes", "rep_votes"]], on="precinct_id", how="left")
        denom = (df["dem_votes"].fillna(0) + df["rep_votes"].fillna(0)).replace(0, pd.NA)
        df["margin"] = ((df["rep_votes"] - df["dem_votes"]) / denom).round(4)

    median_24 = df["turnout_24"].median()
    median_reg = df["reg_voters_24"].median()
    swing_threshold = args.swing_threshold / 100.0

    def classify(row) -> tuple[int, str]:
        t24 = row["turnout_24"]
        sw = row["swing"]
        reg = row["reg_voters_24"]
        favorable = True
        if has_party and pd.notna(row.get("margin")):
            favorable = row["margin"] > 0
        if pd.notna(t24) and t24 >= median_24 and favorable:
            return 1, "Tier 1 — Protect"
        if pd.notna(sw) and sw >= swing_threshold and (pd.isna(t24) or t24 < median_24):
            return 2, "Tier 2 — Mobilize"
        if pd.notna(reg) and reg >= median_reg and (pd.isna(t24) or t24 < median_24):
            return 3, "Tier 3 — Persuade"
        return 4, "Tier 4 — Deprioritize"

    tiers = df.apply(classify, axis=1, result_type="expand")
    tiers.columns = ["tier", "tier_label"]
    df = pd.concat([df, tiers], axis=1)
    df["priority_score"] = df["tier"]

    df = df.sort_values(["tier", "turnout_24"], ascending=[True, False]).reset_index(drop=True)

    print(f"\nMedian 2024 turnout: {median_24:.1%}  Median reg voters: {median_reg:.0f}")
    print("Tier distribution:")
    print(df["tier_label"].value_counts().sort_index().to_string())

    print(f"\nReplacing Precincts sheet in {master_path} ...")
    mio.replace_sheet(master_path, "Precincts", df)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
