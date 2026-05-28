# Runbook — Common Tasks

All commands assume:
```bash
cd /Users/<you>/projects/fl_ag_campaign_site   # or wherever you cloned
export FL_AG_PIN=040476                         # set once per terminal session
```

The shape of every workflow is:
```
decrypt  →  edit  →  encrypt  →  audit  →  deploy
```

---

## 1. Add a single event

```bash
make decrypt                         # data/records.json appears
# open data/records.json in your editor, append a new record
# (copy any existing one; keep the 20 fields in the same order)
make encrypt                          # writes new ciphertext into both HTML files
make audit                            # confirm no schema/duplicate issues
python3 scripts/deploy.py "Add Highlands County Cattlemen event June 12"
```

## 2. Fix a typo in a contact name / phone / venue

Same as above. Edit `data/records.json`, `make encrypt`, `make audit`, deploy.

## 3. Roll past-dated events forward (weekly maintenance)

If the dashboard shows events that have already happened, the dataset is stale.
The roll-forward script regenerates the next monthly occurrence for each
past-dated record that has a parseable `Recurrence` pattern, and removes
one-time events whose date has passed.

```bash
make decrypt
make roll-forward          # rewrites data/records.json
make dedupe                # remove any duplicates the roll-forward created
make encrypt
make audit                 # should be all PASS
python3 scripts/deploy.py "Weekly roll-forward $(date +%F)"
```

## 4. Run a full QC pass

```bash
FL_AG_PIN=040476 python3 scripts/audit.py
```

Outputs schema integrity, past-dated count, duplicates, field completeness
percentages, county coverage, and phone formatting. Exit code 1 if any hard
check fails.

## 5. Change the access PIN

This requires re-encrypting the data with a new key.

```bash
export FL_AG_PIN=040476            # the OLD pin
python3 scripts/decrypt.py

export FL_AG_PIN=999999            # the NEW pin (6 digits)
python3 scripts/encrypt.py
python3 scripts/audit.py
python3 scripts/deploy.py "Rotate access PIN"
```

Then tell the team the new PIN out-of-band. **Do not commit the PIN to git.**

## 6. Recover when a deploy looks broken

```bash
git log --oneline | head -10       # find the last known-good commit
git revert <bad-commit-sha>        # creates a new commit that undoes the bad one
git push
```

GitHub Pages will redeploy in 1-2 minutes. Hard-refresh the browser
(Cmd+Shift+R / Ctrl+Shift+R) — the encrypted blob is cached aggressively.

## 7. Make a change to the UI (CSS / JS / layout)

This is a direct edit to `index.html` between the `<style>` and `</style>`
tags, or inside `<script>` blocks. After editing:

```bash
# Mirror your change to the other HTML file:
cp index.html campaign_schedule_outreach.html
git add index.html campaign_schedule_outreach.html
git commit -m "..."
git push
```

(Do NOT edit `campaign_schedule_outreach.html` directly. Always edit
`index.html` and copy over.)

## 8. Decrypt one-off for analysis

```bash
FL_AG_PIN=040476 python3 scripts/decrypt.py /tmp/snapshot.json
jq '.[] | select(.County == "Escambia")' /tmp/snapshot.json
```

## 9. Bulk find/replace across the dataset

```bash
make decrypt
# Use jq or a Python one-liner against data/records.json
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

## What NOT to do

- Don't commit `data/records.json` (already gitignored). It's the unencrypted dataset.
- Don't reuse the same salt/IV manually. `encrypt.py` regenerates them — let it.
- Don't edit the `window.FL_AG_ENCRYPTED = { ... }` block by hand.
- Don't `git push --force` to main. GitHub Pages serves whatever is at HEAD.
- Don't bump the PBKDF2 iteration count without testing decrypt speed on mobile.
