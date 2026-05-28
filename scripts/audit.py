#!/usr/bin/env python3
"""
Run quality-control checks against the live encrypted data and print a report.

Read-only — does not modify any files.

Checks:
  1. Schema integrity (every record has exactly 20 canonical fields)
  2. Past-dated events (anything before today)
  3. Dates outside the May–Aug 2026 campaign window
  4. Recurrence math (does the date match the recurrence pattern?)
  5. Duplicates (same county + org + date)
  6. Field completeness (% filled per field)
  7. All 67 Florida counties present
  8. Phone format consistency

Usage:
    export FL_AG_PIN=040476
    python scripts/audit.py
"""
import re, sys
from datetime import datetime, date
from collections import Counter, defaultdict
from calendar import monthrange
from pathlib import Path
from _common import HTML_FILES, SCHEMA, get_pin, decrypt_records

TODAY = date.today()
WINDOW_START = date(2026, 5, 1)
WINDOW_END = date(2026, 8, 31)

FL_COUNTIES = {
    "Alachua","Baker","Bay","Bradford","Brevard","Broward","Calhoun","Charlotte","Citrus","Clay",
    "Collier","Columbia","DeSoto","Dixie","Duval","Escambia","Flagler","Franklin","Gadsden",
    "Gilchrist","Glades","Gulf","Hamilton","Hardee","Hendry","Hernando","Highlands","Hillsborough",
    "Holmes","Indian River","Jackson","Jefferson","Lafayette","Lake","Lee","Leon","Levy","Liberty",
    "Madison","Manatee","Marion","Martin","Miami-Dade","Monroe","Nassau","Okaloosa","Okeechobee",
    "Orange","Osceola","Palm Beach","Pasco","Pinellas","Polk","Putnam","St. Johns","St. Lucie",
    "Santa Rosa","Sarasota","Seminole","Sumter","Suwannee","Taylor","Union","Volusia","Wakulla",
    "Walton","Washington",
}

ORD = {"1st":1,"first":1,"2nd":2,"second":2,"3rd":3,"third":3,"4th":4,"fourth":4,"5th":5,"last":-1}
DAYS = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}


def parse_date(s):
    if not s or s.strip().lower() == "tbd": return None
    try: return datetime.strptime(s.strip(), "%B %d, %Y").date()
    except: return None


