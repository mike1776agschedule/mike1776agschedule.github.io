#!/usr/bin/env python3
"""
Roll past-dated monthly recurring events forward to their next occurrence
within the May–Aug 2026 window. One-time past events that cannot be rolled
are removed.

Workflow:
    export FL_AG_PIN=040476
    python scripts/decrypt.py            # data/records.json
    python scripts/roll_forward.py       # rewrites data/records.json in place
    python scripts/audit.py              # sanity check (will hit the live blob)
    python scripts/encrypt.py            # writes back into HTML
    python scripts/deploy.py "msg"       # commit + push to GitHub Pages

Pass --dry-run to preview without writing.
"""
import json, re, sys
from datetime import date, datetime
from calendar import monthrange
from pathlib import Path
from _common import REPO_ROOT

TODAY = date.today()
WINDOW_END = date(2026, 8, 31)

ORD = {"1st":1,"first":1,"2nd":2,"second":2,"3rd":3,"third":3,"4th":4,"fourth":4,"5th":5,"last":-1}
DAYS = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
          "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}


def parse_date(s):
    if not s or s.strip().lower() == "tbd": return None
    try: return datetime.strptime(s.strip(), "%B %d, %Y").date()
    except: return None


def nth_weekday(year, month, ordinal, weekday):
    if ordinal == -1:
        last = monthrange(year, month)[1]
        for d in range(last, last-7, -1):
            if date(year, month, d).weekday() == weekday:
                return date(year, month, d)
        return None
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (ordinal - 1) * 7
    if day > monthrange(year, month)[1]: return None
    return date(year, month, day)


def parse_patterns(rec):
    rec = rec.lower()
    patterns = []
    for m in re.finditer(r"(1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last)\s+(?:and\s+(1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?", rec):
        o1, o2, day = m.group(1), m.group(2), m.group(3)
        patterns.append((ORD[o1], DAYS[day]))
        if o2: patterns.append((ORD[o2], DAYS[day]))
    return patterns


def excluded_months(rec):
    rec = rec.lower(); excl = set()
    if "september" in rec and "may" in rec and any(k in rec for k in ["-", "through", "to "]):
        for m in [6,7,8]: excl.add(m)
    for kw in ["no ", "except ", "dark in ", "dark "]:
        for name, num in MONTHS.items():
            if f"{kw}{name}" in rec: excl.add(num)
    return excl


def main():
    dry = "--dry-run" in sys.argv
    in_path = REPO_ROOT / "data" / "records.json"
    if not in_path.exists():
        sys.exit(f"ERROR: {in_path} not found. Run scripts/decrypt.py first.")

    records = json.loads(in_path.read_text())
    rolled, removed_idx, cleared = 0, [], 0

    for i, r in enumerate(records):
        d = parse_date(r.get("Meeting_or_Event_Date", ""))
        rec = r.get("Recurrence", "").strip().lower()
        if not d: continue

        # Past date
        if d < TODAY:
            if "monthly" in rec or "month" in rec:
                patterns = parse_patterns(rec)
                excl = excluded_months(rec)
                if patterns:
                    found = None
                    for off in range(5):  # try next 5 months
                        y, m = TODAY.year, TODAY.month + off
                        while m > 12: y += 1; m -= 12
                        if m in excl or m < 5 or m > 8: continue
                        cands = [nth_weekday(y, m, o, dow) for o, dow in patterns
                                 if nth_weekday(y, m, o, dow) and nth_weekday(y, m, o, dow) >= TODAY]
                        if cands: found = min(cands); break
                    if found:
                        r["Meeting_or_Event_Date"] = found.strftime("%B %d, %Y").replace(" 0", " ")
                        rolled += 1
                        continue
                # No parseable pattern or no candidate in window
                r["Meeting_or_Event_Date"] = ""; cleared += 1
            else:
                removed_idx.append(i)
        # Outside window forward
        elif d > WINDOW_END:
            if "monthly" in rec or "annual" in rec:
                r["Meeting_or_Event_Date"] = ""; cleared += 1
            else:
                removed_idx.append(i)

    kept = [r for i, r in enumerate(records) if i not in set(removed_idx)]

    print(f"rolled forward:     {rolled}")
    print(f"cleared (TBD):      {cleared}")
    print(f"removed (one-time): {len(removed_idx)}")
    print(f"records: {len(records)} -> {len(kept)}")

    if dry:
        print("\n(dry run — no files modified)")
        return

    in_path.write_text(json.dumps(kept, indent=2))
    print(f"\nwrote {in_path.relative_to(REPO_ROOT)}")
    print("next:  python scripts/encrypt.py && python scripts/deploy.py 'roll forward past dates'")


if __name__ == "__main__":
    main()
