#!/usr/bin/env python3
"""
Facebook page finder for the dashboard's organizations / events.

Many county clubs publish their real meeting schedule on Facebook rather than
a website. This tool searches the open web for the most likely Facebook *page*
for each organization and reports a best-match URL with a confidence score.

It does NOT fetch facebook.com directly — that hits the login wall and returns
nothing useful (see project memory: "Facebook fetch constraint"). Instead it
reads facebook.com/<handle> links out of a normal search-engine results page,
which are visible without logging in, then ranks them by name similarity.

Search backend (in priority order):
    1. Brave Search API  — set BRAVE_API_KEY (free 2,000 queries/mo at
       https://brave.com/search/api/). Reliable JSON; recommended for batches.
    2. DuckDuckGo scrape — keyless fallback. Works, but DDG rate-limits hard;
       use a generous --sleep (>=4s) and expect throttling on big runs.

Default scope is THIS WEEK's events (next 7 days from today), matching the
"what's on this week" question. Use --all for the whole dataset, or --days N
to widen the window.

Workflow:
    export FL_AG_PIN=040476
    python scripts/decrypt.py                 # produce data/records.json
    python scripts/find_facebook_pages.py      # search this week's orgs
    python scripts/find_facebook_pages.py --out fb_pages.csv

Stdlib only — no extra dependencies beyond what decrypt.py already needs.

Flags:
    --records PATH   records JSON (default: data/records.json)
    --days N         look-ahead window in days (default: 7)
    --today YYYY-MM-DD   override "today" (default: real today)
    --all            ignore the date window; search every record
    --limit N        only process the first N unique orgs (testing)
    --sleep SECS     delay between searches, be polite (default: 2.0)
    --out PATH       write CSV here (default: print a table to stdout)
    --min-score N    confidence cutoff 0-100 to call a match (default: 60)
"""
import argparse
import csv
import sys
from pathlib import Path

# Heavy-ish imports stay inside main() so --help works anywhere.

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RECORDS = SCRIPT_DIR.parent / "data" / "records.json"

# DuckDuckGo endpoints that return plain, login-free result links. We try the
# HTML one first, then the lighter "lite" one if HTML serves an anti-bot page.
SEARCH_URL = "https://html.duckduckgo.com/html/"
SEARCH_URL_LITE = "https://lite.duckduckgo.com/lite/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# facebook.com paths that are never an org page.
FB_BLOCKLIST = {
    "sharer", "sharer.php", "login", "login.php", "tr", "plugins", "dialog",
    "help", "policies", "policy.php", "terms", "privacy", "settings",
    "watch", "marketplace", "gaming", "events", "groups", "hashtag",
    "people", "profile.php", "pages", "public", "story.php", "permalink.php",
    "photo.php", "media", "reel", "business", "ads", "legal", "about",
}


def parse_date(s):
    """Parse the dataset's 'Month D, YYYY' format. Returns date or None."""
    from datetime import datetime
    if not s or not s.strip() or s.strip().lower() == "tbd":
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def in_window(rec, today, end):
    d = parse_date(rec.get("Meeting_or_Event_Date", ""))
    return d is not None and today <= d <= end


def normalize(text):
    """Lowercase, drop punctuation, collapse whitespace -> token set helper."""
    import re
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


# Tokens that add no identifying signal when matching a club to a FB handle.
STOPWORDS = {
    "the", "of", "and", "county", "club", "republican", "republicans",
    "committee", "executive", "rec", "florida", "fl", "inc", "association",
    "federated", "women", "womens", "mens", "men", "group", "area", "greater",
}


def tokens(text):
    return [t for t in normalize(text).split() if t and t not in STOPWORDS]


def similarity(org_name, candidate_text):
    """0-100 score: token overlap + sequence ratio against the FB link text."""
    from difflib import SequenceMatcher

    org_tokens = set(tokens(org_name))
    cand_norm = normalize(candidate_text)
    cand_tokens = set(t for t in cand_norm.split() if t)
    if not org_tokens:
        return 0
    overlap = len(org_tokens & cand_tokens) / len(org_tokens)
    seq = SequenceMatcher(None, normalize(org_name), cand_norm).ratio()
    return round(100 * (0.7 * overlap + 0.3 * seq))


