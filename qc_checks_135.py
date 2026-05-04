#!/usr/bin/env python3
"""QC Checks 1, 3, 5 for FL_AG_CAMPAIGN_DATA in index.html"""

import re
import json
import sys
from collections import defaultdict
from datetime import date, datetime

HTML_PATH = "/Users/stefanhiekin/projects/fl_ag_campaign_site/index.html"

# ── Extract JSON array via bracket-counting ─────────────────────────────────
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

m = re.search(r'window\.FL_AG_CAMPAIGN_DATA\s*=\s*(\[)', html)
if not m:
    sys.exit("ERROR: FL_AG_CAMPAIGN_DATA not found")

start = m.start(1)
depth = 0
end = start
for i, ch in enumerate(html[start:], start):
    if ch == '[':  depth += 1
    elif ch == ']':
        depth -= 1
        if depth == 0:
            end = i + 1
            break

json_str = html[start:end]
data = json.loads(json_str)
print(f"Loaded {len(data)} records.\n")

def blank(v):
    return v is None or str(v).strip() == ""

def org(rec):
    return rec.get("Organization_or_Event_Name", "").strip() or "(no name)"

SEP = "=" * 72
TODAY = date(2026, 4, 28)
WIN_START = date(2026, 4, 1)
WIN_END   = date(2026, 8, 31)

# ════════════════════════════════════════════════════════════════════════════
# CHECK 1 — Completeness Audit
# ════════════════════════════════════════════════════════════════════════════
print(SEP)
print("CHECK 1 — COMPLETENESS AUDIT")
print(SEP)
print(f"Total records: {len(data)}\n")

FIELDS = [
    "Region", "County", "Category", "Subcategory",
    "Organization_or_Event_Name", "Contact_Name", "Website", "Source_URL"
]

by_field = defaultdict(list)
for i, rec in enumerate(data):
    for f in FIELDS:
        if blank(rec.get(f, "")):
            by_field[f].append((i, org(rec)))

print("Blank field summary:")
for f in FIELDS:
    items = by_field[f]
    flag = " *** FLAGGED ***" if items else ""
    print(f"  {f:<40} {len(items)}{flag}")

for f in FIELDS:
    items = by_field[f]
    if items:
        print(f"\n  -- {f} blanks ({len(items)} records) --")
        for idx, name in items:
            print(f"     [{idx}] {name}")

# ════════════════════════════════════════════════════════════════════════════
# CHECK 3 — Date Validation
# ════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("CHECK 3 — DATE VALIDATION  (today=2026-04-28, campaign window=Apr–Aug 2026)")
print(SEP)

MONTH_NAMES = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]
DATE_RE = re.compile(r'^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$')

month_counts  = defaultdict(int)
empty_date    = []
past_dates    = []   # before 2026-04-28
out_of_window = []   # outside Apr-Aug 2026
bad_format    = []

for i, rec in enumerate(data):
    raw = rec.get("Meeting_or_Event_Date", "") or ""
    raw = str(raw).strip()
    name = org(rec)
    county = rec.get("County", "").strip() or ""

    if not raw:
        empty_date.append((i, name, county))
        continue

    m2 = DATE_RE.match(raw)
    if not m2:
        bad_format.append((i, name, county, raw))
        continue

    mon_str, day_str, yr_str = m2.group(1), m2.group(2), m2.group(3)
    mn_lower = [x.lower() for x in MONTH_NAMES]
    if mon_str.lower() not in mn_lower:
        bad_format.append((i, name, county, raw, "unknown month"))
        continue

    month_num = mn_lower.index(mon_str.lower()) + 1
    year = int(yr_str)
    day  = int(day_str)

    try:
        d = date(year, month_num, day)
    except ValueError:
        bad_format.append((i, name, county, raw, "invalid date"))
        continue

    key = f"{MONTH_NAMES[month_num-1]} {year}"
    month_counts[key] += 1

    if d < TODAY:
        past_dates.append((i, name, county, raw, d))

    if d < WIN_START or d > WIN_END:
        out_of_window.append((i, name, county, raw, d))

print(f"\nEmpty/blank date (recurring/undated): {len(empty_date)}")

print("\nRecords by month (with a date):")
ordered = ["April 2026","May 2026","June 2026","July 2026","August 2026"]
others  = sorted(k for k in month_counts if k not in ordered)
for m_key in ordered:
    cnt = month_counts.get(m_key, 0)
    if cnt or True:   # always show campaign months
        print(f"  {m_key:<20} {cnt}")
