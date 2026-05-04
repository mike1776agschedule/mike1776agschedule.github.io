#!/usr/bin/env python3
"""
Phase 1 — Contact Audit

Reads data/raw/contacts.xlsx, scores each record on completeness,
deduplicates by email (exact) and name+county (fuzzy), and replaces
the `Contacts` and `Flagged_Issues` sheets in the master workbook.

Usage:
    python scripts/01_audit_contacts.py --input data/raw/contacts.xlsx
    python scripts/01_audit_contacts.py --input <path> --auto-confirm
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Heavy imports happen inside main() so --help works without dependencies.

REQUIRED_FIELDS = ["Name", "County", "REC", "Phone", "Email"]
DEFAULT_INPUT = "data/raw/contacts.xlsx"
DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"

HEADER_HINTS = {
    "Name": ["name", "contact", "contact name", "full name", "first last"],
    "County": ["county"],
    "REC": ["rec", "rec name", "republican executive committee", "committee", "club"],
    "Phone": ["phone", "phone number", "mobile", "cell", "tel"],
    "Email": ["email", "e-mail", "email address"],
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 1 — Audit and dedupe contacts.xlsx into the master workbook.")
    p.add_argument("--input", default=DEFAULT_INPUT, help=f"Input xlsx (default: {DEFAULT_INPUT})")
    p.add_argument("--master", default=DEFAULT_MASTER, help=f"Master workbook (default: {DEFAULT_MASTER})")
    p.add_argument("--auto-confirm", action="store_true",
                   help="Skip interactive column-mapping prompt; use header hints.")
    p.add_argument("--fuzzy-threshold", type=int, default=92,
                   help="rapidfuzz WRatio score (0-100) for name dedup (default: 92).")
    return p.parse_args()


def detect_columns(df_columns, auto_confirm: bool) -> dict:
    lower_to_actual = {str(c).strip().lower(): c for c in df_columns}
    mapping: dict = {}
    for field in REQUIRED_FIELDS:
        for hint in HEADER_HINTS[field]:
            if hint in lower_to_actual:
                mapping[field] = lower_to_actual[hint]
                break

    print("\nDetected column mapping:")
    for field in REQUIRED_FIELDS:
        print(f"  {field:8s} -> {mapping.get(field, '(missing)')}")

    if auto_confirm:
        return mapping

    print("\nAvailable columns in workbook:")
    for col in df_columns:
        print(f"  - {col}")
    print("\nPress Enter to accept, or type 'FIELD=column-name' lines (blank line to finish).")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        if "=" not in line:
            print("  format: FIELD=column-name")
            continue
        field, actual = (s.strip() for s in line.split("=", 1))
        if field not in REQUIRED_FIELDS:
            print(f"  {field!r} is not required. choose from {REQUIRED_FIELDS}")
            continue
        mapping[field] = actual
    return mapping


def normalize_phone(value) -> tuple[str, str | None]:
    if value is None:
        return "", None
    raw = str(value).strip()
    if not raw:
        return "", None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return raw, f"phone has {len(digits)} digits (expected 10)"
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", None


def normalize_email(value) -> tuple[str, str | None]:
    if value is None:
        return "", None
    raw = str(value).strip().lower()
    if not raw:
        return "", None
    if not EMAIL_RE.match(raw):
        return raw, "email format invalid"
    return raw, None


def is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float):
        try:
            import math
            return math.isnan(v)
        except Exception:
            return False
    return str(v).strip() == ""


def main() -> int:
    args = parse_args()

    try:
        import pandas as pd
        from rapidfuzz import fuzz
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    in_path = Path(args.input)
    master_path = Path(args.master)
    if not in_path.exists():
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        return 1

    mio.init_master(master_path)

    print(f"Loading {in_path} ...")
    sheets = pd.read_excel(in_path, sheet_name=None)
    frames = []
    for name, df in sheets.items():
        df = df.copy()
        df["Source_Sheet"] = name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(df)} records across {len(sheets)} sheet(s).")

    mapping = detect_columns(df.columns, args.auto_confirm)
    missing_required = [f for f in REQUIRED_FIELDS if f not in mapping]
    if missing_required:
        print(f"WARN: could not map: {missing_required}; those fields will be flagged.", file=sys.stderr)

    norm = pd.DataFrame()
    norm["Source_Sheet"] = df["Source_Sheet"]
    for field in REQUIRED_FIELDS:
        src = mapping.get(field)
        norm[field] = df[src] if src in df.columns else None

    issues_rows: list[dict] = []
    phones, emails = [], []
    for idx, row in norm.iterrows():
        rec_label = str(row.get("Name") or f"row-{idx}")
        phone_norm, phone_issue = normalize_phone(row["Phone"])
        email_norm, email_issue = normalize_email(row["Email"])
        phones.append(phone_norm)
        emails.append(email_norm)
        if phone_issue:
            issues_rows.append({"record": rec_label, "field": "Phone", "issue": phone_issue, "value": row["Phone"]})
        if email_issue:
            issues_rows.append({"record": rec_label, "field": "Email", "issue": email_issue, "value": row["Email"]})
        for field in REQUIRED_FIELDS:
            if is_empty(row[field]):
                issues_rows.append({"record": rec_label, "field": field, "issue": "missing", "value": ""})
    norm["Phone"] = phones
    norm["Email"] = emails

    norm["Completeness_Score"] = sum((~norm[f].apply(is_empty)).astype(int) for f in REQUIRED_FIELDS)
    def quality(score: int) -> str:
        if score == 5:
            return "Complete"
        if score >= 3:
            return "Partial"
        return "Broken"
    norm["Quality"] = norm["Completeness_Score"].apply(quality)

    # Dedup pass 1: exact email
    before = len(norm)
    has_email = norm["Email"].astype(bool)
    norm_email = norm[has_email].drop_duplicates(subset=["Email"], keep="first")
    norm_no_email = norm[~has_email]
    norm = pd.concat([norm_email, norm_no_email], ignore_index=True)
    after_email = len(norm)

    # Dedup pass 2: fuzzy name within county (records w/o email only)
    keep_mask = [True] * len(norm)
    no_email_idx = norm.index[~norm["Email"].astype(bool)].tolist()
    for i in range(len(no_email_idx)):
        if not keep_mask[no_email_idx[i]]:
            continue
        ai = no_email_idx[i]
        a_name = str(norm.at[ai, "Name"] or "")
        a_county = str(norm.at[ai, "County"] or "")
        if not a_name:
            continue
        for j in range(i + 1, len(no_email_idx)):
            bi = no_email_idx[j]
            if not keep_mask[bi]:
                continue
            if str(norm.at[bi, "County"] or "") != a_county:
                continue
            b_name = str(norm.at[bi, "Name"] or "")
            if not b_name:
                continue
            score = fuzz.WRatio(a_name, b_name)
            if score >= args.fuzzy_threshold:
                keep_mask[bi] = False
                issues_rows.append({
                    "record": b_name, "field": "Name",
                    "issue": f"fuzzy duplicate of '{a_name}' (score {score})",
                    "value": b_name,
                })
    norm = norm[keep_mask].reset_index(drop=True)
    after_fuzzy = len(norm)
    print(f"Dedup: {before} -> {after_email} (email) -> {after_fuzzy} (fuzzy name).")

    issues_df = pd.DataFrame(issues_rows) if issues_rows else pd.DataFrame(
        columns=["record", "field", "issue", "value"]
    )
    if not issues_df.empty:
        per_record = issues_df.groupby("record")["issue"].apply(lambda s: "; ".join(s)).to_dict()
        norm["Issues"] = norm["Name"].astype(str).map(per_record).fillna("")
    else:
        norm["Issues"] = ""

    print(f"Writing Contacts + Flagged_Issues sheets to {master_path} ...")
    mio.replace_sheet(master_path, "Contacts", norm, quality_color_col="Quality")
    mio.replace_sheet(master_path, "Flagged_Issues", issues_df)
    print("Done.")
    print(f"  Clean records:  {len(norm)}")
    print(f"  Flagged issues: {len(issues_df)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
