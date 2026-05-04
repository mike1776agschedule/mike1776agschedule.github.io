#!/usr/bin/env python3
"""QC checks for FL_AG_CAMPAIGN_DATA in campaign_schedule_outreach.html"""

import re
import json
import sys
from collections import defaultdict

# ── Extract JSON ─────────────────────────────────────────────────────────────
html_path = '/Users/stefanhiekin/projects/fl_ag_campaign_site/campaign_schedule_outreach.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Find the assignment — grab everything between the first [ and the matching ]
m = re.search(r'window\.FL_AG_CAMPAIGN_DATA\s*=\s*(\[)', html)
if not m:
    sys.exit('ERROR: could not find FL_AG_CAMPAIGN_DATA')

start = m.start(1)
depth = 0
end = start
for i, ch in enumerate(html[start:], start):
    if ch == '[':
        depth += 1
    elif ch == ']':
        depth -= 1
        if depth == 0:
            end = i + 1
            break

json_str = html[start:end]
data = json.loads(json_str)
print(f'Loaded {len(data)} records.\n')

# ── Helpers ──────────────────────────────────────────────────────────────────
def is_empty(v):
    return v is None or (isinstance(v, str) and v.strip() == '')

def rec_name(r):
    return r.get('Organization_or_Event_Name') or '(no name)'

SEP = '═' * 70

# ════════════════════════════════════════════════════════════════════════════
# CHECK 1 — Completeness Audit
# ════════════════════════════════════════════════════════════════════════════
print(SEP)
print('CHECK 1 — COMPLETENESS AUDIT')
print(SEP)

REQUIRED_FIELDS = [
    'Region',
    'County',
    'Category',
    'Subcategory',
    'Organization_or_Event_Name',
    'Contact_Name',
    'Website',
    'Source_URL',
]

issues = []
for idx, rec in enumerate(data):
    for field in REQUIRED_FIELDS:
        if is_empty(rec.get(field)):
            issues.append({'idx': idx, 'org': rec_name(rec), 'field': field})

if not issues:
    print('✓ No missing required fields found.\n')
else:
    print(f'Found {len(issues)} blank required field(s):\n')
    by_field = defaultdict(list)
    for item in issues:
        by_field[item['field']].append(item)
    for field, records in by_field.items():
        print(f'  Field: {field} — {len(records)} blank(s)')
        for r in records:
            print(f'    [{r["idx"]}] {r["org"]}')
    print()

print('Blank count per required field:')
for field in REQUIRED_FIELDS:
    count = sum(1 for r in data if is_empty(r.get(field)))
    print(f'  {field:<35} {count}')
print()

# ════════════════════════════════════════════════════════════════════════════
# CHECK 4 — Date Validation
# ════════════════════════════════════════════════════════════════════════════
print(SEP)
print('CHECK 4 — DATE VALIDATION')
print(SEP)

MONTH_NAMES = ['January','February','March','April','May','June',
               'July','August','September','October','November','December']
DATE_RE = re.compile(r'^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$')

tbd_records = []
bad_format = []
before_april_2026 = []
outside_window = []
month_counts = defaultdict(int)

for idx, rec in enumerate(data):
    d = rec.get('Meeting_or_Event_Date', '')
    if is_empty(d):
        tbd_records.append({'idx': idx, 'org': rec_name(rec)})
        continue
    d = d.strip()
    m = DATE_RE.match(d)
    if not m:
        bad_format.append({'idx': idx, 'org': rec_name(rec), 'value': d})
        continue
    month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
    month_name_lower = month_str.lower()
    month_names_lower = [mn.lower() for mn in MONTH_NAMES]
    if month_name_lower not in month_names_lower:
        bad_format.append({'idx': idx, 'org': rec_name(rec), 'value': d, 'reason': 'unknown month'})
        continue
    month_idx = month_names_lower.index(month_name_lower)  # 0-based
    month_num = month_idx + 1  # 1-based
    year = int(year_str)

    key = f'{MONTH_NAMES[month_idx]} {year}'
    month_counts[key] += 1

    if year < 2026 or (year == 2026 and month_num < 4):
        before_april_2026.append({'idx': idx, 'org': rec_name(rec), 'value': d})

    if year != 2026 or month_num < 4 or month_num > 8:
        outside_window.append({'idx': idx, 'org': rec_name(rec), 'value': d})

