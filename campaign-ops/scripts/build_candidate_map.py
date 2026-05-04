#!/usr/bin/env python3
"""
Build an interactive HTML map of all 4x8 sign location candidates.

Reads `Sign_Location_Candidates` and `County_Master` from the master workbook
and produces a self-contained `outputs/sign_candidates_map.html`. Pins are
clustered, color-coded by Tier, and toggleable per Type.

Usage:
    python scripts/build_candidate_map.py
    python scripts/build_candidate_map.py --output <path>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
DEFAULT_OUT = "outputs/sign_candidates_map.html"

# Pin color per Strategic Tier.
TIER_COLOR = {
    "A": "red",
    "B": "orange",
    "C": "blue",
    "D": "gray",
}

# Icon per Type (from Font Awesome via Folium).
TYPE_ICON = {
    "intersection": "road",
    "commercial":   "shop",
    "agri_civic":   "tractor",
}

TYPE_LABEL = {
    "intersection": "Intersection",
    "commercial":   "Commercial",
    "agri_civic":   "Agricultural / Civic",
}

# Human-readable status mapping for popups
STATUS_HUMAN = {
    "verified_full":   "Fully verified (phone + email)",
    "verified_phone":  "Phone verified",
    "verified_email":  "Email verified",
    "needs_lookup":    "Needs lookup",
    "chair_complete":  "Chair contact complete",
    "partial_with_delivery": "Partial — delivery contact OK",
    "partial":         "Partial",
    "delivery_only":   "Delivery contact only",
    "MISSING":         "MISSING",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build interactive HTML map of sign deployment plan + candidates.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--output", default=DEFAULT_OUT)
    p.add_argument("--no-cluster", action="store_true",
                   help="Disable marker clustering (every pin shown individually).")
    p.add_argument("--with-heatmap", action="store_true",
                   help="Add a heatmap layer showing candidate density.")
    p.add_argument("--source", default="auto", choices=["auto", "deployment", "candidates"],
                   help="auto: prefer Sign_Deployment_Plan if present, else Sign_Location_Candidates. "
                        "deployment: only the deployment plan. candidates: full pool.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import pandas as pd
        import folium
        from folium.plugins import MarkerCluster, HeatMap, Search
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Source selection: prefer Sign_Deployment_Plan when available.
    slc = pd.DataFrame()
    source_used = ""
    # Optional overlay from action workbook (field-staff edits)
    action_overlay: dict = {}
    action_path = master.parent / "campaign_ops_action.xlsx"
    if action_path.exists():
        try:
            ax = pd.read_excel(action_path, sheet_name="4x8_Sites")
            for _, ar in ax.iterrows():
                cid = str(ar.get("Candidate_ID") or "").strip()
                if not cid:
                    continue
                action_overlay[cid] = {
                    "Phone": ar.get("Phone"),
                    "Email": ar.get("Email"),
                    "Owner_Contact": ar.get("Owner_Contact"),
                    "Notes": ar.get("Notes"),
                    "Approval_Status": ar.get("Approval_Status"),
                    "Install_Status": ar.get("Install_Status"),
                    "Suggested_Storefronts": ar.get("Suggested_Storefronts"),
                }
            print(f"Action workbook overlay: {len(action_overlay)} sites")
        except Exception as e:
            print(f"WARN: could not read action overlay: {e}")
    if args.source in ("auto", "deployment"):
        sdp = mio.read_sheet_safe(master, "Sign_Deployment_Plan")
        if not sdp.empty:
            slc = sdp.copy()
            source_used = "Sign_Deployment_Plan"
    if slc.empty and args.source != "deployment":
        slc = mio.read_sheet_safe(master, "Sign_Location_Candidates")
        if not slc.empty:
            slc["Plan"] = "primary"  # treat full pool as primary for filtering
            source_used = "Sign_Location_Candidates"
    if slc.empty:
        print("ERROR: no source sheet has rows. run find_sign_locations.py first.", file=sys.stderr)
        return 1
    print(f"Source: {source_used}")

    # Filter rows with valid coordinates.
    slc = slc.dropna(subset=["Lat", "Lon"]).copy()
    slc = slc[(slc["Lat"].between(24.0, 31.5)) & (slc["Lon"].between(-88.0, -79.5))]
    if "Plan" not in slc.columns:
        slc["Plan"] = "primary"
    print(f"Plotting {len(slc)} rows with valid Florida coordinates "
          f"(primary={int((slc['Plan']=='primary').sum())}, "
          f"replacement={int((slc['Plan']=='replacement').sum())})")

    # Center on Florida.
    fmap = folium.Map(location=[28.0, -82.5], zoom_start=7, tiles="cartodbpositron",
                      world_copy_jump=True)

    # Determine which (Plan, Type, Tier) combos actually have data — drop empty
    # layers so the layer toggle isn't cluttered with dead options.
    actual_combos = set()
    for _, r in slc.iterrows():
        plan = str(r.get("Plan") or "primary").strip() or "primary"
        type_ = str(r.get("Type") or "").strip()
        tier = str(r.get("Tier") or "").strip().upper()
        try:
            lat = float(r.get("Lat"))
            lon = float(r.get("Lon"))
        except (TypeError, ValueError):
            continue
        if type_ in TYPE_LABEL and tier in TIER_COLOR:
            actual_combos.add((plan, type_, tier))

    # Build one feature group per ACTUAL combo. Replacement layers off by default.
    groups: dict[tuple, MarkerCluster] = {}
    plan_label = {"primary": "Primary", "replacement": "Replacement"}
    for plan in ("primary", "replacement"):
        for type_ in TYPE_LABEL:
            for tier in ["A", "B", "C", "D"]:
                if (plan, type_, tier) not in actual_combos:
                    continue
                label = f"{plan_label[plan]} · {TYPE_LABEL[type_]} · Tier {tier}"
                show_default = (plan == "primary") and (tier in ("A", "B"))
                if args.no_cluster:
                    fg = folium.FeatureGroup(name=label, show=show_default)
                else:
                    fg = MarkerCluster(name=label, show=show_default)
                fg.add_to(fmap)
                groups[(plan, type_, tier)] = fg

    # Add markers.
    plotted = 0
    for _, r in slc.iterrows():
        plan = str(r.get("Plan", "primary")).strip() or "primary"
        if plan not in ("primary", "replacement"):
            plan = "primary"
        type_ = str(r.get("Type", "")).strip()
        tier = str(r.get("Tier", "")).strip().upper()
        if type_ not in TYPE_LABEL or tier not in TIER_COLOR:
            continue
        lat, lon = float(r["Lat"]), float(r["Lon"])
        name = _clean(r.get("Name")) or "(no name)"
        addr = _clean(r.get("Address"))
        category = _clean(r.get("Category"))
        county = _clean(r.get("County"))
        cid = _clean(r.get("Candidate_ID"))
        maps_link = _clean(r.get("Maps_Link"))
        # Action workbook overrides take precedence for field-edit fields
        ov = action_overlay.get(cid, {}) if cid else {}
        phone = _clean(ov.get("Phone")) or _clean(r.get("Phone"))
        email = _clean(ov.get("Email")) or _clean(r.get("Email"))
        website = _clean(r.get("Website"))
        owner = _clean(ov.get("Owner_Contact"))
        field_notes = _clean(ov.get("Notes"))
        install_status = _clean(ov.get("Install_Status"))
        # Storefronts from row first; fall back to action workbook
        sf_text = ""
        sf_parts = []
        for i in (1, 2, 3):
            sf = _clean(r.get(f"Nearest_Storefront_{i}"))
            d = r.get(f"Storefront_{i}_Distance_M")
            if not sf:
                continue
            try:
                if d is not None and not (isinstance(d, float) and d != d):
                    sf_parts.append(f"{sf} ({int(d)}m)")
                else:
                    sf_parts.append(sf)
            except (TypeError, ValueError):
                sf_parts.append(sf)
        if sf_parts:
            sf_text = "<br>".join(f"&nbsp;&nbsp;• {s}" for s in sf_parts)
        poc_status = str(r.get("POC_Status") or "").strip()
        google_url = str(r.get("Google_Search_URL") or "").strip()

        poc_block = ""
        if phone:
            poc_block += f"📞 <b>{phone}</b><br>"
        if email:
            poc_block += f"✉ {email}<br>"
        if website:
            display = website if len(website) <= 60 else website[:57] + "…"
            poc_block += f"🌐 <a href='{website}' target='_blank'>{display}</a><br>"
        if poc_status:
            poc_human = STATUS_HUMAN.get(poc_status, poc_status)
            poc_block += f"<small>POC: {poc_human}</small><br>"
        if google_url and not (phone and email):
            poc_block += f"<small><a href='{google_url}' target='_blank'>🔍 Search for contact info</a></small><br>"

        plan_disp = "Primary" if plan == "primary" else "Replacement"
        # Field-staff overlay block (status / owner / notes)
        overlay_block = ""
        if install_status and install_status.lower() != "pending":
            overlay_block += f"<b>Status: {install_status}</b><br>"
        if owner:
            overlay_block += f"<b>Owner:</b> {owner}<br>"
        if field_notes:
            overlay_block += f"<small><b>Field notes:</b> {field_notes}</small><br>"
        # Suggested storefronts block
        storefront_block = ""
        if sf_text:
            storefront_block = (
                f"<small><b>🏪 Suggested storefronts nearby:</b></small><br>"
                f"<small>{sf_text}</small><br>"
            )
        popup_html = (
            f"<b>{name}</b><br>"
            f"<i>{cid}</i> &nbsp; {county} &nbsp; Tier {tier} &nbsp; <b>{plan_disp}</b><br>"
            f"<small>{TYPE_LABEL[type_]} &mdash; {category}</small><br>"
            + (f"{addr}<br>" if addr else "")
            + poc_block
            + overlay_block
            + storefront_block
            + (f"<a href='{maps_link}' target='_blank'>Open in Google Maps</a><br>" if maps_link else "")
        )
        tooltip = f"{plan_disp}: {name} · {county} · Tier {tier}"

        # Replacement pins use a faded version of the tier color.
        if plan == "replacement":
            icon = folium.Icon(color="lightgray", icon=TYPE_ICON[type_], prefix="fa")
        else:
            icon = folium.Icon(color=TIER_COLOR[tier], icon=TYPE_ICON[type_], prefix="fa")
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=360),
            tooltip=tooltip,
            icon=icon,
        ).add_to(groups[(plan, type_, tier)])
        plotted += 1

    # Optional heatmap.
    if args.with_heatmap:
        heat_layer = folium.FeatureGroup(name="Candidate density (heatmap)", show=False)
        HeatMap([[r["Lat"], r["Lon"], 1] for _, r in slc.iterrows()],
                radius=12, blur=18, min_opacity=0.3).add_to(heat_layer)
        heat_layer.add_to(fmap)

    # ── Yard sign drop-off layer (REC delivery locations) ──
    ysa = mio.read_sheet_safe(master, "Yard_Sign_Allocation")
    if not ysa.empty and "Drop_Lat" in ysa.columns:
        yard_layer = folium.FeatureGroup(name="🌟 Yard Sign Drops (67 RECs)", show=True)
        n_drops = 0
        for _, r in ysa.iterrows():
            try:
                lat = float(r["Drop_Lat"])
                lon = float(r["Drop_Lon"])
            except (TypeError, ValueError, KeyError):
                continue
            # Skip NaN / out-of-bounds
            if lat != lat or lon != lon:
                continue
            if not (24.0 <= lat <= 31.5 and -88.0 <= lon <= -79.5):
                continue
            county = _clean(r.get("County"))
            chair = _clean(r.get("Chair"))
            chair_phone = _clean(r.get("Chair_Phone"))
            chair_email = _clean(r.get("Chair_Email"))
            del_phone = _clean(r.get("Primary_Delivery_Phone"))
            del_email = _clean(r.get("Primary_Delivery_Email"))
            del_loc = _clean(r.get("Meeting_Delivery_Location"))
            tier = _clean(r.get("Strategic_Tier"))
            wave = _clean(r.get("Wave"))
            plan_4000 = r.get("Plan_4000", 0) or 0
            try:
                if isinstance(plan_4000, float) and plan_4000 != plan_4000:
                    plan_4000 = 0
            except Exception:
                plan_4000 = 0
            boss_total = r.get("Suggested_Yard_Signs_Boss", 0) or 0
            try:
                if isinstance(boss_total, float) and boss_total != boss_total:
                    boss_total = 0
            except Exception:
                boss_total = 0
            poc_status = _clean(r.get("POC_Status_Yard"))

            popup_html = (
                f"<b>{county} REC</b> &nbsp; <span style='color:#888'>Tier {tier}</span><br>"
                f"<b>📦 Plan_4000:</b> {int(plan_4000)} signs &nbsp; "
                f"<b>(boss: {int(boss_total)})</b><br>"
                f"<b>Wave:</b> {wave or '(unspecified)'}<br>"
                f"<hr style='margin:4px 0'>"
                f"<b>Chair:</b> {chair or '(none)'}<br>"
                + (f"📞 {chair_phone}<br>" if chair_phone else "")
                + (f"✉ {chair_email}<br>" if chair_email else "")
                + (f"<b>Delivery:</b> 📞 {del_phone} ✉ {del_email}<br>"
                   if (del_phone or del_email) else "")
                + (f"<b>Drop site:</b> {del_loc}<br>" if del_loc else "")
                + f"<small>POC status: {STATUS_HUMAN.get(poc_status, poc_status)}</small>"
            )
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup_html, max_width=380),
                tooltip=f"🌟 {county} REC — {int(plan_4000)} yard signs",
                icon=folium.Icon(color="orange", icon="star", prefix="fa"),
            ).add_to(yard_layer)
            n_drops += 1
        yard_layer.add_to(fmap)
        print(f"Plotted {n_drops} REC yard sign drop locations.")
    else:
        print("WARN: Yard_Sign_Allocation has no Drop_Lat column. "
              "Run scripts/geocode_yard_drops.py to plot yard drops on the map.")

    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)

    # Legend.
    legend = """
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 12px 14px; border: 1px solid #999;
                font: 12px sans-serif; line-height: 1.6;">
      <b>4×8 Sign Plan</b> &nbsp; <small>Pin color = Tier</small><br>
      <span style="display:inline-block;width:12px;height:12px;background:#d63e2a;"></span> Tier A &nbsp;
      <span style="display:inline-block;width:12px;height:12px;background:#f69730;"></span> Tier B &nbsp;
      <span style="display:inline-block;width:12px;height:12px;background:#38aadd;"></span> Tier C &nbsp;
      <span style="display:inline-block;width:12px;height:12px;background:#9e9e9e;"></span> Tier D<br>
      <span style="display:inline-block;width:12px;height:12px;background:#cccccc;"></span> Replacement (light gray)<br>
      <small>Icons: 🛣 intersection &nbsp; 🏪 commercial &nbsp; 🚜 agri/civic</small><br>
      <hr style="margin:6px 0">
      <b>🌟 Yard Sign Drops</b> — gold star = REC delivery location<br>
      <small>Toggle layers top-right. Click pins for POC + plan details.</small>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend))

    # Title bar.
    n_primary = int((slc["Plan"] == "primary").sum())
    n_replace = int((slc["Plan"] == "replacement").sum())
    n_yard = 0
    try:
        ysa_chk = mio.read_sheet_safe(master, "Yard_Sign_Allocation")
        if not ysa_chk.empty and "Drop_Lat" in ysa_chk.columns:
            n_yard = int(ysa_chk["Drop_Lat"].notna().sum())
    except Exception:
        pass
    title = f"""
    <div style="position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
                z-index: 9999; background: white; padding: 10px 18px;
                border: 1px solid #999; border-radius: 4px;
                font: 14px sans-serif; font-weight: bold;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
      Florida Sign Operations — {n_primary:,} 4×8 Primary Sites + {n_replace:,} Replacement Bench + {n_yard} REC Yard-Sign Drops
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(title))

    print(f"Writing {out} ...")
    fmap.save(str(out))

    file_size = out.stat().st_size / 1024
    print(f"Done. {plotted} pins, {file_size:.0f} KB. Open in any browser.")
    return 0


def _clean(v) -> str:
    """Convert NaN/None/'nan'/'None' to empty string for popup display."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and v != v:  # NaN
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if s.lower() in ("nan", "none", "null"):
        return ""
    return s


if __name__ == "__main__":
    sys.exit(main())
