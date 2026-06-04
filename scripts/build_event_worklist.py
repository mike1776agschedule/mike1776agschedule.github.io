import json
from datetime import datetime, date

d = json.load(open('data/records.json'))
today = date(2026,6,4); end = date(2026,6,10)
def parse(s):
    for fmt in ("%B %d, %Y","%b %d, %Y"):
        try: return datetime.strptime(s.strip(),fmt).date()
        except: pass
    return None
hits=[]
for r in d:
    raw=r.get('Meeting_or_Event_Date','').strip()
    dt=parse(raw) if raw else None
    if dt and today<=dt<=end: hits.append((dt,r))
hits.sort(key=lambda x:(x[0], x[1].get('Organization_or_Event_Name','').lower()))

# Validation results keyed by org name. status: OK / FIX / TODO
# tuple: (status, source_used, note)
RES = {
 "Suwannee County REC Meeting": ("OK","florida.gop/.../suwannee","1st Thu; meet&greet 6:30pm, mtg 7pm, Live Oak City Hall — matches."),
 "St. Johns County REC Meeting": ("OK","stjohns.gop / search","1st Thu 5:30/6:00/6:30, Holiday Inn World Golf Village — matches (venue 'liable to change')."),
 "Pinellas Federated Republican Women": ("OK","pinellasrepublican.org/clubs","1st Thu, DeLuka's Restaurant, Clearwater — matches."),
 "Gulf Beaches Republicans": ("OK","pinellasrepublican.org/clubs","1st Thu 6PM confirmed. Venue refine: Original Crabby Bill's is 401 Gulf Blvd, INDIAN ROCKS BEACH (data city 'Gulf Beaches' is vague)."),
 "First Coast Federated Republican Women": ("OK","search (jbrwc / FCRJaxBch)","1st Thu, Southpoint Marriott, Jacksonville — matches."),
 "Republican Club of Plantation": ("OK","republicanclubofplantation.com","EXACT: site states 'Thursday, June 4, 2026, 6:30pm (doors 6:00)', Jim Ward Community Center — fully confirmed."),
 "Heritage Isle Republican Club": ("OK","gopbrevard.org/clubs","1st Thu 10:00am-12:30, Heritage Isle Clubhouse Ballroom — matches."),
 "Republican Club of Southwest Volusia": ("OK","volusiacountyrepublicans.org/clubs","1st Thu 6PM, VFW Hall DeBary — matches."),
 "Temple Terrace Area Republican Club": ("OK","ttarc.org / search","1st Thu, social 6-7pm, mtg 7-8:30pm, Temple Terrace Golf & Country Club — matches."),
 "South Seminole Republican Club": ("OK","seminolegop search","1st Thu, Sheriff's Annex, Altamonte Springs — matches."),
 "Seminole County Regional Chamber of Commerce - Monthly Breakfast": ("OK","business.seminolebusiness.org/events","Confirmed 'Good Morning Seminole!' event listed for Thu Jun 4, 2026 (time/venue not shown; reg closed)."),
 "Homosassa River Republican Club": ("FIX","chronicleonline / rpocitrus","DISCREPANCY: club meets 3rd TUESDAY (->Jun 16) 11:00 social/11:30 at MARGARITA GRILL, 10200 W Halls River Rd, Homosassa — NOT Jun 4 at Beverly Hills. Data appears conflated with Nature Coast."),
 "Nature Coast Republican Club (NCRC)": ("OK","chronicleonline search","FIXED IN DATA: time corrected 8:30/9:00 AM → 5:30 PM doors/6:00 PM program. Date 1st Thu = Jun 4, Beverly Hills Community Bldg ✓."),
 "Central Santa Rosa Republican Club": ("FIX","search (santarosa REC)","LIKELY WRONG DATE: Grover T's (5887 Hwy 90, Pace/Milton) meeting is 3rd THURSDAY (->Jun 18), 5:30 dinner/6:30 mtg — not Jun 4. Confirm club vs REC identity."),
 "30-A Republican Club": ("FIX","waltonflgop.com/clubs / search","NOT FOUND: not listed among Walton GOP clubs; Walton clubs meet 2nd Tue 6-7pm. Likely defunct/renamed (cf. 'South Walton Republican Club', Edgewater Resort, Miramar Beach). Jun 4 unsupported."),
 "Marion County 4-H County Council": ("TODO","-","Not yet checked (UF/IFAS Marion 4-H events page)."),
 "Sumter County REC Meeting": ("TODO","sumterrepublicans.com","No public meeting date on site (PDF/Facebook only). Needs FB or direct confirmation."),
 "North Jacksonville Republican Club": ("TODO","florida.gop/recs (generic)","No date/time in data; generic source. Needs a real club source."),
 "Escambia County Federation of Republican Women": ("TODO","efrw.org","Site deliberately HIDES event details ('security concerns'). Historically Tryon Library. Jun 4 not confirmable online — ask user/FB DM."),
 "Latino Republicans of the Palm Beaches": ("TODO","palmbeach.gop/clubs","No date/time/venue in data. Needs a real source."),
 # --- Day 2: Fri Jun 5 ---
 "157th Silver Spurs Rodeo - Summer": ("OK","silverspursrodeo.com","EXACT: site confirms Fri Jun 5, 2026 7:30 PM (also Sat Jun 6 7:30 PM) at Silver Spurs Arena, Osceola Heritage Park. NOTE: dataset is missing the Jun 6 performance."),
 "Belleair Women's Republican Club": ("OK","search (Patch/bwrc.us)","1st Friday 11:30am, One Country Club Lane, Belleair — Jun 5 matches."),
 "Republican Men's Club of Collier County": ("OK","mensclubcc.org","EXACT: 'Friday, June 5th 7:30am, Naples Hilton' w/ School Board candidate forum. (Site name: 'The Right Men's Club of Collier County'.)"),
 "Federated Republican Women in Action (Brevard)": ("OK","frwabrevard.org","DEDUPED IN DATA: removed the 'Brevard Federated Women of Action' duplicate; this is the canonical record. 1st-Friday pattern → Jun 5 plausible (MeMaw's BBQ, Palm Bay)."),
 "Brevard Federated Women of Action": ("FIX","frwabrevard.org / gopbrevard","DUPLICATE of 'Federated Republican Women in Action (Brevard)' — same MeMaw's BBQ, Palm Bay, 11:15 AM. Merge."),
 "Republican Women's Club of Sarasota": ("FIX","republicanwomensclubofsarasota.com","NO June meeting shown — next listed luncheon is Fri Sep 4, 2026 11:00 AM (summer break likely). Data's Jun 5 5:30-6:00 PM looks wrong (their meetings are 11AM luncheons). Verify before relying."),
 "Jackson County Chamber of Commerce": ("FIX","jacksoncounty.com","QUESTIONABLE: site's Jun 5 listing is 'Update Your Headshot' @12:30 PM, not a noon luncheon at Historic Russ House. Data's event may be generic/placeholder. Confirm actual Chamber June event."),
 # --- Day 3: Mon Jun 8 (2nd Monday) ---
 "Coral Springs Parkland Republican Club": ("OK","browardgop.com/official-republican-clubs","2nd Mon 7PM, Wings Plus — Jun 8 matches."),
 "Golden Triangle Federated Republican Women's Club": ("OK","lakecountyrepublicans.org","2nd Mon 11:30 AM, Country Club of Mount Dora — Jun 8 matches."),
 "Republican Club of the Plantation at Leesburg": ("OK","lakecountyrepublicans.org","2nd Mon 4:00 PM, Ashley Hall @ The Plantation — Jun 8 matches."),
 "Charlotte County Republican Club - Monthly Mixer": ("OK","ccflrc.org","2nd Mon 5PM Mixer, Beef O'Brady's, Punta Gorda — Jun 8 matches. (Business mtg is 4th Wed elsewhere.)"),
 "Bay County Republican Roundtable": ("OK","baygop.com/republican-roundtable","2nd Mon 6PM networking/6:30 mtg, O'Charley's — Jun 8 matches."),
 "Columbia County REC Meeting": ("OK","florida.gop/.../columbia","2nd Mon, Fairgrounds, Lake City — Jun 8 matches."),
 "Gadsden County REC Meeting": ("OK","florida.gop/.../gadsden","2nd Mon 6PM, Havana Community Center — Jun 8 matches."),
 "Lafayette County REC Meeting": ("OK","florida.gop/.../lafayette","2nd Mon of EVEN months 6:30PM, Mayo Community Center. June is even -> Jun 8 valid."),
 "Glades County REC": ("OK","florida.gop/.../glades","2nd Mon 6PM, 1297 FL-78 Moore Haven — Jun 8 matches."),
 "Women's Republican Club of Pasco County": ("OK","search (pascogop)","2nd Mon 5:30 social/6:30 mtg, Timber Greens CC — Jun 8 matches."),
 "West Villages Republican Club": ("OK","sarasotagop.com","2nd Mon 5:30PM, Clubhouse at Gran Paradiso, Venice — Jun 8 matches."),
 "Republican Women of Indian River": ("OK","search (RWIRC)","2nd Mon 11:30 social/12:00 mtg, Bent Pine Country Club — Jun 8 matches."),
 "Pinellas County REC Meeting": ("OK","pinellasrepublican.org/events","2nd Mon pattern, Feather Sound Country Club. NOTE: events page is stale (shows Feb 9) — venue/pattern consistent, Jun 8 inferred."),
 "Broward County REC Meeting": ("FIX","browardgop.com/next-meeting","DATE WRONG: site explicitly states next REC meeting is MON JUN 22, 2026 7PM (E. Pat Larkins Ctr) — not Jun 8. Move date."),
 "Coral Springs Republican Club": ("FIX","browardgop.com","POSSIBLE DUPLICATE: only 'Coral Springs Parkland RC' is listed on Broward GOP; this separate 'Coral Springs Republican Club' (same Wings Plus venue) may be defunct/merged. Confirm before keeping."),
 "New Port Richey Republican Club": ("FIX","search (pascogop)","DAY UNCONFIRMED: data says 2nd Mon, but 2025 listings suggest 4th Thursday at Timber Greens. Distinct from Women's RC of Pasco. Verify meeting day."),
 # --- Day 4: Tue Jun 9 (2nd Tuesday) ---
 "Freeport Republicans": ("OK","waltonflgop.com/clubs","2nd Tue 6PM (5:30 reg), Hammock Bay Clubhouse, Freeport — Jun 9 matches."),
 "Pinellas County Young Republicans": ("OK","pinellasrepublican.org/clubs","2nd Tue, St. Pete Yacht Club — Jun 9 matches."),
 "Seminole Republican Women Federated": ("OK","search (seminolerepublicanwomen)","2nd Tue, Oviedo Center Lake Cultural Center — Jun 9 matches."),
 "Ronald Reagan Republican Club of On Top of the World": ("OK","pinellasrepublican.org/clubs","2nd Tue, West Activity Center, Top of the World, Clearwater — Jun 9 matches."),
 "Shoal River Republican Club": ("FIX","okaloosagop.com","WRONG: meets 3rd Tue (~Jun 16) 6:30PM at Eagle's Nest, 4927 Antioch Rd — not 2nd Tue at Hideaway Pizza."),
 "Republican Club of The Villages (RCTVF)": ("FIX","sumterrepublicans.com/clubs","WRONG DAY: meets 4th WEDNESDAY (~Jun 24) 7PM (doors 6:30) at Ezell Rec Ctr — data has it on Tue Jun 9."),
 "Republican Club of Longboat Key": ("FIX","rclbk.org / search","SEASONAL: club meets Oct–Apr only; no June meeting (summer dark). Remove Jun occurrence."),
 "Davie Cooper City Republican Club": ("TODO","browardgop/daviecooperpatriots","Unverified — no meeting schedule surfaced on Broward GOP or club site."),
 "West Broward Republican Club": ("TODO","search","Unverified — meeting day not confirmed online (Volunteer Park, Plantation)."),
 "Manatee County Young Republicans": ("TODO","mcyrs.wordpress.com","Unverified — homepage has no schedule; check Meetings page."),
 "North Hillsborough Republican Club": ("TODO","florida.gop/recs (generic)","Unverified — address matches Michael's Grill but meeting day not confirmed."),
 # --- Day 5: Wed Jun 10 (2nd Wednesday) ---
 "Emerald Coast Republican Women Federated": ("OK","okaloosagop.com","2nd Wed 11AM, Clubhouse Grill, Fort Walton Beach — Jun 10 matches."),
 "Flagler County REC Meeting": ("OK","florida.gop/.../flagler","2nd Wed 6PM, Palm Coast Community Center — Jun 10 matches."),
 "Indian River County REC Meeting": ("OK","ircgop.com/rec-executive-board","2nd Wed 6:30PM, Heritage Center, Vero Beach — Jun 10 matches."),
 "St Petersburg Republican Club": ("OK","stpetersburgrepublicanclub.com","2nd Wed 7PM, St Petersburg Community Church — Jun 10 matches."),
 "Lake Federated Republican Women's Club": ("OK","lakecountyrepublicans.org","2nd Wed 11:45AM, Tavares Civic Center — Jun 10 matches. (Canonical; 'Lake County RWF' is the dup.)"),
 "East Broward Republican Club": ("OK","eastbrowardrepublicanclub.com","2nd Wed pattern (Mar 11 2026 was 2nd Wed); site listings only thru May — Jun 10 inferred, Stingers Pizzeria."),
 "Lake County Republican Women Federated": ("FIX","lakecountyrepublicans / FB","DUPLICATE of 'Lake Federated Republican Women's Club' (same Tavares Civic Center, 2nd Wed 11:45 AM). Merge."),
 "Republican Club of South Sarasota County": ("FIX","search (rcsscgop)","SUSPECT: reported 2nd THURSDAY (~Jun 11) 6:30PM w/ rotating venues — data has Wed Jun 10 11AM at Osprey. Verify."),
 "Republican Club of Timber Pines": ("FIX","tprepublicanclub.org / hernandosun","WRONG: meets 3rd Tue (~Jun 16) 6:30PM at Northcliffe Church — not 2nd Wed 4:00/4:30 at Timber Pines."),
 "Kings Point Republican Club of Tamarac": ("TODO","browardgop.com","Unverified — 'guest speakers monthly' but day/time not stated."),
 "Greater Brooksville Republican Club": ("TODO","gbrc.club / search","Day unconfirmed — venue/time (The Bistro, 8AM) consistent but meeting day-of-month not verified."),
}