def decode_ddg_href(href):
    """DuckDuckGo wraps targets as //duckduckgo.com/l/?uddg=<encoded>. Unwrap."""
    from urllib.parse import urlparse, parse_qs, unquote
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return href


def fb_handle(url):
    """Return the identifying handle of a facebook.com URL, or None.

    Accepts org pages (facebook.com/Name -> 'Name'), GROUPS
    (facebook.com/groups/<id> -> 'groups/<id>'), and /p/ pages
    (facebook.com/p/Name-123 -> 'Name-123'). Groups are what we want most.
    """
    from urllib.parse import urlparse
    p = urlparse(url)
    if "facebook.com" not in p.netloc:
        return None
    seg = [s for s in p.path.split("/") if s]
    if not seg:
        return None
    head = seg[0].lower()
    if head == "groups":
        return "groups/" + seg[1] if len(seg) > 1 else None
    if head == "p" and len(seg) > 1:
        return seg[1]
    if head in FB_BLOCKLIST:
        return None
    return seg[0]


def _is_challenge(body):
    """DuckDuckGo serves an anti-bot page when rate-limited: no anchors at all."""
    low = body.lower()
    if "result__a" in body or "result-link" in body:
        return False
    return ("anomaly" in low or "captcha" in low or "challenge" in low
            or "<a " not in low)


def _fetch(url, query, timeout):
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    data = urlencode({"q": query}).encode()
    req = Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _extract_fb(body):
    """Pull facebook candidates out of any DDG results page.

    Returns (fb_url, anchor_text) pairs. Works on both the html and lite
    endpoints by scanning every <a href> and keeping facebook.com targets.
    """
    import re
    from html import unescape
    out = []
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.DOTALL):
        url = decode_ddg_href(unescape(href))
        if fb_handle(url):
            clean_text = unescape(re.sub(r"<[^>]+>", "", text)).strip()
            out.append((url, clean_text))
    return out


def search_brave(query, api_key, sleep_after, timeout=20):
    """Brave Search API backend. Returns (candidates, error)."""
    import time
    import json as _json
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    url = "https://api.search.brave.com/res/v1/web/search?" + urlencode(
        {"q": query, "count": 10})
    req = Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
        "User-Agent": USER_AGENT,
    })
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = _json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        time.sleep(sleep_after)
        return [], f"brave error: {e}"
    out = []
    for item in payload.get("web", {}).get("results", []):
        u = item.get("url", "")
        if fb_handle(u):
            out.append((u, item.get("title", "")))
    time.sleep(sleep_after)
    return out, None


def search_facebook(query, sleep_after, timeout=20, retries=3, brave_key=None):
    """Run one search. Prefers Brave API, falls back to DDG scrape with backoff.

    Returns (candidates, error). candidates is a list of (fb_url, text).
    """
    import time
    if brave_key:
        return search_brave(query, brave_key, sleep_after, timeout)
    last_err = None
    for attempt in range(retries):
        # Alternate endpoints: html first, then lite, then html again...
        url = SEARCH_URL if attempt % 2 == 0 else SEARCH_URL_LITE
        try:
            body = _fetch(url, query, timeout)
        except Exception as e:  # network blocked, timeout, etc.
            last_err = f"search error: {e}"
            time.sleep(sleep_after * (attempt + 1))
            continue

        if _is_challenge(body):
            last_err = "rate-limited (anti-bot page)"
            # Back off harder before retrying on the other endpoint.
            time.sleep(sleep_after * (attempt + 2))
            continue

        cands = _extract_fb(body)
        time.sleep(sleep_after)
        return cands, None

    time.sleep(sleep_after)
    return [], last_err


