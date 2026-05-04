#!/usr/bin/env python3
"""
Phone-POC enrichment V3 — three new tiers chasing the residual ~1,200 sites
that have no phone after V1 (OSM tags) and V2 (website regex / Nominatim).

Tiers (run in order; each only on rows still without phone):
  Tier 5 — Schema.org JSON-LD on the business's website
           Highest-trust source: structured machine-readable telephone field.
           Re-fetches homepage + /contact for rows with a Website URL.

  Tier 6 — YellowPages public listing search
           URL: https://www.yellowpages.com/search?search_terms=<name>&geo_location_terms=<city>+FL
           Strict accept: fuzzy name match ≥75 + city match in result address.

  Tier 7 — DuckDuckGo HTML search (last resort)
           URL: https://html.duckduckgo.com/html/?q=<name>+<city>+FL+phone
           Strict accept: result snippet contains BOTH business name (fuzz ≥75)
           AND the city; phone validated via libphonenumber.

Hallucination guards (mandatory):
  - phonenumbers.is_valid_number() on every candidate
  - For Tiers 6 + 7: name fuzz match required + geographic match (city)
  - Phone_Source always populated with traceable URL

Caches (re-runs are nearly free):
  data/clean/_jsonld_cache.json
  data/clean/_yellowpages_cache.json
  data/clean/_ddg_cache.json

Usage:
    python scripts/enrich_pocs_v3.py
    python scripts/enrich_pocs_v3.py --no-ddg          # Schema.org + YP only
    python scripts/enrich_pocs_v3.py --max-rows 500    # cap for testing
    python scripts/enrich_pocs_v3.py --max-rows 25     # quick smoke test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus, urlparse

DEFAULT_MASTER = "outputs/campaign_ops_master.xlsx"
JSONLD_CACHE = "data/clean/_jsonld_cache.json"
YP_CACHE = "data/clean/_yellowpages_cache.json"
DDG_CACHE = "data/clean/_ddg_cache.json"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

FL_AREA_CODES = {
    "239", "305", "321", "352", "386", "407", "472", "561", "656", "689",
    "727", "754", "772", "786", "813", "850", "863", "904", "941", "954",
}
TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}

# Generic phone pattern (loose — phonenumbers does the strict validation)
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?(\d{3})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phone enrichment V3 (Schema.org + YellowPages + DDG).")
    p.add_argument("--master", default=DEFAULT_MASTER)
    p.add_argument("--no-jsonld", action="store_true")
    p.add_argument("--no-yellowpages", action="store_true")
    p.add_argument("--no-ddg", action="store_true")
    p.add_argument("--max-rows", type=int, default=0,
                   help="Cap residual rows processed (0 = no cap)")
    p.add_argument("--name-fuzz", type=int, default=75)
    p.add_argument("--rate-jsonld", type=float, default=1.0)
    p.add_argument("--rate-yp", type=float, default=1.5)
    p.add_argument("--rate-ddg", type=float, default=1.5)
    p.add_argument("--http-timeout", type=float, default=10.0)
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

    # Find residual: no phone, source unset/manual_required
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

    jsonld_cache = _load_cache(JSONLD_CACHE)
    yp_cache = _load_cache(YP_CACHE)
    ddg_cache = _load_cache(DDG_CACHE)

    n_jsonld = n_yp = n_ddg = 0
    new_phones: dict[int, tuple[str, str]] = {}

    client = httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
                          timeout=args.http_timeout, follow_redirects=True)

    try:
        # ── TIER 5: Schema.org JSON-LD ────────────────────────────────────────
        if not args.no_jsonld:
            print("─── Tier 5: Schema.org JSON-LD on business websites ───")
            t0 = time.time()
            for i, (idx, row) in enumerate(residual.iterrows(), start=1):
                website = _str(row.get("Website"))
                if not website:
                    continue
                if not website.startswith(("http://", "https://")):
                    website = "http://" + website.lstrip("/")
                if i % 50 == 0:
                    print(f"  [{i}/{len(residual)}] JSON-LD progress: +{n_jsonld} ({time.time()-t0:.0f}s)")
                if website in jsonld_cache:
                    cached = jsonld_cache[website]
                    if cached and cached.get("phone"):
                        v = _validate_phone(cached["phone"], phonenumbers)
                        if v:
                            new_phones[idx] = (v, f"jsonld:{_domain(website)}")
                            n_jsonld += 1
                    continue
                phone = _scrape_jsonld(client, website, BeautifulSoup, phonenumbers)
                jsonld_cache[website] = {"phone": phone}
                if phone:
                    new_phones[idx] = (phone, f"jsonld:{_domain(website)}")
                    n_jsonld += 1
                time.sleep(args.rate_jsonld)
                if i % 100 == 0:
                    _save_cache(JSONLD_CACHE, jsonld_cache)
            _save_cache(JSONLD_CACHE, jsonld_cache)
            print(f"  Tier 5 total: +{n_jsonld} (elapsed {time.time()-t0:.0f}s)")
            print()

        # ── TIER 6: YellowPages ───────────────────────────────────────────────
        if not args.no_yellowpages:
            print("─── Tier 6: YellowPages public listings ───")
            t0 = time.time()
            for i, (idx, row) in enumerate(residual.iterrows(), start=1):
                if idx in new_phones:
                    continue
                name = _str(row.get("Name"))
                county = _str(row.get("County"))
                city = _city_from_address(_str(row.get("Address"))) or county
                if not name or not city:
                    continue
                if i % 50 == 0:
                    print(f"  [{i}/{len(residual)}] YP progress: +{n_yp} ({time.time()-t0:.0f}s)")
                key = f"{name.lower()}||{city.lower()}"
                if key in yp_cache:
                    cached = yp_cache[key]
                    if cached and cached.get("phone"):
                        v = _validate_phone(cached["phone"], phonenumbers)
                        if v:
                            new_phones[idx] = (v, f"yellowpages")
                            n_yp += 1
                    continue
                phone = _yellowpages_lookup(client, name, city, BeautifulSoup,
                                            phonenumbers, fuzz, args.name_fuzz)
                yp_cache[key] = {"phone": phone}
                if phone:
                    new_phones[idx] = (phone, "yellowpages")
                    n_yp += 1
                time.sleep(args.rate_yp)
                if i % 100 == 0:
                    _save_cache(YP_CACHE, yp_cache)
            _save_cache(YP_CACHE, yp_cache)
            print(f"  Tier 6 total: +{n_yp} (elapsed {time.time()-t0:.0f}s)")
            print()

        # ── TIER 7: DuckDuckGo HTML (last resort, strict validation) ──────────
        if not args.no_ddg:
            print("─── Tier 7: DuckDuckGo HTML search (strict name+city match) ───")
            t0 = time.time()
            for i, (idx, row) in enumerate(residual.iterrows(), start=1):
                if idx in new_phones:
                    continue
                name = _str(row.get("Name"))
                county = _str(row.get("County"))
                city = _city_from_address(_str(row.get("Address"))) or county
                if not name or not city:
                    continue
                if i % 50 == 0:
                    print(f"  [{i}/{len(residual)}] DDG progress: +{n_ddg} ({time.time()-t0:.0f}s)")
                key = f"{name.lower()}||{city.lower()}"
                if key in ddg_cache:
                    cached = ddg_cache[key]
                    if cached and cached.get("phone"):
                        v = _validate_phone(cached["phone"], phonenumbers)
                        if v:
                            new_phones[idx] = (v, "ddg:strict-match")
                            n_ddg += 1
                    continue
                phone = _ddg_lookup(client, name, city, BeautifulSoup, phonenumbers,
                                    fuzz, args.name_fuzz)
                ddg_cache[key] = {"phone": phone}
                if phone:
                    new_phones[idx] = (phone, "ddg:strict-match")
                    n_ddg += 1
                time.sleep(args.rate_ddg)
                if i % 100 == 0:
                    _save_cache(DDG_CACHE, ddg_cache)
            _save_cache(DDG_CACHE, ddg_cache)
            print(f"  Tier 7 total: +{n_ddg} (elapsed {time.time()-t0:.0f}s)")
            print()

    finally:
        client.close()
        _save_cache(JSONLD_CACHE, jsonld_cache)
        _save_cache(YP_CACHE, yp_cache)
        _save_cache(DDG_CACHE, ddg_cache)

    # ── APPLY UPDATES ────────────────────────────────────────────────────────
    print(f"─── Applying {len(new_phones)} new phones ───")
    for idx, (phone, src) in new_phones.items():
        sdp.at[idx, "Phone"] = phone
        sdp.at[idx, "Phone_Source"] = src

    primary = sdp[sdp["Plan"] == "primary"]
    primary_phone = int((primary["Phone"].fillna("").astype(str).str.len() > 0).sum())
    print(f"\nFinal phone coverage on primary plan: "
          f"{primary_phone}/{len(primary)} ({primary_phone/len(primary):.0%})")
    print(f"\nNew phones added by tier:")
    print(f"  Tier 5 (Schema.org):   +{n_jsonld}")
    print(f"  Tier 6 (YellowPages):  +{n_yp}")
    print(f"  Tier 7 (DDG strict):   +{n_ddg}")
    print(f"  TOTAL added:           +{n_jsonld + n_yp + n_ddg}")

    print(f"\nWriting Sign_Deployment_Plan to {master} ...")
    mio.replace_sheet(master, "Sign_Deployment_Plan", sdp,
                      color_col="Plan",
                      color_map={"primary": "D4EDDA", "replacement": "FFF3CD"})

    # Propagate to Sign_Location_Candidates
    print(f"Propagating new phones to Sign_Location_Candidates ...")
    slc = mio.read_sheet_safe(master, "Sign_Location_Candidates")
    if not slc.empty and len(new_phones):
        sdp_idx = sdp.set_index("Candidate_ID")[["Phone", "Phone_Source"]]
        propagated = 0
        for slc_idx, slc_row in slc.iterrows():
            cid = slc_row.get("Candidate_ID")
            if cid in sdp_idx.index:
                p = sdp_idx.at[cid, "Phone"]
                if isinstance(p, str) and p:
                    cur = slc_row.get("Phone")
                    if cur is None or (isinstance(cur, float) and cur != cur) or str(cur).strip() == "":
                        slc.at[slc_idx, "Phone"] = p
                        slc.at[slc_idx, "Phone_Source"] = sdp_idx.at[cid, "Phone_Source"]
                        propagated += 1
        if propagated:
            mio.replace_sheet(master, "Sign_Location_Candidates", slc,
                              color_col="Type",
                              color_map={"intersection": "EAF3FB", "commercial": "FFF8E1", "agri_civic": "E8F5E9"})
            print(f"  Propagated {propagated} phones to Sign_Location_Candidates")

    print("\nDone.")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _city_from_address(addr: str) -> str:
    if not addr:
        return ""
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 2:
        cand = parts[-2] if parts[-1].upper() in ("FL", "FLORIDA") else parts[-1]
        if cand and cand.upper() not in ("FL", "FLORIDA"):
            # Strip trailing zip/state from city name
            cand = re.sub(r"\s+FL\s+\d{5}.*$", "", cand)
            cand = re.sub(r"\s+\d{5}.*$", "", cand)
            return cand.strip()
    return ""


def _validate_phone(raw, phonenumbers) -> str:
    if not raw:
        return ""
    raw = str(raw).strip()
    if not raw or raw.lower() == "nan":
        return ""
    for cand in raw.replace(";", ",").split(","):
        cand = cand.strip()
        try:
            num = phonenumbers.parse(cand, "US")
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


# ── Tier 5: Schema.org JSON-LD ────────────────────────────────────────────────

JSONLD_TYPES_OK = {"localbusiness", "organization", "restaurant", "store",
                   "automotivebusiness", "professionalservice", "homeandconstructionbusiness",
                   "foodestablishment", "lodgingbusiness", "place"}


def _scrape_jsonld(client, base_url: str, BeautifulSoup, phonenumbers) -> str:
    """Fetch base URL + /contact, look for Schema.org JSON-LD with telephone field."""
    base_url = base_url.rstrip("/")
    paths = (base_url, base_url + "/contact", base_url + "/contact-us")
    for url in paths[:3]:
        try:
            r = client.get(url, timeout=client.timeout.read or 8.0)
            if r.status_code != 200:
                continue
            ctype = r.headers.get("content-type", "").lower()
            if "html" not in ctype and "text" not in ctype:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                txt = script.string or script.text
                if not txt:
                    continue
                try:
                    data = json.loads(txt)
                except (json.JSONDecodeError, ValueError):
                    continue
                # Could be a single dict or a list
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # Sometimes wrapped in @graph
                    candidates = [item]
                    if "@graph" in item and isinstance(item["@graph"], list):
                        candidates = item["@graph"]
                    for cand in candidates:
                        if not isinstance(cand, dict):
                            continue
                        type_field = cand.get("@type", "")
                        if isinstance(type_field, list):
                            type_field = type_field[0] if type_field else ""
                        if str(type_field).lower() not in JSONLD_TYPES_OK:
                            continue
                        tel = cand.get("telephone") or cand.get("contactPoint", {}).get("telephone")
                        if isinstance(tel, list) and tel:
                            tel = tel[0]
                        if tel:
                            v = _validate_phone(tel, phonenumbers)
                            if v:
                                return v
        except Exception:
            continue
    return ""


# ── Tier 6: YellowPages ───────────────────────────────────────────────────────

def _yellowpages_lookup(client, name: str, city: str, BeautifulSoup,
                        phonenumbers, fuzz, fuzz_threshold: int) -> str:
    """Search YellowPages for `<name>` in `<city>, FL`. Return validated phone if a
    listing's name fuzz-matches AND the listing's address contains the city."""
    url = (f"https://www.yellowpages.com/search"
           f"?search_terms={quote_plus(name[:80])}&geo_location_terms={quote_plus(city + ', FL')}")
    try:
        r = client.get(url, timeout=client.timeout.read or 10.0)
    except Exception:
        return ""
    if r.status_code != 200:
        return ""
    if "captcha" in r.text.lower()[:5000]:
        return ""
    try:
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return ""
    # YP listings: <div class="result"> ... contains <a class="business-name"> + <div class="phones">
    for result in soup.find_all("div", class_="result"):
        nm_tag = result.find(class_="business-name")
        ph_tag = result.find(class_="phones") or result.find(class_="phone")
        addr_tag = result.find(class_="adr") or result.find(class_="street-address")
        if not nm_tag or not ph_tag:
            continue
        listing_name = nm_tag.get_text(strip=True)
        listing_phone = ph_tag.get_text(strip=True)
        listing_addr = addr_tag.get_text(" ", strip=True) if addr_tag else ""
        # Strict accept rules
        if fuzz.token_set_ratio(name.lower(), listing_name.lower()) < fuzz_threshold:
            continue
        # City match (case-insensitive substring)
        if city.lower() not in (listing_addr + " " + listing_name).lower():
            # Try a looser match: city in any element text in the result
            full_text = result.get_text(" ", strip=True).lower()
            if city.lower() not in full_text:
                continue
        v = _validate_phone(listing_phone, phonenumbers)
        if v:
            return v
    return ""


# ── Tier 7: DuckDuckGo HTML (strict) ──────────────────────────────────────────

def _ddg_lookup(client, name: str, city: str, BeautifulSoup, phonenumbers,
                fuzz, fuzz_threshold: int) -> str:
    """Strict DDG HTML search: phone must appear in result whose snippet contains
    BOTH the business name (fuzz≥threshold) AND the city (case-insensitive)."""
    query = f'"{name}" {city} FL phone'
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        r = client.get(url, timeout=client.timeout.read or 10.0)
    except Exception:
        return ""
    if r.status_code != 200:
        return ""
    try:
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return ""
    name_lower = name.lower()
    city_lower = city.lower()
    for result in soup.find_all("div", class_="result"):
        # Skip ads
        if "ad" in (result.get("class") or []) or result.find(class_="badge--ad"):
            continue
        title_tag = result.find("a", class_="result__a")
        snippet_tag = result.find("a", class_="result__snippet") or result.find(class_="result__snippet")
        if not title_tag and not snippet_tag:
            continue
        title_text = title_tag.get_text(" ", strip=True).lower() if title_tag else ""
        snippet_text = snippet_tag.get_text(" ", strip=True).lower() if snippet_tag else ""
        full_text = f"{title_text} {snippet_text}"
        # Strict gate 1: city must appear
        if city_lower not in full_text:
            continue
        # Strict gate 2: business name fuzz match against title or snippet
        if (fuzz.token_set_ratio(name_lower, title_text) < fuzz_threshold
                and fuzz.token_set_ratio(name_lower, snippet_text) < fuzz_threshold):
            continue
        # Extract phone numbers from snippet
        for m in PHONE_RE.finditer(snippet_text):
            cand_phone = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
            v = _validate_phone(cand_phone, phonenumbers)
            if v:
                return v
        # Also check title text
        for m in PHONE_RE.finditer(title_text):
            cand_phone = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
            v = _validate_phone(cand_phone, phonenumbers)
            if v:
                return v
    return ""


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
