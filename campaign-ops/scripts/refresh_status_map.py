#!/usr/bin/env python3
"""
Refresh the operational status map.

Reads Install_Status from outputs/campaign_ops_action.xlsx (the action workbook
that field staff update) and produces outputs/sign_status_map.html with pins
color-coded by deployment status:

  ✅ Installed       → solid green
  📅 Approved        → blue
  ⏳ Pending         → tier color (default)
  ⚠ Site Issue      → orange
  ❌ Declined        → light gray
  🚧 Removed/Damaged → red

Each status gets its own toggleable layer so you can see "show only what's
installed", "show only what's left to call", etc.

Also adds:
  - 67 REC yard-sign drop pins (gold stars) — Status from Yard_Sign_RECs sheet
  - Per-county progress badge layer (X / Y installed)
  - Title bar with overall progress (X / 2000 installed)

Usage:
    python scripts/refresh_status_map.py
    python scripts/refresh_status_map.py --action <path> --output <path>
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_ACTION = "outputs/campaign_ops_action.xlsx"
DEFAULT_OUTPUT = "outputs/sign_status_map.html"

# Status → (color, icon, human label, default visibility on layer)
STATUS_STYLE = {
    "Installed":   ("green",      "check",       "Installed (live)",   True),
    "Approved":    ("blue",       "calendar",    "Approved (scheduled)", True),
    "Pending":     ("orange",     "phone",       "Pending (to call)",  True),
    "Site Issue":  ("orange",     "exclamation", "Site Issue",         True),
    "Declined":    ("lightgray",  "times",       "Declined",           False),
    "Removed":     ("red",        "minus",       "Removed",            False),
    "Damaged":     ("red",        "wrench",      "Damaged",            False),
}

# Yard delivery status colors
YARD_STATUS_STYLE = {
    "Delivered":  ("green",      "truck"),
    "In Transit": ("orange",     "truck"),
    "Confirmed":  ("blue",       "calendar-check-o"),
    "Scheduled":  ("orange",     "calendar"),
    "Issue":      ("red",        "exclamation"),
    "Cancelled":  ("lightgray",  "ban"),
}

TIER_COLOR_FALLBACK = {"A": "red", "B": "orange", "C": "blue", "D": "gray"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Status map — reflects field-updated Install_Status.")
    p.add_argument("--action", default=DEFAULT_ACTION,
                   help=f"Action workbook (default: {DEFAULT_ACTION})")
    p.add_argument("--output", default=DEFAULT_OUTPUT,
                   help=f"Output HTML (default: {DEFAULT_OUTPUT})")
    p.add_argument("--no-cluster", action="store_true",
                   help="Don't cluster markers (slower at full state zoom).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import warnings; warnings.filterwarnings("ignore")
        import pandas as pd
        import folium
        from folium.plugins import MarkerCluster
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    action = Path(args.action)
    if not action.exists():
        print(f"ERROR: action workbook not found at {action}", file=sys.stderr)
        print(f"       run: python scripts/build_action_workbook.py", file=sys.stderr)
        return 1
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Reading {action} ...")
    sites = pd.read_excel(action, sheet_name="4x8_Sites")
    recs = pd.read_excel(action, sheet_name="Yard_Sign_RECs")

    # We need Lat/Lon and storefront columns — pull them from the master.
    print(f"Joining coordinates + storefronts from master workbook ...")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore
    master_path = Path("outputs/campaign_ops_master.xlsx")
    if not master_path.exists():
        print(f"ERROR: master workbook missing at {master_path}", file=sys.stderr)
        return 1
    sdp = mio.read_sheet_safe(master_path, "Sign_Deployment_Plan")
    join_cols = ["Lat", "Lon"]
    for sf_col in ("Nearest_Storefront_1", "Storefront_1_Distance_M",
                   "Nearest_Storefront_2", "Storefront_2_Distance_M",
                   "Nearest_Storefront_3", "Storefront_3_Distance_M"):
        if sf_col in sdp.columns:
            join_cols.append(sf_col)
    coords = sdp.set_index("Candidate_ID")[join_cols]
    sites = sites.merge(coords, left_on="Candidate_ID", right_index=True, how="left")

    ysa = mio.read_sheet_safe(master_path, "Yard_Sign_Allocation")
    yard_coords = ysa.set_index("County")[["Drop_Lat", "Drop_Lon"]]
    recs = recs.merge(yard_coords, left_on="County", right_index=True, how="left")

    # Stats
    status_counts = sites["Install_Status"].fillna("Pending").value_counts().to_dict()
    n_total = len(sites)
    n_installed = status_counts.get("Installed", 0)
    n_approved = status_counts.get("Approved", 0)
    n_pending = status_counts.get("Pending", 0)
    n_declined = status_counts.get("Declined", 0)
    n_yard_delivered = int((recs["Status"] == "Delivered").sum())

    print(f"\nCurrent status:")
    print(f"  Installed:    {n_installed:5d} / {n_total} ({n_installed/n_total:.0%})")
    print(f"  Approved:     {n_approved:5d}")
    print(f"  Pending:      {n_pending:5d}")
    print(f"  Declined:     {n_declined:5d}")
    print(f"  Yard delivered: {n_yard_delivered}/{len(recs)}")

    # Center on Florida
    fmap = folium.Map(location=[28.0, -82.5], zoom_start=7, tiles="cartodbpositron",
                      world_copy_jump=True)

    # ── Status layers (one per status) ───────────────────────────────────────
    layers: dict[str, MarkerCluster] = {}
    for status, (color, icon, label, show_default) in STATUS_STYLE.items():
        n = int((sites["Install_Status"].fillna("Pending") == status).sum())
        layer_label = f"{label} ({n})"
        if args.no_cluster:
            fg = folium.FeatureGroup(name=layer_label, show=show_default)
        else:
            fg = MarkerCluster(name=layer_label, show=show_default)
        fg.add_to(fmap)
        layers[status] = fg

    n_plotted = 0
    for _, r in sites.iterrows():
        try:
            lat = float(r["Lat"]); lon = float(r["Lon"])
        except (TypeError, ValueError, KeyError):
            continue
        status = _str(r.get("Install_Status")) or "Pending"
        if status not in STATUS_STYLE:
            status = "Pending"
        color, icon_name, label, _ = STATUS_STYLE[status]

        name = _str(r.get("Site_Name")) or "(no name)"
        county = _str(r.get("County"))
        tier = _str(r.get("Tier"))
        addr = _str(r.get("Address"))
        phone = _str(r.get("Phone"))
        email = _str(r.get("Email"))
        owner = _str(r.get("Owner_Contact"))
        notes = _str(r.get("Notes"))
        cid = _str(r.get("Candidate_ID"))
        maps_link = f"https://www.google.com/maps?q={lat},{lon}"

        approval = _str(r.get("Approval_Status"))

        # Suggested storefronts block (when listed business hard to find)
        sf_parts = []
        for i in (1, 2, 3):
            sf_raw = r.get(f"Nearest_Storefront_{i}")
            if sf_raw is None:
                continue
            try:
                if isinstance(sf_raw, float) and sf_raw != sf_raw:
                    continue
            except Exception:
                pass
            sf = str(sf_raw).strip()
            if not sf or sf.lower() in ("nan", "none", "null"):
                continue
            d = r.get(f"Storefront_{i}_Distance_M")
            try:
                if d is not None and not (isinstance(d, float) and d != d):
                    sf_parts.append(f"{sf} ({int(d)}m)")
                else:
                    sf_parts.append(sf)
            except (TypeError, ValueError):
                sf_parts.append(sf)
        sf_block = ""
        if sf_parts:
            sf_lines = "<br>".join(f"&nbsp;&nbsp;• {s}" for s in sf_parts)
            sf_block = f"<small><b>🏪 Suggested storefronts nearby:</b><br>{sf_lines}</small><br>"

        popup = (
            f"<b>{name}</b><br>"
            f"<i>{cid}</i> &nbsp; {county} &nbsp; Tier {tier}<br>"
            f"<b>Status: {status}</b>"
            + (f" &nbsp; <small>(Approval: {approval})</small>" if approval and approval != "Pending" else "")
            + "<br>"
            + (f"{addr}<br>" if addr else "")
            + (f"📞 <b>{phone}</b><br>" if phone else "")
            + (f"✉ {email}<br>" if email else "")
            + (f"<b>Owner:</b> {owner}<br>" if owner else "")
            + (f"<small>Notes: {notes}</small><br>" if notes else "")
            + sf_block
            + f"<a href='{maps_link}' target='_blank'>Open in Google Maps</a>"
        )
        tooltip = f"{status}: {name} · {county}"

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup, max_width=360),
            tooltip=tooltip,
            icon=folium.Icon(color=color, icon=icon_name, prefix="fa"),
        ).add_to(layers[status])
        n_plotted += 1

    # ── REC yard-drop layer (color by delivery Status) ───────────────────────
    yard_delivered_layer = folium.FeatureGroup(name=f"🚚 Yard Delivered ({n_yard_delivered})", show=True)
    yard_pending_layer = folium.FeatureGroup(name=f"📦 Yard Pending ({len(recs)-n_yard_delivered})", show=True)
    yard_delivered_layer.add_to(fmap)
    yard_pending_layer.add_to(fmap)

    n_yard_plotted = 0
    for _, r in recs.iterrows():
        try:
            lat = float(r["Drop_Lat"]); lon = float(r["Drop_Lon"])
        except (TypeError, ValueError, KeyError):
            continue
        status = _str(r.get("Status")) or "Scheduled"
        county = _str(r.get("County"))
        chair = _str(r.get("Chair_Name"))
        chair_phone = _str(r.get("Chair_Phone"))
        chair_email = _str(r.get("Chair_Email"))
        del_phone = _str(r.get("Delivery_Phone"))
        qty = r.get("Plan_4000_Quantity") or 0
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 0
        addr = _str(r.get("Drop_Address"))
        delivery_date = _str(r.get("Delivery_Date"))

        color, icon = YARD_STATUS_STYLE.get(status, ("orange", "star"))
        # Use star icon for yard drops to differentiate from 4x8
        icon = "star"

        popup = (
            f"<b>{county} REC</b><br>"
            f"<b>{qty} yard signs</b> &nbsp; <b>Status: {status}</b><br>"
            + (f"<small>Delivery: {delivery_date}</small><br>" if delivery_date else "")
            + f"<hr style='margin:4px 0'>"
            + (f"<b>Chair:</b> {chair}<br>" if chair else "")
            + (f"📞 {chair_phone}<br>" if chair_phone else "")
            + (f"✉ {chair_email}<br>" if chair_email else "")
            + (f"<b>Delivery phone:</b> {del_phone}<br>" if del_phone else "")
            + (f"<small>Drop site: {addr}</small>" if addr else "")
        )
        tooltip = f"{county} REC: {status} ({qty} signs)"

        layer = yard_delivered_layer if status == "Delivered" else yard_pending_layer
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup, max_width=380),
            tooltip=tooltip,
            icon=folium.Icon(color=color, icon=icon, prefix="fa"),
        ).add_to(layer)
        n_yard_plotted += 1

    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)

    # ── Title bar ────────────────────────────────────────────────────────────
    pct_installed = (n_installed / n_total) * 100 if n_total else 0
    title = f"""
    <div style="position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
                z-index: 9999; background: white; padding: 10px 18px;
                border: 1px solid #999; border-radius: 4px;
                font: 14px sans-serif; font-weight: bold;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); min-width: 600px; text-align: center;">
      Florida Sign Operations — Status Map<br>
      <span style="font-size: 12px; font-weight: normal;">
        ✅ {n_installed} installed &nbsp;&middot;&nbsp;
        📅 {n_approved} approved &nbsp;&middot;&nbsp;
        ⏳ {n_pending} pending &nbsp;&middot;&nbsp;
        ❌ {n_declined} declined
        &nbsp;|&nbsp; <b>{pct_installed:.0f}% complete</b>
        &nbsp;|&nbsp; 🚚 {n_yard_delivered}/{len(recs)} REC deliveries
      </span><br>
      <span style="font-size: 10px; color: #666; font-weight: normal;">
        Refreshed {datetime.now().strftime('%B %d, %Y %H:%M')}
      </span>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(title))

    # ── Legend ───────────────────────────────────────────────────────────────
    legend = """
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 12px 14px; border: 1px solid #999;
                border-radius: 4px; font: 12px sans-serif; line-height: 1.7;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
      <b>4×8 Site Status</b><br>
      <span style="color: #2ecc71;">●</span> Installed (live)<br>
      <span style="color: #3498db;">●</span> Approved (scheduled)<br>
      <span style="color: #f39c12;">●</span> Pending (to call)<br>
      <span style="color: #e67e22;">●</span> Site Issue<br>
      <span style="color: #95a5a6;">●</span> Declined<br>
      <span style="color: #e74c3c;">●</span> Removed / Damaged<br>
      <hr style="margin: 6px 0">
      <b>🌟 REC Yard Drops</b><br>
      <span style="color: #2ecc71;">★</span> Delivered<br>
      <span style="color: #f39c12;">★</span> Pending<br>
      <hr style="margin: 6px 0">
      <small>Toggle layers top-right.<br>Click pins for site details.</small>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend))

    # Save
    fmap.save(str(out))
    size_kb = out.stat().st_size / 1024
    print(f"\nWrote {out} ({size_kb:.0f} KB)")
    print(f"  4×8 pins:  {n_plotted}")
    print(f"  REC stars: {n_yard_plotted}")
    print(f"  Open in any browser.")
    return 0


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


if __name__ == "__main__":
    sys.exit(main())