def best_match(org_name, candidates):
    """Pick the best facebook candidate, preferring GROUPS. Returns (url, handle, score)."""
    best = (None, None, 0)
    best_eff = -1
    for url, text in candidates:
        handle = fb_handle(url)
        if not handle:
            continue
        # Score against the visible link text and the handle (sans 'groups/' prefix).
        base = handle.split("groups/")[-1]
        score = max(similarity(org_name, text), similarity(org_name, base))
        # Groups are the goal — give them an edge so a group beats a page on a tie.
        eff = score + (10 if handle.startswith("groups/") else 0)
        if eff > best_eff:
            best_eff = eff
            best = (url, handle, score)
    return best


def select_records(records, args):
    """Dedupe by org name; apply date window unless --all."""
    from datetime import date, timedelta, datetime

    if args.all:
        chosen = records
    else:
        if args.today:
            today = datetime.strptime(args.today, "%Y-%m-%d").date()
        else:
            today = date.today()
        end = today + timedelta(days=args.days)
        chosen = [r for r in records if in_window(r, today, end)]

    seen, unique = set(), []
    for r in chosen:
        name = (r.get("Organization_or_Event_Name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        unique.append(r)
    if args.limit:
        unique = unique[: args.limit]
    return unique


def existing_fb(rec):
    """If the record already carries a facebook.com link, surface it."""
    for field in ("Website", "Source_URL"):
        val = (rec.get(field) or "")
        if "facebook.com" in val.lower():
            return val.strip()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", default=str(DEFAULT_RECORDS))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--today", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-score", type=int, default=60)
    args = ap.parse_args()

    import json
    import os

    brave_key = os.environ.get("BRAVE_API_KEY")
    backend = "Brave API" if brave_key else "DuckDuckGo scrape (keyless)"
    sys.stderr.write(f"Search backend: {backend}\n")

    rpath = Path(args.records)
    if not rpath.exists():
        sys.stderr.write(
            f"ERROR: {rpath} not found. Run `python scripts/decrypt.py` first.\n"
        )
        return 1
    records = json.loads(rpath.read_text())

    orgs = select_records(records, args)
    sys.stderr.write(f"Searching Facebook pages for {len(orgs)} unique org(s)...\n")

    rows = []
    for i, r in enumerate(orgs, 1):
        name = r["Organization_or_Event_Name"].strip()
        city = (r.get("City") or "").strip()
        county = (r.get("County") or "").strip()

        known = existing_fb(r)
        if known:
            sys.stderr.write(f"[{i}/{len(orgs)}] {name} -> already in data\n")
            rows.append({
                "Organization": name, "City": city, "County": county,
                "Facebook_URL": known, "Handle": fb_handle(known) or "",
                "Score": 100, "Status": "in-data",
            })
            continue

        query = f'{name} {city} Florida facebook group'
        candidates, err = search_facebook(query, args.sleep, brave_key=brave_key)
        if err:
            sys.stderr.write(f"[{i}/{len(orgs)}] {name} -> {err}\n")
            rows.append({
                "Organization": name, "City": city, "County": county,
                "Facebook_URL": "", "Handle": "", "Score": 0, "Status": err,
            })
            continue

        url, handle, score = best_match(name, candidates)
        status = "match" if score >= args.min_score else (
            "low-confidence" if url else "no-result"
        )
        sys.stderr.write(
            f"[{i}/{len(orgs)}] {name} -> {handle or '(none)'} ({score})\n"
        )
        rows.append({
            "Organization": name, "City": city, "County": county,
            "Facebook_URL": url or "", "Handle": handle or "",
            "Score": score, "Status": status,
        })

    fields = ["Organization", "City", "County", "Facebook_URL", "Handle", "Score", "Status"]
    if args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        sys.stderr.write(f"\nWrote {len(rows)} rows -> {args.out}\n")
    else:
        # Plain table to stdout.
        print(f"\n{'ORG':<48} {'SCORE':>5}  FACEBOOK")
        print("-" * 100)
        for row in rows:
            print(f"{row['Organization'][:47]:<48} {row['Score']:>5}  "
                  f"{row['Facebook_URL'] or row['Status']}")

    matched = sum(1 for r in rows if r["Status"] in ("match", "in-data"))
    sys.stderr.write(
        f"\nDone. {matched}/{len(rows)} with a confident page "
        f"(score >= {args.min_score}).\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
