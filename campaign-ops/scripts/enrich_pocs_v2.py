#!/usr/bin/env python3
"""
Phone-POC enrichment V2 — extends V1 with three free, no-API-key tiers:
  Tier 2.5 — Overpass API (OSM bulk query) by name + radius
  Tier 3   — Website scrape (homepage + /contact + /about + /contact-us)
  Tier 4   — Nominatim reverse-geocode with extratags

Targets only rows where Phone is empty AND Phone_Source ∈ {"", "manual_required"}.
Hallucination protection:
  - Every phone validated via `phonenumbers.is_valid_number`
  - Every value tagged with traceable `Phone_Source`
  - Website regex requires phone to be inside <a href='tel:...'> OR within 200
    chars of "phone"/"call"/"contact"/"tel" keyword
Caches: data/clean/_overpass_cache.json, _website_cache.json, _nominatim_v2_cache.json,
        data/clean/_robots_cache.json

Usage:
    python scripts/enrich_pocs_v2.py
    python scripts/enrich_pocs_v2.py --no-overpass --no-nominatim   # website only
    python scripts/enrich_pocs_v2.py --max-rows 500                 # cap for testing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from urllib.robotparser import RobotFileParser

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
OVERPASS_CACHE = "data/clean/_overpass_cache.json"
WEBSITE_CACHE = "data/clean/_website_cache.json"
NOMINATIM_CACHE = "data/clean/_nominatim_v2_cache.json"
ROBOTS_CACHE = "data/clean/_robots_cache.json"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

PHONE_KEYS = ["phone", "contact:phone", "phone:mobile", "phone:1", "contact:mobile"]

USER_AGENT = "fl-ag-campaign-ops/1.0 (campaign signage operations)"

# Florida area codes (incl. new 472 / 656)
FL_AREA_CODES = {
    "239", "305", "321", "352", "386", "407", "472", "561", "656", "689",
    "727", "754", "772", "786", "813", "850", "863", "904", "941", "954",
}
TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phone enrichment V2 (Overpass + Website + Nominatim).")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--no-overpass", action="store_true")
    p.add_argument("--no-website", action="store_true")
    p.add_argument("--no-nominatim", action="store_true")
    p.add_argument("--max-rows", type=int, default=0,
                   help="Cap residual rows processed (0 = no cap)")
    p.add_argument("--overpass-radius", type=int, default=200)
    p.add_argument("--name-fuzz", type=int, default=75)
    p.add_argument("--max-distance-m", type=int, default=200)
    p.add_argument("--rate-overpass", type=float, default=1.1)
    p.add_argument("--rate-website", type=float, default=1.0)
    p.add_argument("--rate-nominatim", type=float, default=1.1)
    p.add_argument("--http-timeout", type=float, default=8.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import warnings; warnings.filterwarnings("ignore")
        import pandas as pd
        import phonenumbers
        from rapidfuzz import fuzz
        import httpx
        from bs4 import BeautifulSoup
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _master_io as mio  # type: ignore

    master = Path(args.master)
    sdp = mio.read_sheet_safe(master, "Sign_Deployment_Plan")
    if sdp.empty:
        print("ERROR: Sign_Deployment_Plan empty.", file=sys.stderr)
        return 1

    # Identify residual rows (no phone, source unset/manual_required)
    has_phone = sdp["Phone"].fillna("").astype(str).str.strip().str.len() > 0
    src_blank = sdp["Phone_Source"].fillna("").astype(str).str.strip().isin(["", "manual_required"])
    residual_mask = (~has_phone) & src_blank
    residual = sdp[residual_mask].copy()
    if args.max_rows and args.max_rows < len(residual):
        residual = residual.head(args.max_rows)
    print(f"Sign_Deployment_Plan: {len(sdp)} rows total")
    print(f"Already have phone:    {int(has_phone.sum())}")
    print(f"Residual to process:   {len(residual)}")
    print()

    # Caches
    overpass_cache = _load_cache(OVERPASS_CACHE)
    website_cache = _load_cache(WEBSITE_CACHE)
    nom_cache = _load_cache(NOMINATIM_CACHE)
    robots_cache = _load_cache(ROBOTS_CACHE)

    n_op = n_web = n_nom = 0
    new_phones: dict[int, tuple[str, str]] = {}  # idx -> (phone, source)
    updates_per_county: dict[str, int] = {}

    httpx_client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=args.http_timeout,
                                follow_redirects=True)

    try:
        # ── TIER 2.5: Overpass ────────────────────────────────────────────────
        if not args.no_overpass:
            print("─── Tier 2.5: Overpass API (OSM name+radius re-query) ───")
            for i, (idx, row) in enumerate(residual.iterrows(), start=1):
                if i % 50 == 0:
                    print(f"  [{i}/{len(residual)}] Overpass progress: +{n_op}")
                name = str(row.get("Name") or "").strip()
                lat = row.get("Lat"); lon = row.get("Lon")
                if not name or lat is None or lon is None:
                    continue
                try:
                    lat = float(lat); lon = float(lon)
                except (TypeError, ValueError):
                    continue
                key = f"{round(lat,5)},{round(lon,5)}|{name.lower()}"
                if key in overpass_cache:
                    result = overpass_cache[key]
                else:
                    result = _overpass_lookup(httpx_client, name, lat, lon, args.overpass_radius)
                    overpass_cache[key] = result
                    time.sleep(args.rate_overpass)
                if not result:
                    continue
                # Match by fuzz + distance
                best = None
                for elem in result.get("elements", []):
                    tags = elem.get("tags", {}) or {}
                    cand_name = tags.get("name", "")
                    if not cand_name:
                        continue
                    score = fuzz.token_set_ratio(name.lower(), cand_name.lower())
                    if score < args.name_fuzz:
                        continue
                    e_lat = elem.get("lat") or (elem.get("center") or {}).get("lat")
                    e_lon = elem.get("lon") or (elem.get("center") or {}).get("lon")
                    if e_lat is None or e_lon is None:
                        continue
                    d = _haversine(lat, lon, e_lat, e_lon)
                    if d > args.max_distance_m:
                        continue
                    if best is None or d < best[0]:
                        best = (d, tags)
                if not best:
                    continue
                tags = best[1]
                phone = ""
                for k in PHONE_KEYS:
                    if k in tags:
                        v = _validate_phone(tags[k], phonenumbers)
                        if v:
                            phone = v; break
                if phone:
                    new_phones[idx] = (phone, "overpass:osm")
                    n_op += 1
                    c = row.get("County", "?"); updates_per_county[c] = updates_per_county.get(c, 0) + 1
            _save_cache(OVERPASS_CACHE, overpass_cache)
            print(f"  Overpass total: +{n_op}")
            print()

        # ── TIER 3: Website scrape ────────────────────────────────────────────
        if not args.no_website:
            print("─── Tier 3: Website scrape (homepage + /contact paths) ───")
            t3_start = time.time()
            seen_domains_per_run = set()
            for i, (idx, row) in enumerate(residual.iterrows(), start=1):
                if idx in new_phones:
                    continue  # already got phone from Overpass
                website = str(row.get("Website") or "").strip()
                if not website or website.lower() in ("nan", "none"):
                    continue
                if not website.startswith(("http://", "https://")):
                    website = "http://" + website.lstrip("/")
                domain = _domain(website)
                if not domain:
                    continue
                if i % 50 == 0:
                    elapsed = time.time() - t3_start
                    print(f"  [{i}/{len(residual)}] Website progress: +{n_web} ({elapsed:.0f}s)")
                # Try cached result first
                if website in website_cache:
                    cached = website_cache[website]
                    if cached and cached.get("phone"):
                        v = _validate_phone(cached["phone"], phonenumbers)
                        if v:
                            new_phones[idx] = (v, f"website:{domain}")
                            n_web += 1
                            c = row.get("County", "?"); updates_per_county[c] = updates_per_county.get(c, 0) + 1
                    continue
                # Robots.txt enforcement
                if not _robots_allows(httpx_client, domain, robots_cache, args):
                    website_cache[website] = {"phone": None, "skipped": "robots"}
                    continue
                # Fetch homepage + /contact + /about + /contact-us
                phones_found = _scrape_website_phones(httpx_client, website, BeautifulSoup, phonenumbers)
                website_cache[website] = {"phone": phones_found[0] if phones_found else None}
                # Per-domain rate limit
                if domain not in seen_domains_per_run:
                    seen_domains_per_run.add(domain)
                    time.sleep(args.rate_website)
                if phones_found:
                    new_phones[idx] = (phones_found[0], f"website:{domain}")
                    n_web += 1
                    c = row.get("County", "?"); updates_per_county[c] = updates_per_county.get(c, 0) + 1
                # Periodic cache save (every 100 fetches)
                if i % 100 == 0:
                    _save_cache(WEBSITE_CACHE, website_cache)
                    _save_cache(ROBOTS_CACHE, robots_cache)
            _save_cache(WEBSITE_CACHE, website_cache)
            _save_cache(ROBOTS_CACHE, robots_cache)
            print(f"  Website total: +{n_web} (elapsed {time.time()-t3_start:.0f}s)")
            print()

        # ── TIER 4: Nominatim reverse-geocode with extratags ──────────────────
        if not args.no_nominatim:
            print("─── Tier 4: Nominatim reverse-geocode ───")
            for i, (idx, row) in enumerate(residual.iterrows(), start=1):
                if idx in new_phones:
                    continue
                lat = row.get("Lat"); lon = row.get("Lon")
                if lat is None or lon is None:
                    continue
                try:
                    lat = float(lat); lon = float(lon)
                except (TypeError, ValueError):
                    continue
                key = f"{round(lat,5)},{round(lon,5)}"
                if key in nom_cache:
                    result = nom_cache[key]
                else:
                    result = _nominatim_reverse(httpx_client, lat, lon)
                    nom_cache[key] = result
                    time.sleep(args.rate_nominatim)
                if not result:
                    continue
                extra = result.get("extratags") or {}
                phone = ""
                for k in ("phone", "contact:phone"):
                    if k in extra:
                        v = _validate_phone(extra[k], phonenumbers)
                        if v:
                            phone = v; break
                if phone:
                    new_phones[idx] = (phone, "nominatim:reverse")
                    n_nom += 1
                    c = row.get("County", "?"); updates_per_county[c] = updates_per_county.get(c, 0) + 1
                if i % 100 == 0:
                    _save_cache(NOMINATIM_CACHE, nom_cache)
            _save_cache(NOMINATIM_CACHE, nom_cache)
            print(f"  Nominatim total: +{n_nom}")
            print()
    finally:
        httpx_client.close()
        # Final cache saves
        _save_cache(OVERPASS_CACHE, overpass_cache)
        _save_cache(WEBSITE_CACHE, website_cache)
        _save_cache(NOMINATIM_CACHE, nom_cache)
        _save_cache(ROBOTS_CACHE, robots_cache)

    # ── APPLY UPDATES ────────────────────────────────────────────────────────
    print(f"─── Applying {len(new_phones)} new phones ───")
    for idx, (phone, src) in new_phones.items():
        sdp.at[idx, "Phone"] = phone
        sdp.at[idx, "Phone_Source"] = src

    # Stats
    new_total = int((sdp["Phone"].fillna("").astype(str).str.len() > 0).sum())
    primary = sdp[sdp["Plan"] == "primary"]
    primary_phone = int((primary["Phone"].fillna("").astype(str).str.len() > 0).sum())

    print(f"\nFinal phone coverage:")
    print(f"  Sign_Deployment_Plan total:   {new_total}/{len(sdp)} ({new_total/len(sdp):.0%})")
    print(f"  Primary plan:                 {primary_phone}/{len(primary)} ({primary_phone/len(primary):.0%})")
    print(f"\nNew phones by tier:")
    print(f"  Overpass:    +{n_op}")
    print(f"  Website:     +{n_web}")
    print(f"  Nominatim:   +{n_nom}")
    print(f"  TOTAL added: +{n_op + n_web + n_nom}")

    if updates_per_county:
        print(f"\nTop 10 counties by new phones:")
        top = sorted(updates_per_county.items(), key=lambda kv: -kv[1])[:10]
        for c, n in top:
            print(f"  {c:18s} +{n}")

    # Source distribution
    src_counts = sdp["Phone_Source"].fillna("").value_counts().head(10)
    print(f"\nPhone_Source distribution:")
    for src, n in src_counts.items():
        if src:
            print(f"  {src:25s} {n}")

    print(f"\nWriting Sign_Deployment_Plan to {master} ...")
    mio.replace_sheet(master, "Sign_Deployment_Plan", sdp,
                      color_col="Plan",
                      color_map={"primary": "D4EDDA", "replacement": "FFF3CD"})

    # Also enrich Sign_Location_Candidates with the same data so future re-selects benefit
    print(f"\nPropagating new phones back to Sign_Location_Candidates ...")
    slc = mio.read_sheet_safe(master, "Sign_Location_Candidates")
    if not slc.empty and len(new_phones) > 0:
        # Match by Candidate_ID
        sdp_idx = sdp.set_index("Candidate_ID")[["Phone", "Phone_Source"]]
        slc_with_new = 0
        for slc_idx, slc_row in slc.iterrows():
            cid = slc_row.get("Candidate_ID")
            if cid in sdp_idx.index:
                p = sdp_idx.at[cid, "Phone"]
                s = sdp_idx.at[cid, "Phone_Source"]
                if isinstance(p, str) and p and not is_blank(slc_row.get("Phone")):
                    continue  # already has phone
                if isinstance(p, str) and p:
                    slc.at[slc_idx, "Phone"] = p
                    slc.at[slc_idx, "Phone_Source"] = s
                    slc_with_new += 1
        if slc_with_new:
            mio.replace_sheet(master, "Sign_Location_Candidates", slc,
                              color_col="Type",
                              color_map={"intersection": "EAF3FB", "commercial": "FFF8E1", "agri_civic": "E8F5E9"})
            print(f"  Propagated {slc_with_new} phones to Sign_Location_Candidates")

    print("\nDone.")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:
        return True
    s = str(v).strip().lower()
    return s in ("", "nan", "none", "null")


def _validate_phone(raw, phonenumbers) -> str:
    if not raw:
        return ""
    raw = str(raw).strip()
    if not raw or raw.lower() == "nan":
        return ""
    for cand in raw.replace(";", ",").split(","):
        try:
            num = phonenumbers.parse(cand.strip(), "US")
        except phonenumbers.NumberParseException:
            continue
        if not phonenumbers.is_valid_number(num):
            continue
        if num.country_code != 1:
            continue
        e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
        area = e164[2:5]
        if area in FL_AREA_CODES:
            return national
        if area in TOLL_FREE:
            return f"{national} (toll-free)"
        return f"{national} (out-of-state — verify)"
    return ""


def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))


# ── Overpass ──────────────────────────────────────────────────────────────────

def _overpass_lookup(client, name: str, lat: float, lon: float, radius: int):
    """Search OSM by name + radius. Returns parsed JSON or None."""
    # Escape regex chars; limit name length
    safe_name = re.escape(name[:80])
    query = (
        f"[out:json][timeout:15];"
        f"("
        f'  node(around:{radius},{lat},{lon})["name"~"{safe_name}",i];'
        f'  way(around:{radius},{lat},{lon})["name"~"{safe_name}",i];'
        f");"
        f"out tags center;"
    )
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            r = client.post(endpoint, data={"data": query}, timeout=20.0)
            if r.status_code == 429:
                time.sleep(3.0)
                continue
            if r.status_code == 200:
                return r.json()
        except Exception:
            continue
    return None


# ── Website scraping ──────────────────────────────────────────────────────────

CONTACT_PATHS = ("/", "/contact", "/contact-us", "/about", "/contacts")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?(\d{3})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})")
KEYWORD_RE = re.compile(r"\b(phone|tel|call|contact)\b", re.IGNORECASE)


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _robots_allows(client, domain: str, robots_cache: dict, args) -> bool:
    """Per-domain robots.txt cache. Default-allow if fetch fails."""
    if domain in robots_cache:
        return robots_cache[domain]
    url = f"https://{domain}/robots.txt"
    try:
        r = client.get(url, timeout=5.0)
        if r.status_code != 200:
            robots_cache[domain] = True
            return True
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        # Use a generic test path; we just need to know we're not site-blocked
        allowed = rp.can_fetch(USER_AGENT, f"https://{domain}/contact")
        robots_cache[domain] = bool(allowed)
        return bool(allowed)
    except Exception:
        robots_cache[domain] = True
        return True


def _scrape_website_phones(client, base_url: str, BeautifulSoup, phonenumbers) -> list[str]:
    """Fetch homepage + common contact paths, extract validated phones.
    Returns list of unique validated phones, in priority order
    (tel: anchors first, then keyword-proximity matches)."""
    found: list[str] = []
    seen_e164 = set()
    base_url = base_url.rstrip("/")
    # Try paths
    pages_html = []
    for path in CONTACT_PATHS:
        url = base_url + path
        try:
            r = client.get(url, timeout=client.timeout.read or 8.0)
            if r.status_code != 200:
                continue
            ctype = r.headers.get("content-type", "").lower()
            if "html" not in ctype and "text" not in ctype:
                continue
            pages_html.append((url, r.text))
        except Exception:
            continue
        if len(pages_html) >= 2:  # cap fetches per site
            break
    # Parse
    for url, html in pages_html:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            continue
        # Priority 1: tel: anchors
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("tel:"):
                continue
            raw = href[4:].split("?")[0]
            v = _validate_phone(raw, phonenumbers)
            if v:
                e164 = re.sub(r"\D", "", v)
                if e164 not in seen_e164:
                    seen_e164.add(e164); found.append(v)
        # Priority 2: regex matches near keywords
        text = soup.get_text(" ", strip=True)
        # Limit search window: only consider phone matches within 200 chars of keyword
        for m in PHONE_RE.finditer(text):
            window_start = max(0, m.start() - 200)
            window_end = min(len(text), m.end() + 50)
            window = text[window_start:window_end]
            if not KEYWORD_RE.search(window):
                continue
            full = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
            v = _validate_phone(full, phonenumbers)
            if v:
                e164 = re.sub(r"\D", "", v)
                if e164 not in seen_e164:
                    seen_e164.add(e164); found.append(v)
    return found


# ── Nominatim ─────────────────────────────────────────────────────────────────

def _nominatim_reverse(client, lat: float, lon: float):
    params = {"lat": lat, "lon": lon, "format": "json", "extratags": 1, "addressdetails": 0, "zoom": 18}
    try:
        r = client.get("https://nominatim.openstreetmap.org/reverse", params=params, timeout=8.0)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_cache(path, cache):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(cache, ensure_ascii=False))
    except Exception as e:
        print(f"WARN: cache save failed for {path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
