# Project Handoff — Florida Ag Commissioner Outreach Dashboard

Everything you need to take over this project, in one document.

> **TL;DR:** Single-file HTML dashboard hosted on GitHub Pages, with all data
> AES-GCM encrypted client-side. PIN is `040476`. Every change follows the same
> shape: **decrypt → edit → encrypt → audit → deploy.**

---

## 1. What this is

A single-file HTML dashboard hosted at https://mike1776agschedule.github.io/
that tracks campaign outreach opportunities across all 67 Florida counties:
Republican infrastructure, agricultural associations, law enforcement /
firefighter unions, chambers of commerce, county fairs, and local events.

- **Live URL:** https://mike1776agschedule.github.io/
- **Access PIN:** `040476` (6 digits)
- **GitHub repo:** https://github.com/mike1776agschedule/mike1776agschedule.github.io
- **Hosting:** GitHub Pages (free, auto-deploys from `main` branch root)
- **Backend:** none. The HTML file IS the deployment.
- **Auth:** none server-side. Browser decrypts an embedded blob if the PIN is correct.

---

## 2. First-time setup (~5 minutes)

```bash
# 1. Clone
git clone https://github.com/mike1776agschedule/mike1776agschedule.github.io.git fl_ag_campaign_site
cd fl_ag_campaign_site

# 2. Install the one Python dep
pip3 install -r requirements.txt

# 3. Set the PIN in your shell
export FL_AG_PIN=040476
# (add this to your ~/.zshrc or ~/.bashrc to make it permanent)

# 4. Confirm everything works
make audit
```

