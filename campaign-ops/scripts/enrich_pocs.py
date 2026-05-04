#!/usr/bin/env python3
"""
Enrich Sign_Location_Candidates with phone / email / website POCs.

Hybrid waterfall (no hallucination — every value traces to a named source):
  Tier 1: OSM tag extraction from `OSM_Tags_JSON` (instant)
  Tier 2: Yelp Fusion API match-by-coords (rate-limited, ~10 min for 2,000)
  Tier 3: Click-to-search URLs for residual rows (Google / Yelp / Sunbiz / Maps)

Phone validation via google's libphonenumber port (`phonenumbers`).
Toll-free + out-of-state numbers flagged for human review, not rejected.

Usage:
    python scripts/enrich_pocs.py
    python scripts/enrich_pocs.py --no-yelp           # OSM + click-search only
    YELP_API_KEY=xxx python scripts/enrich_pocs.py    # enable Yelp Tier 2

Yelp API key (free, 5,000 calls/day): https://www.yelp.com/developers
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from urllib.parse import quote_plus

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
YELP_CACHE = "data/clean/_yelp_cache.json"
YELP_ENDPOINT = "https://api.yelp.com/v3/businesses/search"

# Florida area codes (FL has new ones — 472 and 656 added in 2020s).
FL_AREA_CODES = {
    "239", "305", "321", "352", "386", "407", "472", "561", "656", "689",
    "727", "754", "772", "786", "813", "850", "863", "904", "941", "954",
}
TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}

# OSM tag key precedence
PHONE_KEYS = ["phone", "contact:phone", "phone:mobile", "phone:1", "contact:mobile"]
EMAIL_KEYS = ["email", "contact:email"]
WEB_KEYS = ["website", "contact:website", "url", "contact:url"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enrich Sign_Location_Candidates with POCs.")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--no-yelp", action="store_true", help="Skip Tier 2 Yelp lookup.")
    p.add_argument("--yelp-radius", type=int, default=200,
                   help="Yelp search radius in meters (default: 200).")
    p.add_argument("--name-fuzz-threshold", type=int, default=75,
                   help="rapidfuzz token_set_ratio min for Yelp match (default: 75).")
    p.add_argument("--max-distance-m", type=int, default=150,
                   help="Max distance from OSM coords to Yelp result (default: 150m).")
    p.add_argument("--rate-sleep", type=float, default=0.25,
                   help="Sleep between Yelp calls (default: 0.25s).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import pandas as pd
        import phonenumbers
        from rapidfuzz import fuzz
        import httpx
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    if not master.exists():
        print(f"ERROR: master not found: {master}", file=sys.stderr)
        return 1

    df = mio.read_sheet_safe(master, "Sign_Location_Candidates")
    if df.empty:
        print("ERROR: Sign_Location_Candidates sheet is empty. Run find_sign_locations.py first.",
              file=sys.stderr)
        return 1
    print(f"Loaded {len(df)} candidates.")

    yelp_key = os.environ.get("YELP_API_KEY", "").strip()
    use_yelp = not args.no_yelp and bool(yelp_key)
    if args.no_yelp:
        print("Yelp Tier 2 disabled by --no-yelp flag.")
    elif not yelp_key:
        print("YELP_API_KEY env var not set; Tier 2 (Yelp) skipped. "
              "Get a free key: https://www.yelp.com/developers")
    else:
        print("Yelp Tier 2 enabled.")

    yelp_cache = _load_yelp_cache(YELP_CACHE)

    n_osm = n_yelp = n_lookup = 0
    yelp_calls = yelp_hits = 0

    for idx, row in df.iterrows():
        # ── Tier 1: OSM tags
        tags = _parse_tags(row.get("OSM_Tags_JSON"))
        phone, p_src = "", ""
        email, e_src = "", ""
        website, w_src = "", ""

        for k in PHONE_KEYS:
            if k in tags:
                v = _validate_phone(tags[k], phonenumbers)
                if v:
                    phone, p_src = v, f"osm:{k}"
                    break
        for k in EMAIL_KEYS:
            if k in tags:
                v = _validate_email(tags[k])
                if v:
                    email, e_src = v, f"osm:{k}"
                    break
        for k in WEB_KEYS:
            if k in tags:
                v = tags[k].strip()
                if v.startswith(("http://", "https://", "www.")):
                    if v.startswith("www."):
                        v = "http://" + v
                    website, w_src = v, f"osm:{k}"
                    break

        # ── Tier 2: Yelp (only if phone is still missing)
        if use_yelp and not phone:
            name = str(row.get("Name") or "").strip()
            lat = row.get("Lat")
            lon = row.get("Lon")
            if name and pd.notna(lat) and pd.notna(lon):
                cache_key = f"{round(float(lat), 5)},{round(float(lon), 5)}|{name.lower()}"
                if cache_key in yelp_cache:
                    yelp_result = yelp_cache[cache_key]
                else:
                    yelp_calls += 1
                    yelp_result = _yelp_search(httpx, yelp_key, name, float(lat), float(lon),
                                               args.yelp_radius)
                    yelp_cache[cache_key] = yelp_result
                    time.sleep(args.rate_sleep)

                match = _yelp_match(yelp_result, name, float(lat), float(lon),
                                    args.name_fuzz_threshold, args.max_distance_m, fuzz)
                if match:
                    yelp_hits += 1
                    if not phone:
                        v = _validate_phone(match.get("phone", ""), phonenumbers)
                        if v:
                            phone, p_src = v, "yelp"
                    if not website and match.get("url"):
                        website, w_src = match["url"], "yelp"

        # ── Tier 3: Click-to-search URLs (always)
        name = str(row.get("Name") or "").strip()
        # Strip parenthetical fallbacks like "(see Maps_Link)"
        name_clean = name.split("(")[0].strip() or name
        county = str(row.get("County") or "").strip()
        city = _extract_city(row.get("Address") or "")
        loc_str = f"{city + ', ' if city else ''}{county} County FL"

        google_url = (
            f"https://www.google.com/search?q={quote_plus(name_clean + ' ' + loc_str)}"
            if name_clean else ""
        )
        yelp_search_url = (
            f"https://www.yelp.com/search?find_desc={quote_plus(name_clean)}"
            f"&find_loc={quote_plus(loc_str)}"
            if name_clean else ""
        )
        sunbiz_url = (
            f"https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResultDetail"
            f"?searchNameOrder={quote_plus(name_clean.upper())}"
            if name_clean else ""
        )

        # POC status
        if phone and email:
            poc_status = "verified_full"
        elif phone:
            poc_status = "verified_phone"
        elif email:
            poc_status = "verified_email"
        else:
            poc_status = "needs_lookup"

        # Source classification for stats
        if p_src.startswith("osm") or e_src.startswith("osm"):
            n_osm += 1
        elif p_src == "yelp" or w_src == "yelp":
            n_yelp += 1
        else:
            n_lookup += 1

        df.at[idx, "Phone"] = phone
        df.at[idx, "Phone_Source"] = p_src or ("manual_required" if not phone else "")
        df.at[idx, "Email"] = email
        df.at[idx, "Email_Source"] = e_src or ("manual_required" if not email else "")
        df.at[idx, "Website"] = website
        df.at[idx, "Website_Source"] = w_src or ("manual_required" if not website else "")
        df.at[idx, "POC_Status"] = poc_status
        df.at[idx, "Google_Search_URL"] = google_url
        df.at[idx, "Yelp_Search_URL"] = yelp_search_url
        df.at[idx, "Sunbiz_Search_URL"] = sunbiz_url

    _save_yelp_cache(YELP_CACHE, yelp_cache)

    # Stats
    total = len(df)
    has_phone = int((df["Phone"].astype(str).str.len() > 0).sum())
    has_email = int((df["Email"].astype(str).str.len() > 0).sum())
    has_web = int((df["Website"].astype(str).str.len() > 0).sum())
    print(f"\nEnrichment complete:")
    print(f"  Phone:   {has_phone}/{total} ({has_phone/total:.0%})")
    print(f"  Email:   {has_email}/{total} ({has_email/total:.0%})")
    print(f"  Website: {has_web}/{total} ({has_web/total:.0%})")
    print(f"\nSources (any field present):")
    print(f"  OSM tags only:    {n_osm}")
    print(f"  Yelp matched:     {n_yelp}")
    print(f"  Manual required:  {n_lookup}")
    if use_yelp:
        print(f"\nYelp API calls:   {yelp_calls}  (hits: {yelp_hits})")

    print(f"\nWriting back to Sign_Location_Candidates ...")
    mio.replace_sheet(master, "Sign_Location_Candidates", df,
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

def _parse_tags(raw) -> dict:
    if not raw or not isinstance(raw, str):
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _validate_phone(raw: str, phonenumbers) -> str:
    """Return normalized phone string or empty if invalid."""
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip()
    # Some OSM rows have multiple phones split by ';' or ','
    for candidate in raw.replace(";", ",").split(","):
        try:
            num = phonenumbers.parse(candidate.strip(), "US")
        except phonenumbers.NumberParseException:
            continue
        if not phonenumbers.is_valid_number(num):
            continue
        if num.country_code != 1:
            continue
        e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
        area = e164[2:5]
        suffix = ""
        if area in FL_AREA_CODES:
            pass  # canonical
        elif area in TOLL_FREE:
            suffix = " (toll-free)"
        else:
            suffix = " (out-of-state — verify)"
        return f"{national}{suffix}"
    return ""


def _validate_email(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip().lower()
    # cheap RFC-ish check
    if "@" not in raw or "." not in raw.split("@")[-1]:
        return ""
    if " " in raw:
        return ""
    return raw


def _extract_city(addr: str) -> str:
    """Pull city from 'street, City, FL' formatted addresses."""
    if not addr or not isinstance(addr, str):
        return ""
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 2:
        cand = parts[-2] if parts[-1].upper() in ("FL", "FLORIDA") else parts[-1]
        if cand and cand.upper() not in ("FL", "FLORIDA"):
            return cand
    return ""


def _yelp_search(httpx, key, name, lat, lon, radius):
    """Yelp Fusion API call. Returns list of business dicts (top 5)."""
    headers = {"Authorization": f"Bearer {key}"}
    params = {
        "term": name[:200],
        "latitude": lat,
        "longitude": lon,
        "radius": min(radius, 40000),
        "limit": 5,
    }
    try:
        r = httpx.get(YELP_ENDPOINT, headers=headers, params=params, timeout=10.0)
        if r.status_code == 429:
            time.sleep(2.0)
            r = httpx.get(YELP_ENDPOINT, headers=headers, params=params, timeout=10.0)
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("businesses", []) or []
    except Exception:
        return []


def _yelp_match(results, osm_name, osm_lat, osm_lon, fuzz_threshold, max_dist_m, fuzz):
    """Pick top result that satisfies BOTH name fuzz AND geo distance."""
    if not results:
        return None
    osm_name_norm = osm_name.lower().strip()
    for biz in results:
        ynm = (biz.get("name") or "").lower().strip()
        if not ynm:
            continue
        score = fuzz.token_set_ratio(osm_name_norm, ynm)
        if score < fuzz_threshold:
            continue
        coords = biz.get("coordinates") or {}
        ylat = coords.get("latitude")
        ylon = coords.get("longitude")
        if ylat is None or ylon is None:
            continue
        dist = _haversine_m(osm_lat, osm_lon, float(ylat), float(ylon))
        if dist > max_dist_m:
            continue
        if biz.get("is_closed"):
            continue
        return biz
    return None


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _load_yelp_cache(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_yelp_cache(path, cache):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(cache, ensure_ascii=False))
    except Exception as e:
        print(f"WARN: could not save Yelp cache: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
