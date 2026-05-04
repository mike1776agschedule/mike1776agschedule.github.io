# Archived Phase Scripts

These scripts were built during the original (single-county, precinct-level)
scoping of the project. They were archived on 2026-04-25 when the boss's
statewide master workbook (`florida_sign_operations_master_*.xlsx`) was
adopted as canonical and the project pivoted to county-level / 67-county
scope.

| Script | Why archived | Replaced by |
|---|---|---|
| `00_build_master.py` | Built an empty master from scratch; boss's master already exists | `scripts/refresh_master.py` |
| `01_audit_contacts.py` | Boss's `County_Audit` sheet already scores completeness per county; full-directory audit moved into `Directory_Audit` sheet | `scripts/refresh_master.py` Directory_Audit logic |
| `02_turnout_analysis.py` | Precinct-level turnout analysis; statewide scope uses `County_Master.Strategic Tier` instead | (no replacement — out of scope) |
| `03_gis_map.py` | Precinct-level Folium map with osmnx road intersections; statewide scope doesn't need precinct granularity | (no replacement — out of scope) |
| `04_sign_allocation.py` | County-level allocation; boss already provides `Suggested Yard Signs` and `Suggested 4x8 Goal` per county | `County_Master` columns (already populated) |

## When to revisit

If scope ever returns to a single-county precinct-level deep dive (e.g., for a
specific Tier-A county like Miami-Dade), these scripts can be unarchived and
adapted. They expect:
- A precinct shapefile in `data/raw/precincts/`
- Turnout CSVs in `data/raw/turnout_2022.csv` and `_2024.csv`
- A `contacts.xlsx` in the original schema

The shared helper `scripts/_master_io.py` is still in use and not archived.
