#!/usr/bin/env python3
"""
Phase 3 — GIS Sign Location Map

Builds a self-contained Folium HTML map showing precinct priorities,
REC locations, and (optionally) candidate intersections from osmnx.

Usage:
    python scripts/03_gis_map.py --shapefile data/raw/precincts/your_county.shp
    python scripts/03_gis_map.py --shapefile <path> --no-roads
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
DEFAULT_BILLBOARD = "data/raw/billboard_limits.csv"
DEFAULT_OUT = "outputs/sign_map.html"
DEFAULT_CACHE = "data/clean/_osmnx_cache"

TIER_COLORS = {
    1: "#1a7f1a",  # dark green
    2: "#7ac57a",  # mid green
    3: "#f4d35e",  # amber
    4: "#cccccc",  # gray
}

ROAD_CLASS_WEIGHT = {
    "motorway": 5,
    "trunk": 4,
    "primary": 3,
    "secondary": 2,
    "tertiary": 1,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 3 — GIS sign-location map.")
    p.add_argument("--shapefile", required=False, help="Path to precinct .shp file.")
    p.add_argument("--master", default=DEFAULT_MASTER,
                   help="Master workbook to read Contacts + Precincts from.")
    p.add_argument("--billboard-limits", default=DEFAULT_BILLBOARD)
    p.add_argument("--output", default=DEFAULT_OUT)
    p.add_argument(
        "--precinct-id-col",
        default=None,
        help="Shapefile column name that matches the precinct_id column. "
        "If omitted, the script will prompt or guess.",
    )
    p.add_argument("--no-roads", action="store_true", help="Skip the osmnx road-network layer.")
    p.add_argument("--top-intersections", type=int, default=3,
                   help="Top-N candidate intersections per Tier 1/2 precinct (default: 3).")
    p.add_argument("--cache-dir", default=DEFAULT_CACHE)
    return p.parse_args()


def guess_precinct_col(gdf_columns) -> str | None:
    candidates = ["precinct_id", "precinct", "pct", "pctnum", "id", "PRECINCT"]
    lower_to_actual = {str(c).strip().lower(): c for c in gdf_columns}
    for cand in candidates:
        if cand.lower() in lower_to_actual:
            return lower_to_actual[cand.lower()]
    return None


def main() -> int:
    args = parse_args()
    if not args.shapefile:
        print("ERROR: --shapefile is required.", file=sys.stderr)
        return 1

    try:
        import pandas as pd
        import geopandas as gpd
        import folium
        from folium import plugins as folium_plugins  # noqa: F401  (LayerControl is folium core)
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    shp_path = Path(args.shapefile)
    if not shp_path.exists():
        print(f"ERROR: shapefile not found: {shp_path}", file=sys.stderr)
        return 1
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading shapefile {shp_path} ...")
    gdf = gpd.read_file(shp_path)
    if gdf.crs is None:
        print("WARN: shapefile has no CRS — assuming EPSG:4326.")
    else:
        gdf = gdf.to_crs(epsg=4326)

    pid_col = args.precinct_id_col or guess_precinct_col(gdf.columns)
    if not pid_col:
        print(f"ERROR: could not guess precinct id column. shapefile columns: {list(gdf.columns)}",
              file=sys.stderr)
        return 1
    print(f"Using shapefile precinct id column: {pid_col!r}")
    gdf["__pid__"] = gdf[pid_col].astype(str).str.strip()

    # Join priorities from master workbook (Precincts sheet).
    master_path = Path(args.master)
    pri = mio.read_sheet_safe(master_path, "Precincts")
    if not pri.empty:
        pri["precinct_id"] = pri["precinct_id"].astype(str).str.strip()
        gdf = gdf.merge(pri, left_on="__pid__", right_on="precinct_id", how="left")
        print(f"Joined Precincts from master: {gdf['tier'].notna().sum()}/{len(gdf)} precincts matched.")
    else:
        print(f"WARN: Precincts sheet empty in {master_path} — map will show shapes only, no tiers.")
        gdf["tier"] = 4
        gdf["tier_label"] = "(no priorities)"

    gdf["tier"] = gdf["tier"].fillna(4).astype(int)

    # Center map on the precinct centroid.
    minx, miny, maxx, maxy = gdf.total_bounds
    center = [(miny + maxy) / 2, (minx + maxx) / 2]

    fmap = folium.Map(location=center, zoom_start=10, tiles="cartodbpositron")

    # Precinct layer (choropleth-like).
    precinct_layer = folium.FeatureGroup(name="Precincts (by tier)").add_to(fmap)
    for _, row in gdf.iterrows():
        tier = int(row["tier"]) if row["tier"] in TIER_COLORS else 4
        color = TIER_COLORS.get(tier, "#cccccc")
        popup_html = (
            f"<b>Precinct:</b> {row['__pid__']}<br>"
            f"<b>Tier:</b> {row.get('tier_label', tier)}<br>"
            f"<b>Turnout 2024:</b> {row.get('turnout_24', 'n/a')}<br>"
            f"<b>Swing:</b> {row.get('swing', 'n/a')}<br>"
        )
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda feat, c=color: {
                "fillColor": c,
                "color": "#333",
                "weight": 0.5,
                "fillOpacity": 0.55,
            },
            tooltip=f"Precinct {row['__pid__']} — Tier {tier}",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(precinct_layer)

    # REC contacts layer (read from master Contacts sheet).
    contacts = mio.read_sheet_safe(master_path, "Contacts")
    if not contacts.empty:
        rec_layer = folium.FeatureGroup(name="REC Contacts").add_to(fmap)
        # Derive county centroids as fallback location since we don't have addresses guaranteed.
        county_centroids: dict[str, tuple[float, float]] = {}
        if "County" in gdf.columns:
            for county, sub in gdf.groupby("County"):
                centroid = sub.geometry.union_all().centroid
                county_centroids[str(county)] = (centroid.y, centroid.x)
        placed = 0
        for _, c in contacts.iterrows():
            county = str(c.get("County") or "")
            loc = county_centroids.get(county)
            if not loc:
                # Fallback: map center.
                loc = tuple(center)
            popup = (
                f"<b>REC:</b> {c.get('REC', '')}<br>"
                f"<b>Contact:</b> {c.get('Name', '')}<br>"
                f"<b>County:</b> {county}<br>"
                f"<b>Phone:</b> {c.get('Phone', '')}<br>"
                f"<b>Email:</b> {c.get('Email', '')}<br>"
                f"<b>Quality:</b> {c.get('Quality', '')}<br>"
            )
            quality = c.get("Quality")
            color = {"Complete": "green", "Partial": "orange", "Broken": "red"}.get(quality, "gray")
            folium.CircleMarker(
                location=loc,
                radius=6,
                color=color,
                fill=True,
                fill_opacity=0.9,
                popup=folium.Popup(popup, max_width=300),
                tooltip=f"REC: {c.get('REC', '')} ({county}) — low precision",
            ).add_to(rec_layer)
            placed += 1
        print(f"Placed {placed} REC markers (county centroid; address-level geocoding skipped).")
    else:
        print(f"WARN: Contacts sheet empty in {master_path} — REC layer omitted.")

    # Optional billboard zoning overlay.
    bb_path = Path(args.billboard_limits)
    if bb_path.exists():
        bb_layer = folium.FeatureGroup(name="Billboard Zoning").add_to(fmap)
        bb = pd.read_csv(bb_path)
        # Add municipality info as a popup on the centroid; full zoning shapes require a separate shapefile.
        for _, b in bb.iterrows():
            tip = (
                f"<b>{b.get('municipality', '')}</b><br>"
                f"max sqft: {b.get('max_sign_sqft', '')}<br>"
                f"max height: {b.get('max_height_ft', '')} ft<br>"
                f"setback: {b.get('setback_ft', '')} ft<br>"
                f"permit: {b.get('permit_required', '')}<br>"
            )
            # Without geometry, we can only attach this as a legend marker at map center.
            folium.Marker(
                location=center,
                icon=folium.Icon(color="blue", icon="info-sign"),
                popup=folium.Popup(tip, max_width=250),
                tooltip=f"Zoning: {b.get('municipality', '')}",
            ).add_to(bb_layer)

    # Optional road / intersection layer.
    if not args.no_roads:
        try:
            import osmnx as ox
            from shapely.geometry import Point
            cache_dir = Path(args.cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            ox.settings.use_cache = True
            ox.settings.cache_folder = str(cache_dir)
            int_layer = folium.FeatureGroup(name="Candidate Intersections").add_to(fmap)
            high_priority = gdf[gdf["tier"].isin([1, 2])]
            print(f"Pulling road networks for {len(high_priority)} Tier 1/2 precincts ...")
            for _, row in high_priority.iterrows():
                poly = row.geometry
                try:
                    G = ox.graph_from_polygon(poly, network_type="drive",
                                              custom_filter='["highway"~"primary|secondary|tertiary|trunk|motorway"]')
                except Exception as e:
                    print(f"  precinct {row['__pid__']}: skipped ({e})")
                    continue
                # Score nodes by degree × max-class incident edge.
                scored: list[tuple[float, float, float, str]] = []
                for node, data in G.nodes(data=True):
                    deg = G.degree[node]
                    if deg < 3:
                        continue
                    max_w = 0
                    for _, _, edata in G.edges(node, data=True):
                        hw = edata.get("highway", "")
                        if isinstance(hw, list):
                            hw = hw[0] if hw else ""
                        max_w = max(max_w, ROAD_CLASS_WEIGHT.get(hw, 0))
                    if max_w == 0:
                        continue
                    score = max_w * (5 - int(row["tier"]))
                    scored.append((score, data["y"], data["x"], f"deg={deg} class_w={max_w}"))
                scored.sort(reverse=True)
                for score, y, x, label in scored[: args.top_intersections]:
                    folium.CircleMarker(
                        location=(y, x),
                        radius=4,
                        color="#cc0000",
                        fill=True,
                        fill_opacity=0.9,
                        tooltip=f"Candidate 4x8 site (score {score}; {label})",
                    ).add_to(int_layer)
        except ImportError:
            print("WARN: osmnx not installed; skipping road layer.")
        except Exception as e:
            print(f"WARN: road layer failed ({e}); skipping.")

    folium.LayerControl(collapsed=False).add_to(fmap)

    # Legend.
    legend_html = """
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 10px; border: 1px solid #999;
                font: 12px sans-serif;">
      <b>Precinct Tiers</b><br>
      <span style="display:inline-block;width:12px;height:12px;background:#1a7f1a;"></span> Tier 1 — Protect<br>
      <span style="display:inline-block;width:12px;height:12px;background:#7ac57a;"></span> Tier 2 — Mobilize<br>
      <span style="display:inline-block;width:12px;height:12px;background:#f4d35e;"></span> Tier 3 — Persuade<br>
      <span style="display:inline-block;width:12px;height:12px;background:#cccccc;"></span> Tier 4 — Deprioritize<br>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend_html))

    print(f"Writing {out_path} ...")
    fmap.save(str(out_path))
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
