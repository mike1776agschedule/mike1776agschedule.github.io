#!/usr/bin/env python3
"""
Pull candidate 4x8 sign locations from OpenStreetMap, per county, weighted by
the boss's Strategic Tier and Suggested 4x8 Goal. Writes a
`Sign_Location_Candidates` sheet to the master workbook.

V3 (campaign strategist's playbook):
  - EXCLUDED: churches, schools, government buildings, banks, pharmacies,
    funeral homes (per user / strategist guidance — these refuse political signs)
  - ADDED: VFW posts, gun shops, marinas, RV parks, BBQ joints, used car lots,
    hardware (independent), craft trades (roofer/plumber/electrician/etc.),
    motorcycle/boat dealers, alcohol stores, antiques, country stores
  - CHAIN BLOCKLIST: Lowe's, Home Depot, Discount Tire, Firestone, Pep Boys,
    big-box retailers — corporate policy refuses political signs
  - OSM TAG PRESERVATION: every candidate row carries its full OSM tag dict
    in `OSM_Tags_JSON` so `enrich_pocs.py` can extract phone/email/website
    without re-pulling OSM

Usage:
    python scripts/find_sign_locations.py                  # all 67 counties
    python scripts/find_sign_locations.py --counties Alachua Bay
    python scripts/find_sign_locations.py --target 3000    # tune total
    python scripts/find_sign_locations.py --no-osm         # use cached only

Performance: ~30-90s per uncached county (~60-90 min for full statewide).
Cached re-runs: ~5 min total. Cache: data/clean/_osmnx_cache/
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import warnings
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
DEFAULT_TARGET = 3000
CACHE_DIR = "data/clean/_osmnx_cache"

# ──────────────────────────────────────────────────────────────────────────────
# CHAIN BLOCKLIST — corporate-controlled, refuse political signs
# Case-insensitive substring match against `name` tag.
# Tractor Supply intentionally NOT here — owner-operated stores often say yes.
# ──────────────────────────────────────────────────────────────────────────────
CHAIN_BLOCKLIST = {
    # Hardware big-box (corporate)
    "lowe's", "lowes", "home depot", "menards",
    # Tire / auto chains (corporate-controlled)
    "discount tire", "firestone", "pep boys",
    # General big-box retail (corporate)
    "walmart", "wal-mart", "target", "costco", "sam's club", "sams club",
    "bj's", "bjs wholesale", "big lots", "ikea", "best buy",
    # Grocery (no political sign policy)
    "kroger", "publix", "winn-dixie", "winn dixie", "whole foods", "trader joe's",
    "aldi", "save-a-lot", "fresco y mas",
    # Dollar stores (corporate)
    "dollar general", "dollar tree", "family dollar", "five below",
    # Outdoor big-box (corporate, tho some franchise mgrs flexible)
    "bass pro shops", "cabela's",
    # Gas station chains where sign refusal is corporate policy
    "wawa", "racetrac", "circle k", "7-eleven", "7 eleven", "sheetz", "buc-ee's",
    # Pharmacy chains (covered by exclusion but doubled here for safety)
    "cvs", "walgreens", "rite aid",
    # Auto chains worth dropping (corporate or near-100%-corporate)
    "jiffy lube",
}

# ──────────────────────────────────────────────────────────────────────────────
# OSM TAG BUNDLES
# ──────────────────────────────────────────────────────────────────────────────
# At-grade traffic intersections only. Motorway_junction = interstate ramps,
# not sign-able. Stop signs = often dirt-road and not worth the effort but
# include for very rural fill.
INTERSECTION_TAGS = {"highway": ["traffic_signals", "stop"]}

# Commercial: small business, owner-operated, mid road frontage.
# EXPLICITLY EXCLUDED here (per user + strategist):
#   - amenity=place_of_worship   (501c3 risk)
#   - amenity=school/college/university/kindergarten   (FL law)
#   - amenity=post_office/fire_station/townhall/library/courthouse/police   (govt)
#   - amenity=bank/atm   (corporate policy)
#   - amenity=pharmacy   (corporate policy)
#   - amenity=hospital/clinic/doctors   (sensitivity)
#   - shop=funeral_directors   (sensitivity)
#   - shop=chemist/supermarket   (corporate)
#   - office=government/lawyer/accountant   (sensitivity)
COMMERCIAL_TAGS = {
    "amenity": [
        # Restaurants (filter chains via blocklist)
        "fuel", "restaurant", "fast_food", "bar", "pub", "biergarten", "cafe",
        # Civic but NOT govt
        "community_centre",
        # Animal services — small biz, often vocal owners
        "veterinary",
    ],
    "shop": [
        # Auto / tires / motorcycle / RV
        "car_repair", "tyres", "car", "motorcycle", "boat", "atv", "snowmobile",
        # Hardware / DIY (independent)
        "hardware", "doityourself",
        # Real estate / insurance (independent agents)
        "real_estate_agent",
        # Outdoor / hunting / firearms — strong base alignment
        "hunting", "fishing", "outdoor", "guns", "weapons", "sports",
        # Lifestyle base-aligned
        "alcohol", "tobacco", "antiques", "second_hand", "pawnbroker",
        # Misc small-biz
        "trade", "garden_centre", "convenience",
    ],
    "office": [
        "real_estate", "insurance",
    ],
    # Trades — contractor yards, often have visible road frontage
    "craft": [
        "roofer", "carpenter", "electrician", "plumber", "painter", "hvac",
        "blacksmith", "gardener", "tiler", "sawmill", "agricultural_engines",
        "metal_construction", "scaffolder",
    ],
    # Veterans / hunting / social clubs — extremely high political sign yes-rate
    "club": ["veterans", "hunting", "social", "sport"],
    # Marinas, RV parks, campgrounds, private resorts
    "leisure": ["marina", "resort", "sports_centre"],
    "tourism": ["camp_site", "caravan_site"],
}

# Agri / civic — rural strongholds.
AGRI_CIVIC_TAGS = {
    "shop": ["agrarian", "farm", "country_store"],
    "amenity": ["fairground", "marketplace"],
    "landuse": ["farmland", "farmyard", "orchard", "vineyard"],
    "tourism": ["attraction"],
}

# How candidate slots are split per county. Sums to 1.0.
# Tier-aware: D-tier (rural) leans agri/civic, A-tier (urban) leans commercial.
MIX_DEFAULT = {"agri_civic": 0.20, "commercial": 0.55, "intersection": 0.25}
MIX_RURAL_D = {"agri_civic": 0.30, "commercial": 0.50, "intersection": 0.20}
MIX_URBAN_A = {"agri_civic": 0.10, "commercial": 0.65, "intersection": 0.25}

# ──────────────────────────────────────────────────────────────────────────────
# CATEGORY SCORING — strategist's owner-yes-rate ranking
# 10 = ~80% yes-rate; 1 = corporate refusal expected.
# ──────────────────────────────────────────────────────────────────────────────
COMMERCIAL_PRIORITY = {
    # S-tier — VFW posts, gun shops, hunting / fishing — base lock
    "veterans":          10,
    "guns":              10,
    "weapons":           10,
    "hunting":            9,
    "fishing":            9,
    "outdoor":            8,
    # A-tier — rural ag-aligned independents, marinas, RV parks
    "marina":             8,
    "caravan_site":       8,
    "camp_site":          8,
    "resort":             7,
    "agrarian":           8,
    "country_store":      8,
    "farm":               7,
    "boat":               8,
    "motorcycle":         8,
    "atv":                8,
    "snowmobile":         8,
    # B-tier — independent commercial with road frontage
    "hardware":           7,
    "doityourself":       6,
    "antiques":           7,
    "second_hand":        6,
    "alcohol":            7,
    "tobacco":            7,
    "real_estate_agent":  6,
    "real_estate":        6,
    "car":                7,    # car dealers (used lots score higher in select)
    "car_repair":         6,
    "tyres":              5,
    "trade":              7,
    "garden_centre":      6,
    "veterinary":         5,
    # Bars / pubs — strong owner discretion
    "bar":                7,
    "pub":                7,
    "biergarten":         7,
    # Restaurants — filter chains via blocklist
    "restaurant":         5,
    "fast_food":          3,    # mostly chains; blocklist will trim
    "cafe":               4,
    # Crafts (contractors)
    "roofer":             7,
    "carpenter":          7,
    "electrician":        7,
    "plumber":            7,
    "painter":            6,
    "hvac":               6,
    "blacksmith":         6,
    "gardener":           6,
    "tiler":              5,
    "sawmill":            7,
    "agricultural_engines":8,
    "metal_construction": 6,
    "scaffolder":         5,
    # Clubs
    "social":             6,
    "sport":              5,
    # Misc
    "convenience":        3,    # most are chains
    "fuel":               2,    # franchise gas stations: low yield
    "pawnbroker":         5,
    "insurance":          4,
    "community_centre":   5,
    "sports":             5,
    "sports_centre":      5,
}

INTERSECTION_PRIORITY = {
    "traffic_signals":    5,
    "stop":               2,
}

AGRI_CIVIC_PRIORITY = {
    "fairground":         8,
    "marketplace":        7,
    "country_store":      8,
    "agrarian":           8,
    "farm":               7,
    "farmland":           4,
    "farmyard":           5,
    "orchard":            6,
    "vineyard":           6,
    "attraction":         4,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Find candidate 4x8 sign locations from OSM (V3 strategist).")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--target", type=int, default=DEFAULT_TARGET,
                   help=f"Total target candidates statewide (default: {DEFAULT_TARGET})")
    p.add_argument("--counties", nargs="*", default=None,
                   help="Subset by county name. Default: all 67 from County_Master.")
    p.add_argument("--no-osm", action="store_true",
                   help="Don't hit OSM at all; use cache only.")
    p.add_argument("--min-per-county", type=int, default=10,
                   help="Floor per county regardless of tier (default: 10).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        warnings.filterwarnings("ignore")
        import pandas as pd
        import osmnx as ox
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    if not master.exists():
        print(f"ERROR: master not found: {master}", file=sys.stderr)
        return 1

    cache = Path(CACHE_DIR)
    cache.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(cache)
    if args.no_osm:
        ox.settings.requests_timeout = 1

    cm = mio.read_sheet_safe(master, "County_Master")
    if cm.empty:
        print("ERROR: County_Master sheet empty in master.", file=sys.stderr)
        return 1

    cm["County"] = cm["County"].astype(str).str.strip()
    cm["Suggested 4x8 Goal"] = pd.to_numeric(cm["Suggested 4x8 Goal"], errors="coerce").fillna(0)
    total_goal = cm["Suggested 4x8 Goal"].sum()
    if total_goal <= 0:
        print("ERROR: Suggested 4x8 Goal sums to zero; can't allocate.", file=sys.stderr)
        return 1
    oversample = args.target / total_goal
    print(f"Target: {args.target} candidates  /  Boss's 4x8 goal: {int(total_goal)}  /  Oversample: {oversample:.2f}x")

    cm["__quota__"] = (cm["Suggested 4x8 Goal"] * oversample).apply(math.ceil).clip(lower=args.min_per_county).astype(int)

    if args.counties:
        wanted = {c.strip().lower() for c in args.counties}
        cm = cm[cm["County"].str.lower().isin(wanted)]
        if cm.empty:
            print(f"ERROR: no counties matched {args.counties}", file=sys.stderr)
            return 1
    print(f"Counties to process: {len(cm)}\n")

    all_candidates: list[dict] = []
    counter = {"id": 0}

    for idx, (_, row) in enumerate(cm.iterrows(), start=1):
        county = row["County"]
        tier = row.get("Strategic Tier", "")
        quota = int(row["__quota__"])
        place = f"{county} County, Florida, USA"
        print(f"[{idx:>2}/{len(cm)}] {county:18s} tier={tier} quota={quota:3d}", end=" ", flush=True)
        t0 = time.time()
        try:
            cands = collect_county_candidates(ox, pd, place, county, tier, quota, counter)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        all_candidates.extend(cands)
        print(f"-> {len(cands)} cands ({time.time()-t0:.1f}s)")

    if not all_candidates:
        print("\nNo candidates collected.")
        return 1

    df = pd.DataFrame(all_candidates)

    # Dedup by (Lat, Lon) to 5 decimals.
    before = len(df)
    df["__lat5__"] = df["Lat"].round(5)
    df["__lon5__"] = df["Lon"].round(5)
    df = df.drop_duplicates(subset=["__lat5__", "__lon5__"], keep="first")
    df = df.drop(columns=["__lat5__", "__lon5__"])
    if len(df) < before:
        print(f"\nDeduped {before - len(df)} coordinate clashes.")

    df["Maps_Link"] = df.apply(
        lambda r: f"https://www.google.com/maps?q={r['Lat']},{r['Lon']}"
        if pd.notna(r.get("Lat")) and pd.notna(r.get("Lon")) else "", axis=1)

    cols = ["Candidate_ID", "County", "Tier", "Type", "Category",
            "Name", "Address", "Lat", "Lon", "Maps_Link", "Score",
            "OSM_Element", "OSM_ID", "OSM_URL", "OSM_Tags_JSON",
            "Phone", "Phone_Source", "Email", "Email_Source",
            "Website", "Website_Source", "POC_Status",
            "Google_Search_URL", "Yelp_Search_URL", "Sunbiz_Search_URL",
            "Field_Status", "Owner_Contact", "Notes"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols]
    df = df.sort_values(["Tier", "County", "Score"], ascending=[True, True, False]).reset_index(drop=True)

    print(f"\nTotal candidates: {len(df)}")
    print("\nBy Tier:")
    print(df["Tier"].value_counts().sort_index().to_string())
    print("\nBy Type:")
    print(df["Type"].value_counts().to_string())

    print(f"\nWriting Sign_Location_Candidates to {master} ...")
    mio.replace_sheet(master, "Sign_Location_Candidates", df,
                      color_col="Type",
                      color_map={
                          "intersection": "EAF3FB",
                          "commercial":   "FFF8E1",
                          "agri_civic":   "E8F5E9",
                      })
    print("Done.")
    return 0


def collect_county_candidates(ox, pd, place, county, tier, quota, counter) -> list[dict]:
    """Pull OSM features for one county, score, allocate per the MIX."""
    if str(tier).upper() == "D":
        mix = MIX_RURAL_D
    elif str(tier).upper() == "A":
        mix = MIX_URBAN_A
    else:
        mix = MIX_DEFAULT

    n_agri  = max(1, int(quota * mix["agri_civic"]))
    n_comm  = max(1, int(quota * mix["commercial"]))
    n_inter = quota - n_agri - n_comm

    out: list[dict] = []

    # 1) Agri / civic
    agri_df = _safe_features(ox, place, AGRI_CIVIC_TAGS)
    agri_df = _drop_blocklisted(agri_df)
    agri_picks = pick_agri_civic(agri_df, n_agri)
    overflow_to_commercial = max(0, n_agri - len(agri_picks))
    n_comm += overflow_to_commercial
    for _, r in agri_picks.iterrows():
        cat = _category(r, AGRI_CIVIC_TAGS)
        score = AGRI_CIVIC_PRIORITY.get(cat, 4)
        out.append(_to_candidate(r, county, tier, "agri_civic", cat, score, counter))

    # 2) Commercial
    comm_df = _safe_features(ox, place, COMMERCIAL_TAGS)
    comm_df = _drop_blocklisted(comm_df)
    comm_picks = pick_commercial(comm_df, n_comm)
    overflow_to_inter = max(0, n_comm - len(comm_picks))
    n_inter += overflow_to_inter
    for _, r in comm_picks.iterrows():
        cat = _category(r, COMMERCIAL_TAGS)
        out.append(_to_candidate(r, county, tier, "commercial", cat,
                                 COMMERCIAL_PRIORITY.get(cat, 1), counter))

    # 3) Intersections
    inter_df = _safe_features(ox, place, INTERSECTION_TAGS)
    inter_picks = pick_intersections(inter_df, n_inter)
    for _, r in inter_picks.iterrows():
        cat = _category(r, INTERSECTION_TAGS)
        out.append(_to_candidate(r, county, tier, "intersection", cat,
                                 INTERSECTION_PRIORITY.get(cat, 1), counter))

    return out


def _drop_blocklisted(df):
    """Drop rows whose Name matches any chain in CHAIN_BLOCKLIST (case-insensitive)."""
    import pandas as pd
    if df is None or df.empty or "name" not in df.columns:
        return df
    name_lower = df["name"].astype(str).str.lower()
    blocked = pd.Series(False, index=df.index)
    for token in CHAIN_BLOCKLIST:
        blocked = blocked | name_lower.str.contains(token, regex=False, na=False)
    return df[~blocked]


def _safe_features(ox, place, tags):
    import pandas as pd
    try:
        return ox.features_from_place(place, tags=tags)
    except Exception:
        return pd.DataFrame()


def _category(row, tags) -> str:
    """Return the matched tag value (e.g. 'fuel', 'farm', 'traffic_signals')."""
    for tag_key in tags:
        v = row.get(tag_key) if tag_key in row.index else None
        allowed = tags[tag_key] if isinstance(tags[tag_key], list) else [tags[tag_key]]
        if isinstance(v, str) and v in allowed:
            return v
    for tag_key in tags:
        v = row.get(tag_key) if tag_key in row.index else None
        if isinstance(v, str) and v and v != "yes":
            return v
    return "unknown"


def _extract_tags_dict(row) -> dict:
    """Capture the full OSM tag dict for downstream POC enrichment."""
    keep_keys = {
        "name", "phone", "contact:phone", "phone:mobile", "phone:1", "contact:mobile",
        "email", "contact:email",
        "website", "contact:website", "url", "contact:url",
        "facebook", "contact:facebook", "twitter", "contact:twitter", "instagram",
        "addr:housenumber", "addr:street", "addr:city", "addr:state", "addr:postcode",
        "opening_hours", "operator", "brand", "ref",
    }
    out: dict = {}
    for k in keep_keys:
        if k in row.index:
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
    return out


def _to_candidate(row, county, tier, type_, category, score, counter) -> dict:
    counter["id"] += 1
    cid = f"SLC-{counter['id']:05d}"

    name = row.get("name") if "name" in row.index else None
    if not isinstance(name, str) or not name.strip():
        ref = row.get("ref") if "ref" in row.index else None
        if isinstance(ref, str) and ref.strip():
            name = f"{category} on {ref.strip()}"
        else:
            name = f"{category} (see Maps_Link)"

    parts = []
    for k in ("addr:housenumber", "addr:street"):
        v = row.get(k) if k in row.index else None
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    street = " ".join(parts)
    city = row.get("addr:city") if "addr:city" in row.index else None
    state = row.get("addr:state") if "addr:state" in row.index else None
    addr_parts = [p for p in [street, city, state] if isinstance(p, str) and p.strip()]
    address = ", ".join(addr_parts)

    geom = row.geometry if hasattr(row, "geometry") else None
    lat, lon = None, None
    if geom is not None and not geom.is_empty:
        c = geom.centroid
        lat, lon = round(c.y, 6), round(c.x, 6)

    osm_element, osm_id = "", ""
    if hasattr(row, "name") and isinstance(row.name, tuple) and len(row.name) == 2:
        osm_element, osm_id = row.name
    osm_url = ""
    if osm_element and osm_id:
        osm_url = f"https://www.openstreetmap.org/{osm_element}/{osm_id}"

    tags = _extract_tags_dict(row)
    tags_json = json.dumps(tags, ensure_ascii=False) if tags else ""

    return {
        "Candidate_ID": cid,
        "County": county,
        "Tier": tier,
        "Type": type_,
        "Category": category,
        "Name": name,
        "Address": address,
        "Lat": lat,
        "Lon": lon,
        "Score": score,
        "OSM_Element": osm_element,
        "OSM_ID": str(osm_id) if osm_id else "",
        "OSM_URL": osm_url,
        "OSM_Tags_JSON": tags_json,
        "Phone": "",
        "Phone_Source": "",
        "Email": "",
        "Email_Source": "",
        "Website": "",
        "Website_Source": "",
        "POC_Status": "",
        "Google_Search_URL": "",
        "Yelp_Search_URL": "",
        "Sunbiz_Search_URL": "",
        "Field_Status": "",
        "Owner_Contact": "",
        "Notes": "",
    }


def pick_agri_civic(df, n):
    if df is None or df.empty:
        return df.iloc[0:0] if df is not None else None
    if "name" not in df.columns:
        return df.head(0)
    d = df.copy()
    d = d[d["name"].notna() & (d["name"].astype(str).str.strip() != "")]
    if d.empty:
        return d
    has_addr = d["addr:street"].notna() if "addr:street" in d.columns else False
    d = d.assign(__has_addr__=has_addr.astype(int) if hasattr(has_addr, "astype") else 0)

    def row_score(r):
        for col in ("amenity", "shop", "landuse", "tourism"):
            if col in d.columns:
                v = r.get(col)
                if isinstance(v, str) and v in AGRI_CIVIC_PRIORITY:
                    return AGRI_CIVIC_PRIORITY[v]
        return 1
    d = d.assign(__cat_score__=d.apply(row_score, axis=1))
    d = d.sort_values(["__cat_score__", "__has_addr__"], ascending=[False, False])
    return d.head(n)


def pick_commercial(df, n):
    """Prefer named POIs, ranked by COMMERCIAL_PRIORITY. Diversity cap 35%."""
    if df is None or df.empty:
        return df.iloc[0:0] if df is not None else None
    d = df.copy()
    if "name" not in d.columns:
        return d.head(0)
    d = d[d["name"].notna() & (d["name"].astype(str).str.strip() != "")]
    if d.empty:
        return d

    def category_of(r):
        for col in ("amenity", "shop", "office", "craft", "club", "leisure", "tourism"):
            if col in d.columns:
                v = r.get(col)
                if isinstance(v, str) and v in COMMERCIAL_PRIORITY:
                    return v
        return "unknown"

    d = d.assign(
        __cat__=d.apply(category_of, axis=1),
        __score__=d.apply(lambda r: COMMERCIAL_PRIORITY.get(category_of(r), 0), axis=1),
    )
    d = d.sort_values("__score__", ascending=False)

    cap_per_cat = max(2, int(n * 0.35))
    picks = []
    cat_count: dict = {}
    for _, row in d.iterrows():
        cat = row["__cat__"]
        if cat_count.get(cat, 0) >= cap_per_cat:
            continue
        picks.append(row)
        cat_count[cat] = cat_count.get(cat, 0) + 1
        if len(picks) >= n:
            break

    if len(picks) < n:
        remaining_idx = set(d.index) - {p.name for p in picks}
        for idx in d.loc[list(remaining_idx)].sort_values("__score__", ascending=False).index:
            picks.append(d.loc[idx])
            if len(picks) >= n:
                break

    if not picks:
        return d.head(0)
    import pandas as pd
    return pd.DataFrame(picks)


def pick_intersections(df, n):
    if df is None or df.empty:
        return df.iloc[0:0] if df is not None else None
    d = df.copy()
    if "highway" not in d.columns:
        return d.head(0)
    def row_score(r):
        v = r.get("highway")
        if isinstance(v, str):
            return INTERSECTION_PRIORITY.get(v, 0)
        return 0
    d = d.assign(__score__=d.apply(row_score, axis=1))
    return d.sort_values("__score__", ascending=False).head(n)


if __name__ == "__main__":
    sys.exit(main())