# Bad format
if not bad_format:
    print('✓ All dated records match "Month D, YYYY" format.\n')
else:
    print(f'Bad date format — {len(bad_format)} record(s):')
    for r in bad_format:
        print(f'  [{r["idx"]}] {r["org"]} → "{r["value"]}"')
    print()

# Before April 2026
if not before_april_2026:
    print('✓ No dates before April 2026.\n')
else:
    print(f'Dates BEFORE April 2026 — {len(before_april_2026)} record(s):')
    for r in before_april_2026:
        print(f'  [{r["idx"]}] {r["org"]} → "{r["value"]}"')
    print()

# Outside window
if not outside_window:
    print('✓ All dates fall within April–August 2026 window.\n')
else:
    print(f'Dates OUTSIDE April–August 2026 window — {len(outside_window)} record(s):')
    for r in outside_window:
        print(f'  [{r["idx"]}] {r["org"]} → "{r["value"]}"')
    print()

# Month distribution — sort by year then month
print('Month distribution (records with a date):')
def sort_key(k):
    parts = k.rsplit(' ', 1)
    mn, yr = parts[0], int(parts[1])
    mi = [m.lower() for m in MONTH_NAMES].index(mn.lower()) if mn.lower() in [m.lower() for m in MONTH_NAMES] else 99
    return (yr, mi)
for k in sorted(month_counts.keys(), key=sort_key):
    print(f'  {k:<20} {month_counts[k]}')
print()

# TBD
print(f'TBD records (no date) — {len(tbd_records)} total:')
for r in tbd_records:
    print(f'  [{r["idx"]}] {r["org"]}')
print()

# ════════════════════════════════════════════════════════════════════════════
# CHECK 5 — County / Region Validation
# ════════════════════════════════════════════════════════════════════════════
print(SEP)
print('CHECK 5 — COUNTY / REGION VALIDATION')
print(SEP)

OFFICIAL_COUNTIES = {
    'Alachua','Baker','Bay','Bradford','Brevard','Broward','Calhoun','Charlotte',
    'Citrus','Clay','Collier','Columbia','DeSoto','Dixie','Duval','Escambia',
    'Flagler','Franklin','Gadsden','Gilchrist','Glades','Gulf','Hamilton','Hardee',
    'Hendry','Hernando','Highlands','Hillsborough','Holmes','Indian River','Jackson',
    'Jefferson','Lafayette','Lake','Lee','Leon','Levy','Liberty','Madison','Manatee',
    'Marion','Martin','Miami-Dade','Monroe','Nassau','Okaloosa','Okeechobee','Orange',
    'Osceola','Palm Beach','Pasco','Pinellas','Polk','Putnam','Santa Rosa','Sarasota',
    'Seminole','St. Johns','St. Lucie','Sumter','Suwannee','Taylor','Union','Volusia',
    'Wakulla','Walton','Washington'
}

KNOWN_MAPPINGS = {
    'Miami-Dade':   'South Florida',
    'Duval':        'Northeast Florida',
    'Hillsborough': 'Central Florida',
    'Escambia':     'Northwest Florida',
    'Leon':         'North Central Florida',
    'Orange':       'Central Florida',
    'Polk':         'Central Florida',
    'Palm Beach':   'South Florida',
    'Broward':      'South Florida',
    'Lee':          'Southwest Florida',
    'Collier':      'Southwest Florida',
    'Volusia':      'Northeast Florida',
    'Brevard':      'Central Florida',
    'Pinellas':     'Central Florida',
}

county_region_map = defaultdict(set)   # county → set of regions
region_county_map = defaultdict(set)   # region → set of counties

for rec in data:
    county = rec.get('County', '')
    region = rec.get('Region', '')
    if not is_empty(county):
        county_region_map[county].add(region if not is_empty(region) else '(blank)')
    if not is_empty(region):
        region_county_map[region].add(county if not is_empty(county) else '(blank)')

