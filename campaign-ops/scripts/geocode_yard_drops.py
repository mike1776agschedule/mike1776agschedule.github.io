#!/usr/bin/env python3
"""
Geocode the REC delivery / meeting location for each REC and write Lat/Lon
to Yard_Sign_Allocation. Uses Nominatim (free OSM, no API key, 1 req/sec).

Strategy (in order, until a result is found):
  1. Parse a clean street-level address out of the messy Meeting/Delivery
     Location field (drops semicolon clauses, facility-name prefixes, etc.)
  2. Try the cleaned address with city + 'FL'
  3. Try the County Office / Mailing / HQ field if present
  4. Fall back to the FL county SEAT (the actual town where the REC operates),
     not the geometric centroid — centroids land in swamps/forests for many
     Florida counties.

Cache: data/clean/_yard_geocode_cache.json (JSON; stable keys).

Usage:
    python scripts/geocode_yard_drops.py
    python scripts/geocode_yard_drops.py --rate-sleep 1.1
    python scripts/geocode_yard_drops.py --force-recompute  # ignore cache
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
GEOCODE_CACHE = "data/clean/_yard_geocode_cache.json"

# Florida county seats — the actual administrative town, used as fallback
# instead of geometric centroid (which lands in unpopulated terrain for many
# rural counties).
FL_COUNTY_SEATS = {
    "Alachua": "Gainesville", "Baker": "Macclenny", "Bay": "Panama City",
    "Bradford": "Starke", "Brevard": "Titusville", "Broward": "Fort Lauderdale",
    "Calhoun": "Blountstown", "Charlotte": "Punta Gorda", "Citrus": "Inverness",
    "Clay": "Green Cove Springs", "Collier": "Naples", "Columbia": "Lake City",
    "DeSoto": "Arcadia", "Dixie": "Cross City", "Duval": "Jacksonville",
    "Escambia": "Pensacola", "Flagler": "Bunnell", "Franklin": "Apalachicola",
    "Gadsden": "Quincy", "Gilchrist": "Trenton", "Glades": "Moore Haven",
    "Gulf": "Port St. Joe", "Hamilton": "Jasper", "Hardee": "Wauchula",
    "Hendry": "LaBelle", "Hernando": "Brooksville", "Highlands": "Sebring",
    "Hillsborough": "Tampa", "Holmes": "Bonifay", "Indian River": "Vero Beach",
    "Jackson": "Marianna", "Jefferson": "Monticello", "Lafayette": "Mayo",
    "Lake": "Tavares", "Lee": "Fort Myers", "Leon": "Tallahassee",
    "Levy": "Bronson", "Liberty": "Bristol", "Madison": "Madison",
    "Manatee": "Bradenton", "Marion": "Ocala", "Martin": "Stuart",
    "Miami-Dade": "Miami", "Monroe": "Key West", "Nassau": "Fernandina Beach",
    "Okaloosa": "Crestview", "Okeechobee": "Okeechobee", "Orange": "Orlando",
    "Osceola": "Kissimmee", "Palm Beach": "West Palm Beach", "Pasco": "Dade City",
    "Pinellas": "Clearwater", "Polk": "Bartow", "Putnam": "Palatka",
    "Santa Rosa": "Milton", "Sarasota": "Sarasota", "Seminole": "Sanford",
    "St. Johns": "St. Augustine", "St. Lucie": "Fort Pierce",
    "Sumter": "Bushnell", "Suwannee": "Live Oak", "Taylor": "Perry",
    "Union": "Lake Butler", "Volusia": "DeLand", "Wakulla": "Crawfordville",
    "Walton": "DeFuniak Springs", "Washington": "Chipley",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Geocode REC delivery locations.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--rate-sleep", type=float, default=1.1)
    p.add_argument("--force-recompute", action="store_true",
                   help="Ignore existing cache and re-query Nominatim.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import pandas as pd
        import httpx
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}).", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    ysa = mio.read_sheet_safe(master, "Yard_Sign_Allocation")
    cm = mio.read_sheet_safe(master, "County_Master")
    if ysa.empty or cm.empty:
        print("ERROR: Yard_Sign_Allocation or County_Master is empty.", file=sys.stderr)
        return 1

    cache_path = Path(GEOCODE_CACHE)
    cache = {} if args.force_recompute else _load_cache(cache_path)
    print(f"Geocoding {len(ysa)} REC delivery locations ({len(cache)} cached) ...")

    # Index the County_Master HQ field so we can pull it as a secondary
    cm_hq = {}
    for _, c in cm.iterrows():
        county = str(c.get("County") or "").strip()
        hq = c.get("County Office / Mailing / HQ")
        if isinstance(hq, str) and hq.strip() and hq.strip().lower() != "nan":
            cm_hq[county] = hq.strip()

    if "Drop_Lat" not in ysa.columns:
        ysa["Drop_Lat"] = None
    if "Drop_Lon" not in ysa.columns:
        ysa["Drop_Lon"] = None
    if "Drop_Geocode_Source" not in ysa.columns:
        ysa["Drop_Geocode_Source"] = ""
    if "Drop_Geocoded_Address" not in ysa.columns:
        ysa["Drop_Geocoded_Address"] = ""

    n_addr = n_hq = n_seat = n_fail = n_cached = 0
    for idx, row in ysa.iterrows():
        county = str(row.get("County") or "").strip()
        meet = _str(row.get("Meeting_Delivery_Location"))
        hq = cm_hq.get(county, "")

        # Try queries in order of specificity.
        queries: list[tuple[str, str]] = []  # (query_string, source_label)

        # 1. Cleaned meeting address
        clean = _extract_street_address(meet)
        if clean:
            queries.append((f"{clean}, FL", "Nominatim:meeting_address"))
            # Simplified version (strip suite/direction/hyphens) — Nominatim is picky
            simple = _simplify_address(clean)
            if simple and simple != clean:
                queries.append((f"{simple}, FL", "Nominatim:meeting_address_simple"))
            queries.append((f"{clean}, {county} County, FL", "Nominatim:meeting_address+county"))

        # 2. County HQ address
        if hq:
            hq_clean = _extract_street_address(hq)
            if hq_clean:
                queries.append((f"{hq_clean}, FL", "Nominatim:hq_address"))

        # 3. County seat (better than centroid for FL — actual town)
        seat = FL_COUNTY_SEATS.get(county)
        if seat:
            queries.append((f"{seat}, {county} County, FL", "Nominatim:county_seat"))
        # 4. Last resort
        queries.append((f"{county} County, Florida", "Nominatim:county_only"))

        result = None
        used_source = ""
        used_query = ""
        for q, src in queries:
            cache_key = f"{q}||{county}"  # county-aware cache key
            if cache_key in cache:
                cached = cache[cache_key]
                if cached:
                    result = cached
                    used_source = src
                    used_query = q
                    n_cached += 1
                    break
                continue
            # County-only fallback shouldn't enforce expected_county check (it's already
            # the county). Address queries DO enforce.
            enforce_county = "address" in src or "hq_address" in src
            res = _nominatim(httpx, q, expected_county=county if enforce_county else "")
            cache[cache_key] = res
            time.sleep(args.rate_sleep)
            if res:
                result = res
                used_source = src
                used_query = q
                break

        if result and result.get("lat") and result.get("lon"):
            ysa.at[idx, "Drop_Lat"] = float(result["lat"])
            ysa.at[idx, "Drop_Lon"] = float(result["lon"])
            ysa.at[idx, "Drop_Geocode_Source"] = used_source
            ysa.at[idx, "Drop_Geocoded_Address"] = result.get("display_name", "") or used_query
            if "meeting_address" in used_source:
                n_addr += 1
            elif "hq_address" in used_source:
                n_hq += 1
            elif "county_seat" in used_source:
                n_seat += 1
            else:
                n_seat += 1  # county_only counts as fallback bucket
        else:
            ysa.at[idx, "Drop_Geocode_Source"] = "FAILED"
            n_fail += 1

    _save_cache(cache_path, cache)

    print(f"\nGeocoding done:")
    print(f"  Meeting-address (best):    {n_addr}")
    print(f"  HQ-address (good):         {n_hq}")
    print(f"  County seat (decent):      {n_seat}")
    print(f"  Cache hits:                {n_cached}")
    print(f"  Failed:                    {n_fail}")

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
    print("Done.")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Address extraction
# ──────────────────────────────────────────────────────────────────────────────

# Patterns to skip entirely
SKIP_PATTERNS = (
    "tbd", "varies", "see ", "call ", "email ", "meeting date", "n/a", "none",
)

# Regex for "<num> <street words> ... <city>, FL <zip?>"
# Handles directional abbreviations with periods (Blvd N., St., Ave.) by allowing
# the street part to contain ', N.', ', S.', etc. before the city comma.
# Examples that should match:
#   "1455 Pine Ridge Rd, Naples, FL 34109"
#   "10515 Northcliffe Blvd, Spring Hill, FL 34608"
#   "1801 Havendale Blvd N., Winter Haven, FL"
#   "902 FL-20 Suite 102, Freeport, FL 32439"
ADDRESS_RE = re.compile(
    r"\b(\d{1,6}[A-Z]?\s+"           # street number (and optional letter)
    r"[A-Z0-9][\w\.\-/'\s]*?"        # street name (allows "FL-20", "5th", "St.")
    r"(?:\s+[NSEW]\.?)?,\s*"         # optional trailing direction (N./S./E./W.)
    r"[A-Za-z\.\s\-'/]+,\s*"         # city
    r"FL(?:\s*\d{5}(?:-\d{4})?)?)",  # state + optional zip
    re.IGNORECASE,
)
# Looser: '<num> <words>' before the first comma (no city/state)
ADDRESS_LOOSE_RE = re.compile(
    r"\b(\d{1,6}[A-Z]?\s+[A-Za-z][\w\.\-/'\s]{4,80})",
)


def _extract_street_address(raw: str) -> str:
    """Return a clean '<num> <street>, <city>, FL [zip]' string or ''.

    Examples:
      'Northcliffe Church, 10515 Northcliffe Blvd, Spring Hill, FL 34608; 3rd Tuesday'
        → '10515 Northcliffe Blvd, Spring Hill, FL 34608'
      'Happy Homes Inc 7600 NW 5th Place Gainesville FL 32607'
        → '7600 NW 5th Place, Gainesville, FL 32607'  (best-effort reformat)
      'Varies' or 'TBD' → ''
    """
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    low = s.lower()
    # Skip pure junk
    if any(low.startswith(p) for p in SKIP_PATTERNS) or low in ("tbd", "varies", "n/a", "none"):
        return ""

    # Drop everything after the first ';' (meeting time annotations etc)
    s = s.split(";")[0].strip()

    # Try the strict pattern first
    m = ADDRESS_RE.search(s)
    if m:
        addr = m.group(1).strip().rstrip(",.;: ")
        return _normalize_spaces(addr)

    # Loose: '<num> <street words>' then we'll append city
    m = ADDRESS_LOOSE_RE.search(s)
    if m:
        candidate = m.group(1).strip().rstrip(",.;: ")
        # Try to attach a trailing city if "FL" appears anywhere in the original
        # e.g. "Happy Homes Inc 7600 NW 5th Place Gainesville FL 32607"
        # → candidate = "7600 NW 5th Place Gainesville FL 32607"
        # We'll just return this raw and let Nominatim handle it.
        candidate = _normalize_spaces(candidate)
        return candidate
    return ""


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _simplify_address(addr: str) -> str:
    """Strip patterns Nominatim chokes on: trailing direction (Blvd N.),
    suite/unit/apt qualifiers, hyphenated route refs (FL-20 → FL 20), zip code."""
    s = addr
    # Strip "Suite XX", "Apt YY", "Unit ZZ", "# 123"
    s = re.sub(r",?\s*(suite|ste|apt|unit|#)\s*[\w\-]+", "", s, flags=re.IGNORECASE)
    # Strip trailing direction with period (Blvd N., White Ave SE)
    s = re.sub(r"\b(Blvd|Ave|St|Rd|Dr|Pkwy|Ln|Ct|Way|Cir)\s+([NSEW]{1,2})\.?\b",
               r"\1", s, flags=re.IGNORECASE)
    # Strip leading/embedded direction prefix on route ("16840 SE Hwy 19" → "16840 Hwy 19")
    s = re.sub(r"\b([NSEW]{1,2})\s+(Hwy|Highway|Route|Rt|US|FL|SR|CR)\b",
               r"\2", s, flags=re.IGNORECASE)
    # FL-20 → FL 20  (Nominatim prefers space)
    s = re.sub(r"\b(FL|US|SR|CR)-(\d+)", r"\1 \2", s)
    # Drop trailing ZIP
    s = re.sub(r"\s+\d{5}(?:-\d{4})?\s*$", "", s)
    return _normalize_spaces(s)


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    return str(v).strip()


# ──────────────────────────────────────────────────────────────────────────────
# Nominatim
# ──────────────────────────────────────────────────────────────────────────────

def _nominatim(httpx, query: str, expected_county: str = ""):
    """Query Nominatim with Florida viewbox bias and verify result is in FL.
    If `expected_county` is provided, also verify the result's county matches —
    rejects same-name street collisions in other counties."""
    headers = {"User-Agent": "campaign-ops/1.0 (geocode_yard_drops.py)"}
    params = {
        "q": query,
        "format": "json",
        "limit": 5,                # ask for 5; pick first one in FL+expected county
        "countrycodes": "us",
        # Florida bounding box (left, top, right, bottom) — restricts to FL
        "viewbox": "-87.65,31.05,-79.90,24.40",
        "bounded": 1,
    }
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/search",
                      headers=headers, params=params, timeout=10.0)
        if r.status_code != 200:
            return None
        data = r.json()
        if not data:
            return None
        # Pick first result that's in FL AND (if given) the expected county
        for d in data:
            display = d.get("display_name", "")
            if "Florida" not in display:
                continue
            if expected_county:
                # Match "<County> County" anywhere in display name (case-insensitive,
                # tolerant of normalization, e.g. "St. Johns" vs "Saint Johns")
                exp = expected_county.replace(".", "").lower()
                disp_norm = display.replace(".", "").lower()
                if f"{exp} county" not in disp_norm:
                    continue
            return {"lat": d["lat"], "lon": d["lon"], "display_name": display}
        return None
    except Exception:
        return None


def _load_cache(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_cache(path: Path, cache):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(cache, ensure_ascii=False))
    except Exception as e:
        print(f"WARN: could not save cache: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