def header(title):
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def main():
    records = decrypt_records(HTML_FILES[0], get_pin())
    total = len(records)
    print(f"Loaded {total} records (today = {TODAY})")
    issues_total = 0

    # 1. Schema integrity
    header("1. Schema integrity")
    bad = []
    for i, r in enumerate(records):
        missing = [k for k in SCHEMA if k not in r]
        extra = [k for k in r if k not in SCHEMA]
        if missing or extra: bad.append((i, missing, extra))
    if bad:
        print(f"  FAIL: {len(bad)} records with schema problems")
        for b in bad[:5]:
            print(f"    [{b[0]}] missing={b[1]} extra={b[2]}")
        issues_total += len(bad)
    else:
        print("  PASS: all records match canonical 20-field schema")

    # 2. Past-dated
    header("2. Past-dated events")
    past = [(i, parse_date(r["Meeting_or_Event_Date"]), r) for i, r in enumerate(records)
            if parse_date(r.get("Meeting_or_Event_Date", "")) and parse_date(r["Meeting_or_Event_Date"]) < TODAY]
    if past:
        print(f"  FAIL: {len(past)} past-dated events. Run roll_forward.py.")
        for i, d, r in past[:10]:
            print(f"    [{i}] {d}  {r['Organization_or_Event_Name']} ({r['County']})")
        issues_total += len(past)
    else:
        print("  PASS: no past-dated events")

    # 3. Outside window
    header(f"3. Dates outside {WINDOW_START}..{WINDOW_END}")
    oob = [(i, parse_date(r["Meeting_or_Event_Date"]), r) for i, r in enumerate(records)
           if parse_date(r.get("Meeting_or_Event_Date", "")) and not (WINDOW_START <= parse_date(r["Meeting_or_Event_Date"]) <= WINDOW_END)]
    if oob:
        print(f"  WARN: {len(oob)} out-of-window dates")
        for i, d, r in oob[:10]:
            print(f"    [{i}] {d}  {r['Organization_or_Event_Name']}")
    else:
        print("  PASS")

    # 4. Recurrence math
    header("4. Recurrence pattern vs actual date")
    mism = []
    for i, r in enumerate(records):
        d = parse_date(r.get("Meeting_or_Event_Date", ""))
        rec = r.get("Recurrence", "").strip().lower()
        if not d or not rec: continue
        patterns = []
        for m in re.finditer(r"(1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last)\s+(?:and\s+(1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?", rec):
            o1, o2, day = m.group(1), m.group(2), m.group(3)
            patterns.append((ORD[o1], DAYS[day]))
            if o2: patterns.append((ORD[o2], DAYS[day]))
        if not patterns: continue
        actual_dow, actual_ord = d.weekday(), (d.day - 1) // 7 + 1
        ok = False
        for o, dow in patterns:
            if o == -1:
                last = monthrange(d.year, d.month)[1]
                for day in range(last, last-7, -1):
                    if date(d.year, d.month, day).weekday() == dow:
                        if d.day == day: ok = True
                        break
            elif actual_dow == dow and actual_ord == o:
                ok = True
        if not ok:
            mism.append((i, r["Organization_or_Event_Name"], r["County"], rec, d.strftime("%a %b %d")))
    if mism:
        print(f"  WARN: {len(mism)} recurrence mismatches (may be false-positives on multi-pattern recurrences)")
        for m in mism[:10]:
            print(f"    [{m[0]}] {m[1]} ({m[2]}): '{m[3]}' actual={m[4]}")
    else:
        print("  PASS")

    # 5. Duplicates
    header("5. Duplicates (county+org+date)")
    dup_map = defaultdict(list)
    for i, r in enumerate(records):
        date_val = r.get("Meeting_or_Event_Date", "").strip()
        if not date_val:
            continue  # blank-date duplicates may be legit (TBD placeholders)
        norm_org = re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", r["Organization_or_Event_Name"].strip().lower()))
        k = (r["County"].lower(), norm_org, date_val)
        dup_map[k].append(i)
    dupes = {k: v for k, v in dup_map.items() if len(v) > 1}
    if dupes:
        print(f"  FAIL: {len(dupes)} duplicate sets")
        for k, v in list(dupes.items())[:10]:
            print(f"    {k} -> {v}")
        issues_total += len(dupes)
    else:
        print("  PASS: no exact duplicates (blank-date records not compared)")

    # 6. Field completeness
    header("6. Field completeness")
    for f in ["County","Region","Category","Subcategory","Organization_or_Event_Name",
              "Contact_Name","Phone","Email","Website","Source_URL"]:
        filled = sum(1 for r in records if str(r.get(f, "")).strip())
        pct = 100 * filled // total
        bar = "#" * (pct // 5) + "." * (20 - pct // 5)
        print(f"  {f:<32} [{bar}] {pct:>3}%  ({filled}/{total})")

    # 7. County coverage
    header("7. All 67 Florida counties present")
    counties = {r["County"] for r in records}
    missing = FL_COUNTIES - counties
    extra = counties - FL_COUNTIES
    if missing:
        print(f"  FAIL: missing counties: {missing}"); issues_total += len(missing)
    if extra:
        print(f"  WARN: unrecognized county names in data: {extra}")
    if not missing and not extra:
        print("  PASS: all 67 counties present, no unrecognized names")

    # 8. Phone format
    header("8. Phone format consistency")
    bad_phone = []
    for i, r in enumerate(records):
        p = r.get("Phone", "").strip()
        if p and p.lower() != "tbd" and not re.match(r"^\(\d{3}\)\s?\d{3}-\d{4}", p):
            bad_phone.append((i, r["Organization_or_Event_Name"], p))
    if bad_phone:
        print(f"  FAIL: {len(bad_phone)} non-standard phone numbers")
        for b in bad_phone[:10]: print(f"    [{b[0]}] {b[1]}: '{b[2]}'")
        issues_total += len(bad_phone)
    else:
        print(f"  PASS")

    # Summary
    header(f"AUDIT SUMMARY")
    if issues_total == 0:
        print("  All hard checks PASS")
    else:
        print(f"  {issues_total} issues require attention")
        sys.exit(1)


if __name__ == "__main__":
    main()