unique_counties = sorted(county_region_map.keys())
print(f'Unique counties in data ({len(unique_counties)}):')
print('  ' + ', '.join(unique_counties) + '\n')

# Invalid counties
invalid = [c for c in unique_counties if c not in OFFICIAL_COUNTIES]
if not invalid:
    print('✓ All county names match the official Florida county list.\n')
else:
    print(f'Invalid/unrecognised counties — {len(invalid)}:')
    for c in invalid:
        print(f'  "{c}" → found in regions: {", ".join(sorted(county_region_map[c]))}')
    print()

# Missing counties
missing = sorted(c for c in OFFICIAL_COUNTIES if c not in county_region_map)
print(f'Counties in official list but NOT in data ({len(missing)}):')
if missing:
    print('  ' + ', '.join(missing))
print()

# Verify known mappings
print('Verifying known County → Region mappings:')
mapping_errors = 0
for county, expected_region in KNOWN_MAPPINGS.items():
    actual_regions = county_region_map.get(county)
    if not actual_regions:
        print(f'  [NOT IN DATA] {county} — expected: {expected_region}')
    else:
        regions = sorted(actual_regions)
        if all(r == expected_region for r in regions):
            print(f'  ✓ {county:<16} → {expected_region}')
        else:
            print(f'  ✗ {county:<16} → expected "{expected_region}", found: {", ".join(regions)}')
            mapping_errors += 1

if mapping_errors == 0:
    print('\n✓ All checked mappings are correct.\n')
else:
    print(f'\n{mapping_errors} mapping error(s) found.\n')

# Complete region→county listing
print('Complete Region → County mapping in data:')
for region in sorted(region_county_map.keys()):
    counties = sorted(region_county_map[region])
    print(f'\n  {region} ({len(counties)} counties):')
    print(f'    {", ".join(counties)}')
print()

# ════════════════════════════════════════════════════════════════════════════
# CHECK 7 — "Unverified" Label Check
# ════════════════════════════════════════════════════════════════════════════
print(SEP)
print('CHECK 7 — "UNVERIFIED" LABEL CHECK')
print(SEP)

# Literal "Unverified" in any field
literal_unverified = []
for idx, rec in enumerate(data):
    hits = [k for k, v in rec.items() if isinstance(v, str) and 'Unverified' in v]
    if hits:
        literal_unverified.append({'idx': idx, 'org': rec_name(rec), 'fields': hits})

if not literal_unverified:
    print('✓ No records contain the literal string "Unverified".\n')
else:
    print(f'Records containing literal "Unverified" — {len(literal_unverified)}:')
    for r in literal_unverified:
        print(f'  [{r["idx"]}] {r["org"]} (in fields: {", ".join(r["fields"])})')
    print()

# Empty Contact_Name, Website, Source_URL (render as "Unverified" in UI)
empty_contact = [(i, r) for i, r in enumerate(data) if is_empty(r.get('Contact_Name'))]
empty_website = [(i, r) for i, r in enumerate(data) if is_empty(r.get('Website'))]
empty_source  = [(i, r) for i, r in enumerate(data) if is_empty(r.get('Source_URL'))]

print('Empty field counts (render as "Unverified" in UI):')
print(f'  Contact_Name  : {len(empty_contact)}')
print(f'  Website       : {len(empty_website)}')
print(f'  Source_URL    : {len(empty_source)}')
print()

if empty_contact:
    print(f'  Contact_Name blanks — {len(empty_contact)} records (goal: ZERO):')
    for idx, rec in empty_contact:
        print(f'    [{idx}] {rec_name(rec)}')
    print()
else:
    print('  ✓ Contact_Name: ZERO blanks — goal met.\n')

if empty_website:
    print(f'  Website blanks — {len(empty_website)} records:')
    for idx, rec in empty_website:
        print(f'    [{idx}] {rec_name(rec)}')
    print()

if empty_source:
    print(f'  Source_URL blanks — {len(empty_source)} records:')
    for idx, rec in empty_source:
        print(f'    [{idx}] {rec_name(rec)}')
    print()

print(SEP)
print('QC COMPLETE')
print(SEP)
