# Campaign Ops — Project Context

## What This Project Is

Statewide (67-county) Florida campaign signage operation. The boss has done
the strategic work — county tier rankings, per-county sign allocations,
regional hub planning, partner / influence prospect lists, audit trail.
This project keeps the boss's master workbook live with two operational
deliverables:

1. **2,000 4×8 sign deployment plan** with Points-of-Contact (phone + email)
   for each, sourced via OSM tags + Yelp Fusion API matching (no hallucination).
   ~500 replacement bench for refusal recovery.
2. **Yard sign allocation per REC** with TWO totals side-by-side: boss's
   audited 7,485 plan AND a re-allocated `Plan_4000` (50% tier-weight + 50%
   GOP-voter-weight). Every county has at least one POC.

## Key Numbers (from boss's audited master)

- **7,485 yard signs** suggested statewide (boss's plan)
- **4,000 yard signs** alternative plan (`Plan_4000` column)
- **367 4×8 sign opportunities** statewide (boss's number — we deliver 2,000
  primary candidates ranked, with 500 replacements)
- **67 counties**, tiered A (11) / B (8) / C (14) / D (34)
- **898 directory contacts** in `florida_gop_directory.xlsx`

## Categorical Exclusions (V3 — Strategist Pass)

Real campaign reality — these venues do NOT host political signs:
- Churches / places of worship (501c3 risk)
- Funeral homes (sensitivity)
- Schools, colleges, kindergartens (FL law)
- Government buildings: post office, fire station, town hall, library,
  courthouse, police, hospital, clinic
- Banks, ATMs, pharmacies (corporate policy)

Plus a chain blocklist of corporate-controlled venues (see
`scripts/find_sign_locations.py::CHAIN_BLOCKLIST`): Lowe's, Home Depot,
Discount Tire, Firestone, Pep Boys, Walmart, Target, Costco, Sam's, BJ's,
Dollar General/Tree/Family, Publix, Winn-Dixie, Kroger, IKEA, Best Buy,
CVS / Walgreens / Rite Aid, Wawa, RaceTrac, Circle K, 7-Eleven, Buc-ee's,
Bass Pro / Cabela's corporate, Jiffy Lube. (Tractor Supply intentionally
NOT blocked — owner-operated stores often say yes.)

## Master Workbook Layout

Three sheet classes (full list in [_master_io.py](scripts/_master_io.py)):

- **BOSS_OWNED** (14 sheets) — read-only, except `County_Master` columns
  `Yard Signs Delivered`, `Yard Signs Remaining`, `4x8 Confirmed` which the
  feedback loop updates
- **USER_EDITED** (3 sheets) — `Yard_Sign_Deliveries`, `Large_Sign_Locations`,
  `Outreach_Log`. The user fills these by hand. **Scripts NEVER overwrite them.**
- **DERIVED** (6 sheets) — `Dashboard`, `Directory_Audit`,
  `Sign_Location_Candidates`, `Sign_Deployment_Plan`, `Yard_Sign_Allocation`,
  `QC_Report`.

= 23 sheets total.

The non-clobbering guarantee is enforced by `scripts/_master_io.py` —
any code touching the master MUST go through that helper:
- `replace_sheet()` for derived sheets
- `update_cells()` for the surgical County_Master feedback writes
- `read_sheet_safe()` for everything else

## Data Files

- `outputs/campaign_ops_master.xlsx` — boss's audited master (canonical)
- `data/raw/florida_gop_directory.xlsx` — boss's contact directory (898 rows)
- `data/clean/_osmnx_cache/` — OpenStreetMap response cache
- `data/clean/_yelp_cache.json` — Yelp Fusion API response cache

## Scripts (run order)

1. `find_sign_locations.py` — OSM pull, V3 strategist categories, chain
   blocklist enforced. Writes `Sign_Location_Candidates` (~3,000 rows). Slow.
2. `enrich_pocs.py` — three-tier waterfall (OSM tags → Yelp Fusion API → click-
   to-search URLs). Validates phone via `phonenumbers`, requires fuzzy name
   match (≥75) AND geo distance (≤150m) for Yelp acceptance — no hallucination.
3. `select_sign_deployment.py` — picks 2,000 primary + ~500 replacement
   from the candidate pool, ranked by composite score (tier × score × POC).
   Writes `Sign_Deployment_Plan`.
4. `allocate_yard_signs.py` — per-REC yard sign allocation with dual totals
   (boss's 7,485 + new Plan_4000). Enriches missing chair POCs from the
   Master Directory. Writes `Yard_Sign_Allocation`.
5. `build_candidate_map.py` — Folium HTML map. Defaults to `Sign_Deployment_Plan`
   when present.
6. `qc_report.py` — quality control checks. Writes `QC_Report` sheet.
7. `refresh_master.py` — Dashboard + Directory_Audit + County_Master feedback loop.

`_master_io.py` — shared helper for surgical workbook edits.
`_archive/` — earlier single-county precinct-level pipeline.

## Code Standards

- Python only
- Use pandas, openpyxl, phonenumbers, httpx, rapidfuzz
- Every script must be runnable standalone (`--help` works without deps)
- Print progress to console as scripts run
- Never overwrite raw data files
- Never overwrite USER_EDITED sheets in the master
- Never modify BOSS_OWNED sheets except via the County_Master feedback columns
- Heavy imports happen INSIDE main() so `--help` works without the dependency tree
- **NO HALLUCINATION**: every Phone/Email value MUST trace to a non-empty `_Source` field

## API Keys

`enrich_pocs.py` uses `YELP_API_KEY` env var (free, 5,000 calls/day at
https://www.yelp.com/developers). Without it Tier 2 enrichment is skipped
and the script falls back to OSM tags + click-to-search URLs only.

## Connection to Parent Repo

This subfolder lives inside `fl_ag_campaign_site/`. The parent repo's
`campaign_schedule_outreach.html` contains REC event data in
`window.FL_AG_CAMPAIGN_DATA`. Parent repo files are not modified by this project.