for m_key in others:
    print(f"  {m_key:<20} {month_counts[m_key]}  *** OUT-OF-WINDOW ***")

print(f"\nPAST DATES (before 2026-04-28): {len(past_dates)}")
if past_dates:
    for idx, name, county, raw, d in past_dates:
        print(f"  [{idx}] {name} | {county} | {raw}")
else:
    print("  None")

print(f"\nOUT-OF-WINDOW (outside Apr–Aug 2026): {len(out_of_window)}")
if out_of_window:
    for idx, name, county, raw, d in out_of_window:
        print(f"  [{idx}] {name} | {county} | {raw}")
else:
    print("  None")

print(f"\nBAD FORMAT / non-date text: {len(bad_format)}")
if bad_format:
    for item in bad_format:
        idx, name, county = item[0], item[1], item[2]
        raw = item[3]
        reason = item[4] if len(item) > 4 else ""
        print(f"  [{idx}] {name} | {county} | '{raw}'" + (f" ({reason})" if reason else ""))
else:
    print("  None")

# ════════════════════════════════════════════════════════════════════════════
# CHECK 5 — Contact Data Quality
# ════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("CHECK 5 — CONTACT DATA QUALITY")
print(SEP)

ADDR_RE  = re.compile(r'(^\d+\s|\bCR\s|\bHwy\b|\bHighway\b|\bRoad\b|\bStreet\b|'
                       r'\bAve\b|\bAvenue\b|\bBlvd\b|\bDr\b|\bDrive\b|\bLane\b|'
                       r'\bCourt\b|\bCircle\b|\bPkwy\b|\bRoute\b)',
                       re.IGNORECASE)
VENUE_RE  = re.compile(r'\b(Hall|Center|Centre|Building|Plaza|Lodge|Fairground|'
                        r'Fairgrounds|Arena|Pavilion|Auditorium|Complex|Park)\b',
                        re.IGNORECASE)

empty_contact   = []
address_contact = []
single_word     = []
office_suffix   = []
ins_agent       = []
venue_name      = []

for i, rec in enumerate(data):
    name = org(rec)
    cn   = rec.get("Contact_Name", "") or ""
    cn   = str(cn).strip()

    if not cn:
        empty_contact.append((i, name))
        continue

    if ADDR_RE.search(cn):
        address_contact.append((i, name, cn))

    if len(cn.split()) == 1:
        single_word.append((i, name, cn))

    if re.search(r'\bOffice\b', cn, re.IGNORECASE):
        office_suffix.append((i, name, cn))

    if re.search(r'\b(Insurance|Agent)\b', cn, re.IGNORECASE):
        ins_agent.append((i, name, cn))

    if VENUE_RE.search(cn):
        venue_name.append((i, name, cn))

print(f"\nEmpty Contact_Name: {len(empty_contact)}")
if empty_contact:
    for idx, name in empty_contact:
        print(f"  [{idx}] {name}")

print(f"\nContact looks like street address ({len(address_contact)}):")
if address_contact:
    for idx, name, cn in address_contact:
        print(f"  [{idx}] {name} | '{cn}'")
else:
    print("  None")

print(f"\nSingle-word Contact_Name — likely incomplete ({len(single_word)}):")
if single_word:
    for idx, name, cn in single_word:
        print(f"  [{idx}] {name} | '{cn}'")
else:
    print("  None")

print(f"\nContact_Name contains 'Office' — org-level placeholder ({len(office_suffix)}):")
if office_suffix:
    for idx, name, cn in office_suffix:
        print(f"  [{idx}] {name} | '{cn}'")
else:
    print("  None")

print(f"\nContact_Name contains 'Insurance' or 'Agent' — possible confusion ({len(ins_agent)}):")
if ins_agent:
    for idx, name, cn in ins_agent:
        print(f"  [{idx}] {name} | '{cn}'")
else:
    print("  None")

print(f"\nContact_Name looks like a venue name ({len(venue_name)}):")
if venue_name:
    for idx, name, cn in venue_name:
        print(f"  [{idx}] {name} | '{cn}'")
else:
    print("  None")

print(f"\n{SEP}")
print("QC COMPLETE")
print(SEP)