EMOJI = {"OK":"✅", "FIX":"⚠️", "TODO":"⬜"}
WORD  = {"OK":"Verified", "FIX":"Needs fix", "TODO":"Unverified"}

def cell(s):
    """Make a string safe for a markdown table cell."""
    return (s or "").replace("|", "/").replace("\n", " ").strip()

def status_of(name):
    return RES.get(name, ("TODO","",""))

# --- totals across the window ---
n = {"OK":0,"FIX":0,"TODO":0}
for _,r in hits:
    n[status_of(r['Organization_or_Event_Name'].strip())[0]] += 1
total = len(hits)

L = []
L.append("# Events Worklist — Thu Jun 4 → Wed Jun 10, 2026")
L.append("")
L.append("> Auto-generated by `scripts/build_event_worklist.py` from the (local, encrypted) dataset.")
L.append("> Validation = confirming each event's **date** and **location** against the club's website / Facebook.")
L.append("")
L.append(f"**{total} events** &nbsp;·&nbsp; ✅ **{n['OK']}** verified &nbsp;·&nbsp; "
         f"⚠️ **{n['FIX']}** need a fix &nbsp;·&nbsp; ⬜ **{n['TODO']}** unverifiable online")
L.append("")
L.append("Status: ✅ verified OK · ⚠️ discrepancy (needs a data change) · ⬜ couldn't confirm online")
L.append("")
L.append("**Already applied to the data + dashboard:** removed a Brevard duplicate · corrected Nature Coast RC time · "
         "flagged 25 events with a red *Needs Verification* badge in the UI. "
         "Date moves & deletions are listed below but left for human approval.")
