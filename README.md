# Florida Ag Commissioner Outreach Dashboard

Single-file HTML dashboard hosted on GitHub Pages. Tracks campaign outreach
opportunities across all 67 Florida counties — Republican infrastructure,
agricultural associations, law enforcement / firefighter unions, chambers
of commerce, county fairs, and local events.

- **Live site:** https://mike1776agschedule.github.io/
- **Access PIN:** `040476` (6 digits — required to decrypt the dashboard in-browser)
- **Repo:** https://github.com/mike1776agschedule/mike1776agschedule.github.io

## Quick start (new colleague)

```bash
git clone https://github.com/mike1776agschedule/mike1776agschedule.github.io.git fl_ag_campaign_site
cd fl_ag_campaign_site
pip3 install -r requirements.txt
export FL_AG_PIN=040476

# Confirm everything works:
make audit
```

If `make audit` prints `All hard checks PASS`, you're ready to go.

## Repo layout

```
fl_ag_campaign_site/
├── index.html                           ← LIVE dashboard (1.6 MB, encrypted)
├── campaign_schedule_outreach.html      ← identical mirror (legacy URL)
├── county_outreach.html                 ← older console layout (legacy, not encrypted)
│
├── scripts/                             ← Python tooling for the data lifecycle
│   ├── _common.py                       (shared helpers — don't run directly)
│   ├── decrypt.py                       Dashboard → data/records.json
│   ├── encrypt.py                       data/records.json → Dashboard
│   ├── audit.py                         QC report (read-only)
│   ├── roll_forward.py                  Past dates → next monthly occurrence
│   ├── dedupe.py                        Remove (county, org, date) duplicates
│   └── deploy.py                        Commit + push to GitHub Pages
│
├── docs/
│   ├── ARCHITECTURE.md                  How the encrypted single-file SPA works
│   ├── DATA_SCHEMA.md                   The 20-field record schema
│   ├── DEPLOYMENT.md                    GitHub Pages mechanics, rollback
│   └── RUNBOOK.md                       Common tasks (add event, fix typo, rotate PIN, etc.)
│
├── data/                                ← gitignored — local working copy
│   └── records.json                     (decrypted dataset; never commit)
│
├── campaign-ops/                        Separate Python project for sign-deployment ops
│                                        (has its own README; not part of the dashboard)
│
├── Makefile                             Shortcuts for common workflows
├── requirements.txt                     Python deps (just `cryptography`)
└── .gitignore                           Blocks data/, .env, .DS_Store, etc.
```

## The data lifecycle

Every change to the dashboard data follows the same shape:

```
                   make decrypt         (edit)          make encrypt        make audit       deploy.py
   live HTML  ───────────────────▶ data/records.json ──────────────▶ live HTML ──────────▶ ────────────▶ GitHub Pages
```

The longer version:

```bash
make decrypt                    # 1. Pull data out of index.html into data/records.json
$EDITOR data/records.json       # 2. Edit the JSON (add/fix/remove)
make encrypt                    # 3. Re-encrypt with a fresh salt/IV, write into both HTML files
make audit                      # 4. Run QC checks (schema, duplicates, past dates, etc.)
python3 scripts/deploy.py "..." # 5. Commit + push (deploys via GitHub Pages)
```

## Common Makefile targets

| Command | What it does |
|---|---|
| `make decrypt` | Decrypt live HTML → `data/records.json` |
| `make encrypt` | Encrypt `data/records.json` → both HTML files |
| `make audit` | Run all 8 QC checks against live data |
| `make roll-forward` | Roll past dates to next monthly occurrence |
| `make dedupe` | Remove duplicate records |
| `make refresh` | Full pipeline: decrypt → roll-forward → dedupe → encrypt → audit |
| `make help` | Print this menu |

## How the page works (30-second version)

1. Visitor opens `https://mike1776agschedule.github.io/`
2. Browser receives a 1.6 MB HTML file containing 6 PIN input boxes + an encrypted blob
3. Visitor types `040476`
4. Browser derives a key (PBKDF2 600k iterations) and decrypts the blob client-side
5. Dashboard renders: 1,300+ outreach records, calendar, call list, itinerary tabs

If the PIN is wrong, nothing decrypts. No data is ever sent to a server —
authentication is purely "do you have the key to read this blob."

Full details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What to read first

1. **[docs/RUNBOOK.md](docs/RUNBOOK.md)** — start here. Step-by-step recipes for
   every routine task (add event, fix typo, roll forward stale dates, rotate PIN).
2. **[docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md)** — the 20 fields on every record
   and what they mean.
3. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — only when you need to change
   the encryption, the page structure, or how decryption works.
4. **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — only when something deploys
   weirdly or you need to roll back.

## Production credentials

| What | Where |
|---|---|
| Access PIN | `040476` — needed for `FL_AG_PIN` env var and to view the live site |
| GitHub push | The owner of `mike1776agschedule.github.io` must add you as a collaborator |
| GitHub Pages config | Settings → Pages → Source: `main` branch, root `/` |

## Questions?

The runbook covers everything routine. For one-off questions about why a
specific record looks the way it does, check the file's git history first:

```bash
git log --all --oneline -- index.html | head -30
```

The previous maintainer left commit messages that explain each round of QC
fixes (search for `Round` in the log).