If you see `All hard checks PASS` at the end, you're ready. If not, see
[Troubleshooting](#10-troubleshooting) below.

You will also need **push access** to the GitHub repo. Ask the previous
maintainer to add you as a collaborator on
`mike1776agschedule/mike1776agschedule.github.io`.

---

## 3. Repo layout

```
fl_ag_campaign_site/
├── README.md                            ← short version of this document
├── HANDOFF.md                           ← this file (everything in one place)
├── Makefile                             ← shortcuts for common workflows
├── requirements.txt                     ← Python deps (just `cryptography`)
├── .gitignore                           ← blocks data/, .env, .DS_Store
│
├── index.html                           ← THE LIVE DASHBOARD (~1.5 MB, encrypted)
├── campaign_schedule_outreach.html      ← identical mirror (legacy URL)
├── county_outreach.html                 ← older console layout (legacy, not encrypted)
│
├── scripts/
│   ├── _common.py                       shared helpers (don't run directly)
│   ├── decrypt.py                       live HTML → data/records.json
│   ├── encrypt.py                       data/records.json → live HTML
│   ├── audit.py                         8 QC checks (read-only)
│   ├── roll_forward.py                  past dates → next monthly occurrence
│   ├── dedupe.py                        remove (county+org+date) duplicates
│   └── deploy.py                        safe commit + push to GitHub Pages
│
├── docs/                                detailed docs (per-topic)
│   ├── ARCHITECTURE.md
│   ├── DATA_SCHEMA.md
│   ├── RUNBOOK.md
│   └── DEPLOYMENT.md
│
├── data/                                ← GITIGNORED. Local working copy.
│   └── records.json                     decrypted dataset; NEVER commit
│
└── campaign-ops/                        Separate Python project for sign-deployment
                                         ops. Self-contained, has its own README.
                                         Not part of the dashboard.
```

---

## 4. How the dashboard works (30-second version)

1. Visitor opens `https://mike1776agschedule.github.io/`
2. Browser receives a 1.5 MB HTML file containing 6 PIN input boxes + an encrypted blob
3. Visitor types the 6-digit PIN
4. Browser derives a key (PBKDF2-HMAC-SHA256, 600,000 iterations) and decrypts the blob client-side
5. Dashboard renders: ~1,370 outreach records across tabs (Home / Database / Calendar / My Itinerary / Call List / Priorities)

If the PIN is wrong, nothing decrypts. No data is ever sent to a server.

**Encryption details:**

| Parameter | Value |
|---|---|
| Cipher | AES-GCM (256-bit) |
| Key derivation | PBKDF2-HMAC-SHA256 |
| Iterations | 600,000 |
| Salt | 16 random bytes (regenerated on every encrypt) |
| IV | 12 random bytes (regenerated on every encrypt) |
| PIN | 6 digits (`040476`) |
| Browser impl | `crypto.subtle` (built-in, no JS libs) |
| Tooling impl | Python `cryptography` package |

---

## 5. The data lifecycle

Every change to the data follows the same shape:

```
                make decrypt        (edit)         make encrypt         make audit            deploy.py
  live HTML ──────────────────▶ data/records.json ─────────────▶ live HTML ─────────────▶ ─────────────▶ GitHub Pages
```

Or as commands:

```bash
make decrypt                       # 1. pull data out of index.html into data/records.json
$EDITOR data/records.json          # 2. edit the JSON (add/fix/remove)
make encrypt                       # 3. re-encrypt with fresh salt/IV, write into both HTML files
make audit                         # 4. run 8 QC checks
python3 scripts/deploy.py "..."    # 5. commit + push (deploys via GitHub Pages in 1-2 min)
```

---

## 6. Makefile shortcuts

| Command | What it does |
|---|---|
| `make help` | Print the menu |
| `make decrypt` | Live HTML → `data/records.json` |
| `make encrypt` | `data/records.json` → both HTML files |
| `make audit` | Run 8 QC checks against live data (read-only) |
| `make roll-forward` | Roll past dates to next monthly occurrence |
| `make dedupe` | Remove duplicate (county+org+date) records |
| `make refresh` | Full pipeline: decrypt → roll-forward → dedupe → encrypt → audit |

After `make refresh` or any data change, commit with:
```bash
python3 scripts/deploy.py "your message here"
```

---

## 7. Data schema (the 20 fields)

Every record has exactly 20 fields. `scripts/encrypt.py` enforces this on every save.

| # | Field | Type | Required | Example | Notes |
|---|---|---|---|---|---|
| 1 | `Region` | string | yes | `Northwest Florida` | One of 6 regions (see below) |
| 2 | `County` | string | yes | `Escambia` | One of the 67 Florida counties |
| 3 | `Category` | string | yes | `Political Infrastructure` | Top-level grouping |
| 4 | `Subcategory` | string | yes | `Republican Executive Committee` | Drives card icon/badge |
| 5 | `Record_Classification` | string | yes | `Verified Opportunity` | Free text label |
| 6 | `Organization_or_Event_Name` | string | yes | `Escambia County REC Meeting` | Card title |
| 7 | `Contact_Name` | string | yes | `Jim Stansel` | Person or `<Org> Office` |
| 8 | `Contact_Title` | string | no | `Chairman` | |
| 9 | `Email` | string | no | `chair@escambiagop.com` | |
| 10 | `Phone` | string | no | `(850) 555-1234` | Must match `(###) ###-####` |
| 11 | `Website` | string | yes | `https://escambiagop.com/` | |
| 12 | `Meeting_or_Event_Date` | string | no | `June 15, 2026` | `Month DD, YYYY` |
| 13 | `Meeting_or_Event_Time` | string | no | `6:30 PM` | Free text; may describe multi-stage events |
| 14 | `Recurrence` | string | no | `3rd Tuesday monthly` | Drives roll-forward logic |
| 15 | `Venue` | string | no | `Library, 200 Spring St` | Address goes here, not Notes |
| 16 | `City` | string | no | `Pensacola` | |
| 17 | `Notes` | string | no | `RSVP not required` | Anything else |
| 18 | `Source_URL` | string | yes | `https://florida.gop/...` | Where verified |
| 19 | `Priority_Tier` | integer | yes | `3` | 0–4. 0 = unrated, 4 = top |
| 20 | `Priority_Label` | string | no | `Strong Impact` | Maps to tier |

**Six regions:** `Northwest Florida` · `North Central Florida` · `Northeast Florida` · `Central Florida` · `Southwest Florida` · `South Florida`

**Six categories:** `Political Infrastructure` · `Agricultural and Industry Associations` · `Law Enforcement and Public Safety` · `Business Organizations` · `County Fairs and Festivals` · `Local Events and Forums`

**Recurrence patterns** the roll-forward script understands:
- `3rd Tuesday monthly` — single Nth-weekday
- `2nd and 4th Thursdays of each month` — multi-ordinal
- `1st Monday monthly except July` — exclusion clauses
- `September-May` — implies Jun/Jul/Aug are off
- `Annual` — not rolled forward
- `One-time` — removed when past

**Date format:** Always `Month DD, YYYY`, single-digit days NOT zero-padded (`June 5, 2026` not `June 05, 2026`).

---

## 8. Common tasks

### Add a single event

```bash
make decrypt
# Open data/records.json, append a new record (copy any existing one as template)
make encrypt
make audit
python3 scripts/deploy.py "Add Highlands County Cattlemen event June 12"
```

### Fix a typo (contact name, phone, venue)

Same as above. Decrypt, edit, encrypt, audit, deploy.

### Weekly maintenance — roll past dates forward

If the dashboard shows events that already happened:

```bash
make refresh                                  # full pipeline
python3 scripts/deploy.py "Weekly refresh $(date +%F)"
```

### Run a QC pass

```bash
make audit
```

Prints 8 checks: schema, past-dated, out-of-window dates, recurrence math,
duplicates, field completeness, county coverage, phone formatting. Exits 1 on any hard fail.

### Change the access PIN

```bash
export FL_AG_PIN=040476          # the OLD pin
python3 scripts/decrypt.py

export FL_AG_PIN=999999          # the NEW pin
python3 scripts/encrypt.py
python3 scripts/audit.py
python3 scripts/deploy.py "Rotate access PIN"
```

Then tell the team the new PIN **out-of-band** (Signal, in person — not email/Slack). **Never commit the PIN to git.**

### Bulk find/replace across the dataset

```bash
make decrypt
python3 -c "
import json
d = json.load(open('data/records.json'))
for r in d:
    if r['Subcategory'] == 'Farm Bureau':
        r['Subcategory'] = 'Florida Farm Bureau'
json.dump(d, open('data/records.json','w'), indent=2)
"
make encrypt audit
python3 scripts/deploy.py "Standardize Farm Bureau subcategory"
```

### Decrypt for one-off analysis

```bash
FL_AG_PIN=040476 python3 scripts/decrypt.py /tmp/snapshot.json
jq '.[] | select(.County == "Escambia")' /tmp/snapshot.json
```

### Edit the UI (CSS / JS / HTML structure)

Direct edits to `index.html`. After editing:

```bash
cp index.html campaign_schedule_outreach.html    # keep mirror in sync
git add index.html campaign_schedule_outreach.html
git commit -m "..."
git push
```

Always edit `index.html` and copy to `campaign_schedule_outreach.html` — never edit the mirror directly.

### Roll back a bad deploy

```bash
git log --oneline | head           # find the last good commit
git revert <bad-sha>               # creates a new commit that undoes the bad one
git push
```

GitHub Pages redeploys in 1-2 minutes. Tell users to hard-refresh (Cmd+Shift+R / Ctrl+Shift+R).

**Never** `git push --force` to `main`.

---

## 9. What NOT to do

- **Don't commit `data/records.json`** — it's the unencrypted dataset (already gitignored, but don't override).
- **Don't edit the `window.FL_AG_ENCRYPTED = { ... }` block** by hand — always use `scripts/encrypt.py`.
- **Don't reuse the same salt/IV** manually — `encrypt.py` regenerates them; let it.
- **Don't `git push --force`** to `main` — GitHub Pages serves whatever is at HEAD.
- **Don't bump PBKDF2 iterations** without testing decrypt speed on mobile (currently ~1s on iPhone).
- **Don't put the PIN in commits, environment files that get committed, Slack, or email.** Pass it out-of-band only.
- **Don't edit `campaign_schedule_outreach.html` directly** — edit `index.html` and copy.
- **Don't claim "done" on data changes without running `make audit` first.**

---

## 10. Troubleshooting

### `make audit` says `FL_AG_PIN not set`

```bash
export FL_AG_PIN=040476
# Add to ~/.zshrc or ~/.bashrc to make it permanent
```

### `git push` fails with 403 / permission denied

You need to be added as a collaborator on the GitHub repo. Ask the previous maintainer or org owner.

### `make decrypt` fails with `Incorrect PIN`

The PIN was rotated. Ask the team for the current PIN. Or check sessionStorage on a working browser: open the live site DevTools → Application → Session Storage → `fl_ag_pin`.

### `pip install cryptography` fails on macOS

```bash
xcode-select --install         # install command-line tools
pip3 install --upgrade pip
pip3 install -r requirements.txt
```

### Browser shows old data after a deploy

Hard refresh: **Cmd+Shift+R** (Mac) or **Ctrl+Shift+R** (Windows/Linux).
The encrypted HTML is 1.5 MB and aggressively cached by browsers and Cloudflare.

### Audit shows recurrence mismatches that look wrong

Multi-pattern recurrences like `2nd and 4th Thursdays` may register as
false-positives. The audit only flags single-pattern matches. If `actual` matches
ANY pattern in the recurrence string, it's fine — verify by hand.

### Verifying a deploy went through

```bash
LIVE=$(curl -s https://mike1776agschedule.github.io/ | wc -c)
LOCAL=$(wc -c < index.html)
echo "live=$LIVE local=$LOCAL"   # should match within ~2 min of pushing
```

If they don't match after 2 minutes, check repo Actions tab for build failures.

---

## 11. Where to read more

The standalone docs in `docs/` go deeper on each topic:

| File | When to read it |
|---|---|
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Common tasks — same recipes as section 8 above but standalone |
| [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) | Deeper on the 20-field schema, edge cases, recurrence parsing |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | When you need to change the encryption or how the page works |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | When something deploys weirdly or you need to roll back |

---

## 12. Project history (in commit messages)

The previous maintainer left commit messages explaining each QC round. To see them:

```bash
git log --oneline | head -40
git log --grep="Round" --oneline    # 40+ rounds of QC fixes during initial build
```

Notable past decisions:
- Original data was 1,709 records → trimmed to ~1,370 after deduplication + roll-forwards
- April 2026 events were removed once the month passed (precedent: prune stale months)
- AES-GCM + PBKDF2 encryption added to keep contact data out of public view
- Login screen was redesigned twice — final version is minimalist (just 6 boxes, no chrome)

---

## 13. Quick reference card

```
Live site:    https://mike1776agschedule.github.io/
PIN:          040476
Repo:         github.com/mike1776agschedule/mike1776agschedule.github.io

Setup:        pip3 install -r requirements.txt
              export FL_AG_PIN=040476
              make audit

Add data:     make decrypt
              $EDITOR data/records.json
              make encrypt audit
              python3 scripts/deploy.py "msg"

Weekly:       make refresh
              python3 scripts/deploy.py "Weekly refresh $(date +%F)"

Rollback:     git revert <bad-sha> && git push
```

Welcome to the project. Anything that's not covered here, check the commit
history first (`git log --oneline`) — most decisions are explained there.
