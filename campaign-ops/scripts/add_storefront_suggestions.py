#!/usr/bin/env python3
"""
Add storefront suggestions to the Sign_Deployment_Plan.

For every primary 4×8 site, find the 3 nearest *named* commercial POIs from
the broader Sign_Location_Candidates pool (within --max-distance-m, excluding
the site itself). Field staff use these as fallback options when the listed
business at a site is hard to find or has closed.

Adds 6 columns to Sign_Deployment_Plan:
  Nearest_Storefront_1, Storefront_1_Distance_M
  Nearest_Storefront_2, Storefront_2_Distance_M
  Nearest_Storefront_3, Storefront_3_Distance_M

Uses scipy.spatial.cKDTree for fast nearest-neighbor search (~5 sec for 2,000
sites against a 20K candidate pool).

Usage:
    python scripts/add_storefront_suggestions.py
    python scripts/add_storefront_suggestions.py --max-distance-m 800
"""
from __future__ import annotations

import argparse
import sys
import time
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Add nearest-storefront suggestions to Sign_Deployment_Plan.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--max-distance-m", type=int, default=500,
                   help="Max meters to search for storefronts (default: 500).")
    p.add_argument("--top-n", type=int, default=3,
                   help="Number of nearest storefronts per site (default: 3).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import warnings; warnings.filterwarnings("ignore")
        import pandas as pd
        import numpy as np
        from scipy.spatial import cKDTree
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}).", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    if not master.exists():
        print(f"ERROR: master not found: {master}", file=sys.stderr)
        return 1

    print(f"Reading sheets ...")
    sdp = mio.read_sheet_safe(master, "Sign_Deployment_Plan")
    slc = mio.read_sheet_safe(master, "Sign_Location_Candidates")
    if sdp.empty or slc.empty:
        print("ERROR: Sign_Deployment_Plan or Sign_Location_Candidates empty.", file=sys.stderr)
        return 1

    # Filter the pool: named commercial POIs only (real storefronts)
    pool = slc.copy()
    pool = pool[pool["Type"] == "commercial"]
    pool = pool.dropna(subset=["Lat", "Lon", "Name"])
    pool["Name"] = pool["Name"].astype(str).str.strip()
    # Drop placeholder names that may have leaked into the pool
    bad = pool["Name"].str.match(r"^[A-Z0-9]{1,2}$") | pool["Name"].str.lower().str.contains(
        r"\(no name\)|\(see maps_link\)|\(highway corridor\)", regex=True)
    pool = pool[~bad]
    pool = pool.reset_index(drop=True)
    print(f"  Storefront pool:   {len(pool):,} named commercial POIs")
    print(f"  Sites to enrich:   {len(sdp):,} (primary + replacement)")

    # Build KD-tree on lat/lon (in radians for haversine; use Equirectangular
    # approximation since search radius is small ~500m → fast and accurate enough).
    # Convert deg→approx meters: 1° lat ≈ 111,000m; 1° lon ≈ 111,000 * cos(lat) m.
    # For Florida ~28° N, lon factor ≈ cos(28°) ≈ 0.883.
    LAT_M = 111_000.0
    LON_M = 111_000.0 * cos(radians(28.0))

    pool_xy = np.column_stack([pool["Lat"].values * LAT_M, pool["Lon"].values * LON_M])
    tree = cKDTree(pool_xy)
    pool_ids = pool["Candidate_ID"].astype(str).values
    pool_names = pool["Name"].values
    pool_lats = pool["Lat"].values
    pool_lons = pool["Lon"].values

    # Initialize new columns
    new_cols = []
    for i in range(1, args.top_n + 1):
        new_cols += [f"Nearest_Storefront_{i}", f"Storefront_{i}_Distance_M"]
    for c in new_cols:
        if c not in sdp.columns:
            sdp[c] = None

    # Query nearest neighbors. Ask for top_n + 1 to drop the self-match.
    print(f"\nQuerying nearest {args.top_n} storefronts per site (max {args.max_distance_m}m) ...")
    t0 = time.time()
    has_coords = sdp.dropna(subset=["Lat", "Lon"])
    sdp_xy = np.column_stack([has_coords["Lat"].values * LAT_M, has_coords["Lon"].values * LON_M])
    # Query top_n + 1 to allow self-removal
    distances, indices = tree.query(sdp_xy, k=min(args.top_n + 1, len(pool)),
                                    distance_upper_bound=args.max_distance_m)
    print(f"  KD-tree query: {time.time()-t0:.1f}s")

    # Apply
    sdp_idx = has_coords.index.tolist()
    n_with_at_least_one = 0
    for row_offset, idx in enumerate(sdp_idx):
        own_id = str(sdp.at[idx, "Candidate_ID"])
        ds = distances[row_offset]
        ix = indices[row_offset]
        # Pair, filter self-match, drop infinity, take top_n
        picks = []
        # numpy returns scalars for k=1; normalize to list
        if np.isscalar(ds):
            ds = [ds]; ix = [ix]
        for d, i in zip(ds, ix):
            if i >= len(pool_ids):
                continue  # no neighbor within radius
            if d == float("inf"):
                continue
            pid = pool_ids[i]
            if pid == own_id:
                continue
            picks.append((d, pool_names[i]))
            if len(picks) >= args.top_n:
                break
        if picks:
            n_with_at_least_one += 1
        for slot in range(args.top_n):
            if slot < len(picks):
                d, name = picks[slot]
                sdp.at[idx, f"Nearest_Storefront_{slot+1}"] = name
                sdp.at[idx, f"Storefront_{slot+1}_Distance_M"] = int(round(d))
            else:
                sdp.at[idx, f"Nearest_Storefront_{slot+1}"] = None
                sdp.at[idx, f"Storefront_{slot+1}_Distance_M"] = None

    pct = n_with_at_least_one / len(sdp) if len(sdp) else 0
    print(f"\nResults:")
    print(f"  Sites with ≥1 storefront within {args.max_distance_m}m: {n_with_at_least_one}/{len(sdp)} ({pct:.0%})")

    # Sample
    primary = sdp[sdp["Plan"] == "primary"].head(5)
    print(f"\nSample (first 5 primary sites):")
    for _, r in primary.iterrows():
        s1 = r.get("Nearest_Storefront_1") or "—"
        d1 = r.get("Storefront_1_Distance_M") or 0
        s2 = r.get("Nearest_Storefront_2") or "—"
        s3 = r.get("Nearest_Storefront_3") or "—"
        print(f"  {str(r.get('County')):14s} {str(r.get('Name'))[:30]:30s}  → {s1[:25]} ({d1}m), {s2[:20]}, {s3[:20]}")

    print(f"\nWriting Sign_Deployment_Plan to {master} ...")
    mio.replace_sheet(master, "Sign_Deployment_Plan", sdp,
                      color_col="Plan",
                      color_map={"primary": "D4EDDA", "replacement": "FFF3CD"})
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
