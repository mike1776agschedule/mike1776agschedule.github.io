# Deployment

## How GitHub Pages serves this site

The repo `mike1776agschedule/mike1776agschedule.github.io` is configured as a
user-level GitHub Pages site. The `main` branch is served directly — whatever
is at the root of `main` is what visitors see.

- Production URL: **https://mike1776agschedule.github.io/**
- The default file `index.html` is served at `/`
- `campaign_schedule_outreach.html` is reachable at `/campaign_schedule_outreach.html` (legacy link)
- `county_outreach.html` is reachable at `/county_outreach.html` (legacy console)

## Pushing a deploy

The deploy step is just `git push`. GitHub Pages picks up new commits on `main`
and rebuilds within 1-2 minutes.

The `scripts/deploy.py` helper:
1. Stages ONLY `index.html` and `campaign_schedule_outreach.html`
2. Refuses to run if anything else is already staged (safety)
3. Commits with the message you provide
4. Pushes to `origin/main`

```bash
python3 scripts/deploy.py "Add June Walton REC date"
```

## First-time setup on a new machine

```bash
git clone https://github.com/mike1776agschedule/mike1776agschedule.github.io.git fl_ag_campaign_site
cd fl_ag_campaign_site
pip3 install -r requirements.txt
export FL_AG_PIN=040476
python3 scripts/audit.py    # verify you can decrypt
```

You need push access to the GitHub repo. If `git push` fails with 403, ask
the repo owner to add you as a collaborator on
`mike1776agschedule/mike1776agschedule.github.io`.

## Verifying a deploy went through

```bash
curl -sI https://mike1776agschedule.github.io/ | head -5
curl -s https://mike1776agschedule.github.io/ | grep -c "FL_AG_ENCRYPTED"
# Should print: 1
```

Compare the byte size to your local file:
```bash
LIVE=$(curl -s https://mike1776agschedule.github.io/ | wc -c)
LOCAL=$(wc -c < index.html)
echo "live=$LIVE local=$LOCAL"
```

These should match within seconds of a deploy. If they don't match after
2 minutes, check https://github.com/mike1776agschedule/mike1776agschedule.github.io/actions
for build failures.

## Browser cache caveat

The encrypted HTML is ~1.6 MB and aggressively cached by browsers and CDNs.
After a deploy, users may see the old data until they:
- Hard refresh (Cmd+Shift+R on Mac, Ctrl+Shift+R elsewhere)
- Or wait for the cache to expire (usually 10 min)

Tell stakeholders to hard refresh when you push fixes.

## Rolling back

```bash
git log --oneline | head        # find the good commit
git revert <bad-sha>
git push
```

Never `--force` push to main.
