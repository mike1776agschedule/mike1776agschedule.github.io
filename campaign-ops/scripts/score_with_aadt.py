#!/usr/bin/env python3
"""
Score Sign_Location_Candidates by Florida DOT Annual Average Daily Traffic
(AADT) — vehicles per day on the nearest road segment.

Source: FDOT publishes AADT as a public ArcGIS feature service:
  https://gis-fdot.opendata.arcgis.com/

This script:
  1. Downloads (or reads cached) FDOT AADT segments as GeoJSON
  2. For each candidate row in Sign_Location_Candidates, finds the nearest
     AADT segment within --max-distance-m meters
  3. Writes back columns: AADT, AADT_Year, AADT_Road, AADT_Distance_M

Cache: data/clean/_fdot_aadt.geojson (one-time ~10-50 MB download)

Usage:
    python scripts/score_with_aadt.py
    python scripts/score_with_aadt.py --shapefile /path/to/aadt.shp
    python scripts/score_with_aadt.py --max-distance-m 500
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
CACHE_PATH = "data/clean/_fdot_aadt.geojson"

# FDOT AADT public ArcGIS REST endpoint. RCI_Layers/FeatureServer/0 is the
# current "Annual Average Daily Traffic TDA" layer per FDOT Open Data Hub.
FDOT_ENDPOINTS = [
    "https://gis.fdot.gov/arcgis/rest/services/RCI_Layers/FeatureServer/0",
    # Fallbacks
    "https://gis.fdot.gov/arcgis/rest/services/Traffic/AADT/MapServer/0",
    "https://gis.fdot.gov/arcgis/rest/services/Traffic/AADTS/MapServer/0",
]

PAGE_SIZE = 1000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score candidates by FDOT AADT.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--shapefile", default=None,
                   help="Optional local AADT shapefile (.shp). "
                        "If omitted, tries to download from FDOT.")
    p.add_argument("--cache", default=CACHE_PATH,
                   help="Local GeoJSON cache (default: data/clean/_fdot_aadt.geojson).")
    p.add_argument("--max-distance-m", type=int, default=300,
                   help="Max meters from candidate to road segment (default: 300).")
    p.add_argument("--force-download", action="store_true",
                   help="Re-download even if cache exists.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        warnings.filterwarnings("ignore")
        import pandas as pd
        import geopandas as gpd
        import httpx
        from shapely.geometry import Point
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}).", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    if not master.exists():
        print(f"ERROR: master not found: {master}", file=sys.stderr)
        return 1

    # ── Load AADT geometry ────────────────────────────────────────────────────
    aadt = None
    if args.shapefile:
        sp = Path(args.shapefile)
        if not sp.exists():
            print(f"ERROR: shapefile not found: {sp}", file=sys.stderr)
            return 1
        print(f"Loading AADT from local shapefile: {sp}")
        aadt = gpd.read_file(sp)
    else:
        cache_path = Path(args.cache)
        if cache_path.exists() and not args.force_download:
            print(f"Loading AADT from cache: {cache_path}")
            aadt = gpd.read_file(cache_path)
        else:
            print("Downloading AADT from FDOT public ArcGIS REST ...")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            aadt = _download_aadt_paged(httpx, gpd, FDOT_ENDPOINTS, cache_path)
            if aadt is None:
                print("\nFDOT auto-download failed. Manual fallback:", file=sys.stderr)
                print("  1. Visit: https://gis-fdot.opendata.arcgis.com/", file=sys.stderr)
                print("  2. Search 'AADT' or 'Annual Average Daily Traffic'", file=sys.stderr)
                print("  3. Download as shapefile to data/raw/aadt.shp", file=sys.stderr)
                print("  4. Re-run: python scripts/score_with_aadt.py --shapefile data/raw/aadt.shp",
                      file=sys.stderr)
                return 1

    if aadt is None or aadt.empty:
        print("ERROR: AADT layer is empty.", file=sys.stderr)
        return 1

    print(f"Loaded {len(aadt):,} AADT segments.")

    # Normalize column names — FDOT field names vary across publications
    aadt_col = _detect_column(aadt, ["AADT", "AADT_NUM", "AADT_2023", "AADT_2022", "AADT_2021", "AADT_VAL"])
    year_col = _detect_column(aadt, ["YEAR_", "YEAR", "AADT_YEAR", "DATA_YEAR"])
    road_col = _detect_column(aadt, ["ROADWAY", "ROAD_NAME", "ROADNAME", "DESC_FROM", "ROAD", "NAME", "SR_NAME"])

    if aadt_col is None:
        print(f"WARN: could not detect AADT column. Available: {list(aadt.columns)[:20]}", file=sys.stderr)
        print("Continuing — AADT values will be 0.", file=sys.stderr)

    print(f"  AADT column: {aadt_col}")
    print(f"  Year column: {year_col}")
    print(f"  Road column: {road_col}")

    # Reproject to metric CRS for distance math
    if aadt.crs is None:
        aadt = aadt.set_crs("EPSG:4326")
    aadt_m = aadt.to_crs("EPSG:3857")

    # ── Load candidates ───────────────────────────────────────────────────────
    slc = mio.read_sheet_safe(master, "Sign_Location_Candidates")
    if slc.empty:
        print("ERROR: Sign_Location_Candidates is empty.", file=sys.stderr)
        return 1
    print(f"\nLoaded {len(slc):,} candidates.")

    # Build a GeoDataFrame of candidate points in metric CRS
    pts = slc.dropna(subset=["Lat", "Lon"]).copy()
    pts["__pt__"] = pts.apply(lambda r: Point(float(r["Lon"]), float(r["Lat"])), axis=1)
    cand_gdf = gpd.GeoDataFrame(pts, geometry="__pt__", crs="EPSG:4326").to_crs("EPSG:3857")

    print(f"Spatial-joining {len(cand_gdf):,} points to nearest AADT segment "
          f"(max {args.max_distance_m}m) ...")
    t0 = time.time()
    joined = gpd.sjoin_nearest(
        cand_gdf, aadt_m, how="left", max_distance=args.max_distance_m, distance_col="__d__"
    )
    print(f"  {time.time()-t0:.1f}s")

    # Some points may have multiple matches (if equidistant); keep first
    joined = joined[~joined.index.duplicated(keep="first")]

    # Init columns on full SLC
    if "AADT" not in slc.columns:
        slc["AADT"] = 0
    if "AADT_Year" not in slc.columns:
        slc["AADT_Year"] = ""
    if "AADT_Road" not in slc.columns:
        slc["AADT_Road"] = ""
    if "AADT_Distance_M" not in slc.columns:
        slc["AADT_Distance_M"] = None

    # Write joined values back by index
    matched = 0
    for orig_idx, jrow in joined.iterrows():
        d = jrow.get("__d__")
        if d is None or (isinstance(d, float) and d != d):
            continue
        slc.at[orig_idx, "AADT_Distance_M"] = round(float(d), 1)
        if aadt_col and aadt_col in jrow.index:
            v = jrow.get(aadt_col)
            try:
                slc.at[orig_idx, "AADT"] = int(float(v)) if v is not None and v == v else 0
            except (TypeError, ValueError):
                slc.at[orig_idx, "AADT"] = 0
        if year_col and year_col in jrow.index:
            v = jrow.get(year_col)
            slc.at[orig_idx, "AADT_Year"] = "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()
        if road_col and road_col in jrow.index:
            v = jrow.get(road_col)
            slc.at[orig_idx, "AADT_Road"] = "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()
        matched += 1

    aadt_vals = slc["AADT"].fillna(0).astype(int)
    n_with_aadt = int((aadt_vals > 0).sum())
    print(f"\nMatched {matched:,} / {len(slc):,} candidates to a road segment.")
    print(f"Candidates with AADT > 0: {n_with_aadt:,} ({n_with_aadt/len(slc):.0%})")
    if n_with_aadt:
        print(f"AADT stats (matched only):")
        nz = aadt_vals[aadt_vals > 0]
        print(f"  median: {int(nz.median()):,}")
        print(f"  mean:   {int(nz.mean()):,}")
        print(f"  p90:    {int(nz.quantile(0.90)):,}")
        print(f"  max:    {int(nz.max()):,}")

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
# AADT download via ArcGIS REST API (paginated)
# ──────────────────────────────────────────────────────────────────────────────

def _download_aadt_paged(httpx, gpd, endpoints, cache_path):
    """Try each FDOT endpoint until one returns features. Saves combined GeoJSON."""
    for base in endpoints:
        print(f"  trying: {base}")
        try:
            # Probe metadata
            meta_url = f"{base}?f=json"
            meta = httpx.get(meta_url, timeout=15.0).json()
            max_count = meta.get("maxRecordCount", PAGE_SIZE)
            page = min(PAGE_SIZE, max_count)
            print(f"    metadata OK, page size: {page}")

            # Count
            count_url = f"{base}/query?where=1%3D1&returnCountOnly=true&f=json"
            cnt = httpx.get(count_url, timeout=15.0).json().get("count", 0)
            print(f"    {cnt:,} segments to download")
            if cnt == 0:
                continue

            # Page through
            features = []
            offset = 0
            t0 = time.time()
            while offset < cnt:
                qurl = (f"{base}/query?where=1%3D1&outFields=*&returnGeometry=true"
                        f"&outSR=4326&f=geojson&resultOffset={offset}&resultRecordCount={page}")
                r = httpx.get(qurl, timeout=60.0)
                if r.status_code != 200:
                    print(f"    HTTP {r.status_code} at offset {offset}; aborting endpoint")
                    features = None
                    break
                try:
                    d = r.json()
                except Exception:
                    print(f"    non-JSON response; aborting endpoint")
                    features = None
                    break
                got = d.get("features", []) or []
                if not got:
                    break
                features.extend(got)
                offset += len(got)
                if offset % (page * 10) == 0:
                    print(f"    {offset:,}/{cnt:,} ({time.time()-t0:.0f}s)")
            if not features:
                continue

            # Save and load
            import json as _json
            geojson = {"type": "FeatureCollection", "features": features}
            cache_path.write_text(_json.dumps(geojson))
            print(f"  cached {len(features):,} features -> {cache_path}")
            return gpd.read_file(cache_path)
        except Exception as e:
            print(f"    endpoint failed: {type(e).__name__}: {e}")
            continue
    return None


def _detect_column(df, candidates):
    cols_upper = {c.upper(): c for c in df.columns}
    for c in candidates:
        if c.upper() in cols_upper:
            return cols_upper[c.upper()]
    # Fuzzy: any column starting with the candidate
    for c in candidates:
        for col in df.columns:
            if str(col).upper().startswith(c.upper()):
                return col
    return None


if __name__ == "__main__":
    sys.exit(main())