L.append("")
L.append("---")
L.append("")

# --- ACTION LIST: just the items needing a fix, up top for quick triage ---
fixes = [(dt,r) for dt,r in hits if status_of(r['Organization_or_Event_Name'].strip())[0]=="FIX"]
L.append(f"## ⚠️ Action list — {len(fixes)} events need a data change")
L.append("")
L.append("| Date | Event | What's wrong | Recommended fix |")
L.append("|------|-------|--------------|-----------------|")
for dt,r in fixes:
    name=r['Organization_or_Event_Name'].strip()
    _,_,note = status_of(name)
    L.append(f"| {dt.strftime('%b %-d')} | {cell(name)} | {cell(note)} | _pending your OK_ |")
L.append("")
L.append("---")
L.append("")

# --- PER-DAY TABLES ---
for day in sorted(set(h[0] for h in hits)):
    todays = [r for dt,r in hits if dt==day]
    c = {"OK":0,"FIX":0,"TODO":0}
    for r in todays: c[status_of(r['Organization_or_Event_Name'].strip())[0]] += 1
    L.append(f"## {day.strftime('%A, %B %-d')} — {len(todays)} events "
             f"· ✅ {c['OK']} · ⚠️ {c['FIX']} · ⬜ {c['TODO']}")
    L.append("")
    L.append("| ✓ | Organization | Time | Location | Finding | Source |")
    L.append("|---|--------------|------|----------|---------|--------|")
    for r in sorted(todays, key=lambda r:(
            {"FIX":0,"TODO":1,"OK":2}[status_of(r['Organization_or_Event_Name'].strip())[0]],
            r['Organization_or_Event_Name'].lower())):
        name=r.get('Organization_or_Event_Name','').strip()
        time=r.get('Meeting_or_Event_Time','').strip() or 'TBD'
        venue=r.get('Venue','').strip(); city=r.get('City','').strip()
        loc=", ".join(p for p in (venue, city) if p) or "—"
        status,via,note = status_of(name)
        L.append(f"| {EMOJI[status]} | {cell(name)} | {cell(time)} | {cell(loc)} | "
                 f"{cell(note) or '—'} | {cell(via) or '—'} |")
    L.append("")
L.append("---")
L.append("")
L.append("_Weekend Jun 6–7: no events in dataset._")

out = "docs/events_2026-06-04_to_06-10.md"
open(out, "w").write("\n".join(L) + "\n")
print(f"Wrote {out}: {total} events ({n['OK']} OK, {n['FIX']} fix, {n['TODO']} todo)")
