#!/usr/bin/env python3
"""
Highway-corridor enrichment for Sign_Location_Candidates (per-county pulls).

For each FL county:
  1. Pull motorway/trunk/primary road geometry from OSM (cached after first run)
  2. Filter to just the major routes we care about (interstates, US routes,
     and major state highways -- captured via highway tag, not ref)
  3. Buffer by 500m (or --buffer-m)
  4. Mark existing SLC rows in that county as Highway_Adjacent if inside the buffer
  5. Pull NEW commercial POIs inside the buffer that aren't already in SLC

Per-county queries are small and cache well. Total runtime: ~5-15 min for all 67.

Usage:
    python scripts/find_highway_candidates.py
    python scripts/find_highway_candidates.py --counties Hillsborough Orange
    python scripts/find_highway_candidates.py --no-add  # only flag existing
    python scripts/find_highway_candidates.py --buffer-m 500
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
DEFAULT_BUFFER = 500
CACHE_DIR = "data/clean/_osmnx_cache"

# Major Florida road refs we care about for "highway-adjacent" classification.
# Used only for naming Nearest_Highway; the actual buffer comes from
# motorway+trunk+primary OSM geometries.
PREFERRED_REFS = {
    "I 4", "I 10", "I 75", "I 95", "I 110", "I 275", "I 295", "I 595",
    "US 1", "US 17", "US 19", "US 27", "US 41", "US 90", "US 92", "US 98",
    "US 129", "US 192", "US 221", "US 231", "US 301", "US 319", "US 331", "US 441",
}

ROAD_TAGS = {"highway": ["motorway", "trunk", "primary"]}

# Tag bundle for highway-adjacent commercial POI pull (high-yes-rate categories
# with road frontage).
HIGHWAY_POI_TAGS = {
    "amenity": ["fuel", "restaurant", "fast_food", "bar", "pub"],
    "shop": [
        "car", "car_repair", "tyres", "motorcycle", "boat",
        "hardware", "doityourself", "outdoor", "hunting", "fishing",
        "guns", "alcohol", "tobacco", "antiques", "agrarian", "country_store",
    ],
    "leisure": ["marina", "resort"],
    "tourism": ["camp_site", "caravan_site"],
    "club": ["veterans", "hunting"],
    "craft": ["roofer", "carpenter", "agricultural_engines", "sawmill"],
}

CHAIN_BLOCKLIST = {
    "lowe's", "lowes", "home depot", "menards",
    "discount tire", "firestone", "pep boys",
    "walmart", "wal-mart", "target", "costco", "sam's club", "sams club",
    "bj's", "bjs wholesale", "big lots", "ikea", "best buy",
    "kroger", "publix", "winn-dixie", "winn dixie", "whole foods", "trader joe's",
    "aldi", "save-a-lot", "fresco y mas",
    "dollar general", "dollar tree", "family dollar", "five below",
    "bass pro shops", "cabela's",
    "wawa", "racetrac", "circle k", "7-eleven", "7 eleven", "sheetz", "buc-ee's",
    "cvs", "walgreens", "rite aid",
    "jiffy lube",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Highway-corridor enrichment (per-county).")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--buffer-m", type=int, default=DEFAULT_BUFFER)
    p.add_argument("--counties", nargs="*", default=None)
    p.add_argument("--no-add", action="store_true",
                   help="Only mark existing rows; don't add new candidates.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        warnings.filterwarnings("ignore")
        import pandas as pd
        import osmnx as ox
        import geopandas as gpd
        from shapely.geometry import Point
        from shapely.ops import unary_union
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}).", file=sys.stderr)
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

    slc = mio.read_sheet_safe(master, "Sign_Location_Candidates")
    if slc.empty:
        print("ERROR: Sign_Location_Candidates is empty.", file=sys.stderr)
        return 1
    print(f"Loaded {len(slc)} existing candidates.", flush=True)

    # Ensure new columns exist
    if "Highway_Adjacent" not in slc.columns:
        slc["Highway_Adjacent"] = False
    if "Nearest_Highway" not in slc.columns:
        slc["Nearest_Highway"] = ""

    # Counties to process
    counties_in_slc = sorted(slc["County"].dropna().unique().tolist())
    if args.counties:
        wanted = {c.strip().lower() for c in args.counties}
        counties_in_slc = [c for c in counties_in_slc if c.lower() in wanted]
    print(f"Processing {len(counties_in_slc)} counties.\n", flush=True)

    counter = {"id": _max_existing_id(slc)}
    new_rows: list[dict] = []
    total_marked = 0
    total_added = 0

    for idx, county in enumerate(counties_in_slc, start=1):
        place = f"{county} County, Florida, USA"
        t0 = time.time()
        print(f"[{idx:>2}/{len(counties_in_slc)}] {county:18s}", end=" ", flush=True)
        try:
            roads = ox.features_from_place(place, tags=ROAD_TAGS)
        except Exception as e:
            print(f"  no roads ({e})", flush=True)
            continue
        if roads is None or roads.empty:
            print(f"  no roads", flush=True)
            continue

        # Build buffer (in metric CRS)
        try:
            roads_metric = roads.to_crs("EPSG:3857")
            buffered_metric = unary_union(roads_metric.buffer(args.buffer_m).values)
            buffered_4326 = (
                gpd.GeoSeries([buffered_metric], crs="EPSG:3857")
                .to_crs("EPSG:4326").iloc[0]
            )
        except Exception as e:
            print(f"  buffer fail ({e})", flush=True)
            continue

        # Pick a representative ref name for each row by nearest-highway logic
        # (we use a quick spatial-index approach: only relevant when a row falls
        # in the buffer; we then check which preferred-ref road is closest)
        ref_geoms = []
        if "ref" in roads.columns:
            for _, rrow in roads.iterrows():
                ref_val = rrow.get("ref")
                if isinstance(ref_val, str) and ref_val.strip():
                    # Sometimes refs come as "I 75;US 41" — split and keep first preferred
                    for r in ref_val.split(";"):
                        r = r.strip()
                        if r in PREFERRED_REFS:
                            ref_geoms.append((r, rrow.geometry))
                            break

        # Mark existing SLC rows in this county
        mask = slc["County"] == county
        county_slc = slc[mask]
        marked_here = 0
        for sidx, srow in county_slc.iterrows():
            lat = srow.get("Lat")
            lon = srow.get("Lon")
            if lat is None or lon is None:
                continue
            try:
                p = Point(float(lon), float(lat))
            except (TypeError, ValueError):
                continue
            if not buffered_4326.contains(p):
                continue
            slc.at[sidx, "Highway_Adjacent"] = True
            # Find nearest preferred ref
            best_name = ""
            best_d = float("inf")
            for ref_name, geom in ref_geoms:
                try:
                    d = p.distance(geom)
                    if d < best_d:
                        best_d = d
                        best_name = ref_name
                except Exception:
                    continue
            slc.at[sidx, "Nearest_Highway"] = best_name
            marked_here += 1
        total_marked += marked_here

        # Pull additional commercial features inside the buffer
        added_here = 0
        if not args.no_add:
            try:
                feats = ox.features_from_polygon(buffered_4326, tags=HIGHWAY_POI_TAGS)
            except Exception as e:
                feats = None
            if feats is not None and not feats.empty:
                feats = _drop_blocklisted(feats)
                if "name" in feats.columns:
                    feats = feats[feats["name"].notna() &
                                  (feats["name"].astype(str).str.strip() != "")]
                existing_keys = set(zip(slc["Lat"].round(5), slc["Lon"].round(5)))
                for _, frow in feats.iterrows():
                    geom = frow.geometry if hasattr(frow, "geometry") else None
                    if geom is None or geom.is_empty:
                        continue
                    c = geom.centroid
                    lat, lon = round(c.y, 6), round(c.x, 6)
                    if (round(lat, 5), round(lon, 5)) in existing_keys:
                        continue
                    cat = _category_of(frow)
                    # Pick nearest preferred ref for this new candidate
                    nearest_name = ""
                    best_d = float("inf")
                    pt = Point(float(lon), float(lat))
                    for ref_name, geom_ref in ref_geoms:
                        try:
                            d = pt.distance(geom_ref)
                            if d < best_d:
                                best_d = d
                                nearest_name = ref_name
                        except Exception:
                            continue
                    tier = _tier_for_county(slc, county)
                    cand = _to_candidate(frow, county, tier, cat, counter, nearest_name)
                    new_rows.append(cand)
                    existing_keys.add((round(lat, 5), round(lon, 5)))
                    added_here += 1
        total_added += added_here

        print(f"marked={marked_here:3d} added={added_here:3d} ({time.time()-t0:.1f}s)", flush=True)

    # Append new rows to SLC
    if new_rows:
        new_df = _new_rows_df(new_rows, slc.columns.tolist())
        slc = pd.concat([slc, new_df], ignore_index=True)
        before = len(slc)
        slc["__lat5__"] = slc["Lat"].round(5)
        slc["__lon5__"] = slc["Lon"].round(5)
        slc = slc.drop_duplicates(subset=["__lat5__", "__lon5__"], keep="first")
        slc = slc.drop(columns=["__lat5__", "__lon5__"])
        if len(slc) < before:
            print(f"\nDeduped {before - len(slc)} clashes after append.")

    # Stats
    n_adj = int(slc["Highway_Adjacent"].fillna(False).astype(bool).sum())
    print(f"\nTotal Highway_Adjacent: {n_adj}/{len(slc)} ({n_adj/len(slc):.0%})")
    print(f"  Marked existing rows: {total_marked}")
    print(f"  Added new candidates: {total_added}")
    by_hwy = slc[slc["Highway_Adjacent"] == True]["Nearest_Highway"].value_counts()
    print(f"\nBy nearest highway (top 10):")
    print(by_hwy.head(10).to_string())

    print(f"\nWriting Sign_Location_Candidates to {master} ...")
    mio.replace_sheet(master, "Sign_Location_Candidates", slc,
                      color_col="Type",
                      color_map={
                          "intersection": "EAF3FB",
                          "commercial":   "FFF8E1",
                          "agri_civic":   "E8F5E9",
                      })
    print("Done.")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _drop_blocklisted(df):
    import pandas as pd
    if df is None or df.empty or "name" not in df.columns:
        return df
    name_lower = df["name"].astype(str).str.lower()
    blocked = pd.Series(False, index=df.index)
    for token in CHAIN_BLOCKLIST:
        blocked = blocked | name_lower.str.contains(token, regex=False, na=False)
    return df[~blocked]


def _category_of(row) -> str:
    for col in ("amenity", "shop", "leisure", "tourism", "club", "craft"):
        if col in row.index:
            v = row.get(col)
            if isinstance(v, str) and v.strip() and v != "yes":
                return v
    return "unknown"


def _tier_for_county(slc, county: str) -> str:
    sub = slc[slc["County"] == county]
    if sub.empty:
        return "D"
    val = sub.iloc[0].get("Tier", "D")
    return str(val).strip().upper() or "D"


def _max_existing_id(slc) -> int:
    if slc.empty or "Candidate_ID" not in slc.columns:
        return 0
    nums = []
    for cid in slc["Candidate_ID"].dropna().astype(str):
        if cid.startswith("SLC-"):
            try:
                nums.append(int(cid.split("-", 1)[1]))
            except ValueError:
                pass
    return max(nums) if nums else 0


def _to_candidate(row, county, tier, category, counter, highway_name) -> dict:
    counter["id"] += 1
    cid = f"SLC-{counter['id']:05d}"

    name = row.get("name") if "name" in row.index else None
    if not isinstance(name, str) or not name.strip():
        name = f"{category} (highway corridor)"

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

    keep_keys = {
        "name", "phone", "contact:phone", "phone:mobile", "phone:1", "contact:mobile",
        "email", "contact:email",
        "website", "contact:website", "url", "contact:url",
        "addr:housenumber", "addr:street", "addr:city", "addr:state", "addr:postcode",
        "opening_hours", "operator", "brand",
    }
    tags = {}
    for k in keep_keys:
        if k in row.index:
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                tags[k] = v.strip()
    tags_json = json.dumps(tags, ensure_ascii=False) if tags else ""

    return {
        "Candidate_ID": cid,
        "County": county,
        "Tier": tier,
        "Type": "commercial",
        "Category": category,
        "Name": name,
        "Address": address,
        "Lat": lat,
        "Lon": lon,
        "Maps_Link": f"https://www.google.com/maps?q={lat},{lon}" if lat else "",
        "Score": 7,
        "OSM_Element": osm_element,
        "OSM_ID": str(osm_id) if osm_id else "",
        "OSM_URL": osm_url,
        "OSM_Tags_JSON": tags_json,
        "Phone": "", "Phone_Source": "",
        "Email": "", "Email_Source": "",
        "Website": "", "Website_Source": "",
        "POC_Status": "",
        "Google_Search_URL": "", "Yelp_Search_URL": "", "Sunbiz_Search_URL": "",
        "Field_Status": "", "Owner_Contact": "", "Notes": "",
        "Highway_Adjacent": True,
        "Nearest_Highway": highway_name,
    }


def _new_rows_df(rows, target_columns):
    import pandas as pd
    df = pd.DataFrame(rows)
    for c in target_columns:
        if c not in df.columns:
            df[c] = ""
    return df[target_columns]


if __name__ == "__main__":
    sys.exit(main())
