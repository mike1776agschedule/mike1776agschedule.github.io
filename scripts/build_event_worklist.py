#!/usr/bin/env python3
"""
Regenerate the week's validation docs straight from data/records.json, so they
always reflect the live confidence markers in each record's Notes field:

  ✅ VERIFIED:  -> Confirmed   (green)
  ⚠️ VERIFY:    -> Open        (amber, needs a human look)
  ❌ INCORRECT: -> Not-this-date (red, confirmed wrong)
  (none)        -> Pending     (grey, not reviewed yet)

Writes:
  docs/SCHEDULE.md  — every event in the window with status, time, location, finding
  docs/FACEBOOK.md  — the human Facebook checklist (links to confirm dates on FB)

Usage:  python scripts/build_event_worklist.py
"""
import json
from datetime import datetime, date

WINDOW = (date(2026, 6, 11), date(2026, 6, 17))

def parse(s):
    for f in ("%B %d, %Y", "%b %d, %Y"):
        try: return datetime.strptime(s.strip(), f).date()
        except ValueError: continue
    return None

def status(notes):
    n = str(notes or "")
    if n.startswith("❌ INCORRECT:"): return ("bad", "❌", "Not this date")
    if n.startswith("⚠️ VERIFY:"):    return ("open", "⚠️", "Open")
    if n.startswith("✅ VERIFIED:"):   return ("high", "✅", "Confirmed")
    return ("pending", "🟡", "Pending")

def reason(notes):
    n = str(notes or "")
    for p in ("❌ INCORRECT: ", "⚠️ VERIFY: ", "✅ VERIFIED: "):
        if n.startswith(p): return n[len(p):].split(" | ")[0]
    return ""

def cell(s): return (str(s or "")).replace("|", "/").replace("\n", " ").strip()
def fbtype(u): return "group" if "/groups/" in u else "page"
SORT = {"bad": 0, "open": 1, "pending": 2, "high": 3}

def main():
    d = json.load(open("data/records.json"))
    lo, hi = WINDOW
    evs = []
    for r in d:
        dt = parse(r.get("Meeting_or_Event_Date", "") or "")
        if dt and lo <= dt <= hi:
            evs.append((dt, r))
    days = sorted({dt for dt, _ in evs})

    counts = {"high": 0, "open": 0, "bad": 0, "pending": 0}
    for _, r in evs:
        counts[status(r.get("Notes"))[0]] += 1
    total = len(evs)

    # ---------------- SCHEDULE.md ----------------
    S = [f"# SCHEDULE — event validation, {lo.strftime('%b %-d')}–{hi.strftime('%b %-d, %Y')}", "",
         "> Auto-generated from the dataset by `scripts/build_event_worklist.py`. "
         "Status comes from each record's confidence marker.", "",
         f"**{total} events** · ✅ **{counts['high']}** confirmed · ⚠️ **{counts['open']}** open · "
         f"❌ **{counts['bad']}** not-this-date · 🟡 **{counts['pending']}** pending", "",
         "Status: ✅ confirmed (real source) · ⚠️ open (needs a human/Facebook look) · "
         "❌ confirmed NOT on this date · 🟡 not reviewed yet.", ""]
    for day in days:
        rows = [r for dt, r in evs if dt == day]
        rows.sort(key=lambda r: (SORT[status(r.get("Notes"))[0]], r["Organization_or_Event_Name"].lower()))
        c = {"high": 0, "open": 0, "bad": 0, "pending": 0}
        for r in rows: c[status(r.get("Notes"))[0]] += 1
        S.append(f"## {day.strftime('%A, %B %-d')} — {len(rows)} events "
                 f"· ✅ {c['high']} · ⚠️ {c['open']} · ❌ {c['bad']} · 🟡 {c['pending']}")
        S.append("")
        S.append("| | Event | County | Time | Location | Finding |")
        S.append("|---|---|---|---|---|---|")
        for r in rows:
            _, emoji, _ = status(r.get("Notes"))
            loc = ", ".join(p for p in (r.get("Venue", "").strip(), r.get("City", "").strip()) if p) or "—"
            S.append(f"| {emoji} | {cell(r['Organization_or_Event_Name'])} | {cell(r.get('County'))} | "
                     f"{cell(r.get('Meeting_or_Event_Time') or 'TBD')} | {cell(loc)[:48]} | {cell(reason(r.get('Notes'))) or '—'} |")
        S.append("")
    open("docs/SCHEDULE.md", "w").write("\n".join(S) + "\n")

    # ---------------- FACEBOOK.md ----------------
    F = [f"# FACEBOOK — page/group verification checklist ({lo.strftime('%b %-d')}–{hi.strftime('%b %-d, %Y')})", "",
         "Open each link, confirm the club's **next meeting date & location** on Facebook, tick the box. "
         "If FB shows a different date than ours, tell me and I'll correct the data.", "",
         "- I can't load Facebook directly (it blocks automated requests) — every link below was a current Brave "
         "search result, so it's live/indexed, but *you* are the final check.",
         "- **page** = org/club page · **group** = FB group · **—** = no org-specific FB found (manual search).",
         "- Status: ✅ confirmed · ⚠️ open · ❌ not-this-date · 🟡 pending.", ""]
    withfb = sum(1 for _, r in evs if r.get("Facebook_URL", "").strip())
    F.append(f"**{withfb} of {total} events have a Facebook link to check; {total-withfb} need a manual search.**")
    F.append("")
    for day in days:
        rows = [r for dt, r in evs if dt == day]
        rows.sort(key=lambda r: (SORT[status(r.get("Notes"))[0]], r["Organization_or_Event_Name"].lower()))
        F.append(f"## {day.strftime('%A, %B %-d')}")
        F.append("")
        F.append("| | Event | County | Time | Facebook | Type | Confirmed? |")
        F.append("|---|---|---|---|---|---|---|")
        for r in rows:
            _, emoji, _ = status(r.get("Notes"))
            fb = r.get("Facebook_URL", "").strip()
            link = f"[open]({fb})" if fb else "— *manual*"
            F.append(f"| {emoji} | {cell(r['Organization_or_Event_Name'])} | {cell(r.get('County'))} | "
                     f"{cell(r.get('Meeting_or_Event_Time') or 'TBD')} | {link} | {fbtype(fb) if fb else '—'} | ☐ |")
        F.append("")
    open("docs/FACEBOOK.md", "w").write("\n".join(F) + "\n")

    print(f"SCHEDULE.md + FACEBOOK.md: {total} events "
          f"(✅{counts['high']} ⚠️{counts['open']} ❌{counts['bad']} 🟡{counts['pending']}), {withfb} with FB")

if __name__ == "__main__":
    main()
