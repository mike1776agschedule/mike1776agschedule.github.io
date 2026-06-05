# ACCURACY — how we measure validation accuracy

This file tracks how reliable our event validation is, so the accuracy can be
shown to stakeholders and improved over time.

## The post-event problem (why "did it happen?" is hard)

For most events we **cannot** confirm after the fact whether they occurred:

| Event type | Post-event confirmable? | How |
|---|---|---|
| Routine club meetings (most records) | ❌ Not remotely | Recaps/photos go on **Facebook** behind a login wall — only a logged-in human can check |
| Public / ticketed / press events (rodeo, some chambers) | ✅ Sometimes | Local news, public event pages, photos |
| Government / REC at public venues | ⚠️ Occasionally | Posted agendas or minutes |

Facebook blocks automated requests (returns `400` to everything), so liveness/
content checks of FB pages must be done by a human. See [FACEBOOK.md](FACEBOOK.md).

## How we measure accuracy instead

Three methods, in order of usefulness:

1. **Independent 2nd-source corroboration** — for a sample of ✅-verified events,
   re-confirm the date/venue from a *different* source than the one we used. The
   share that agree is our reliability score. Runnable now, no waiting.
2. **Falsifiable predictions** — our ⚠️ discrepancy corrections are specific,
   testable claims that contradict the original dataset. As each date passes,
   record who was right (us vs. the original data). This measures the *value* the
   validation adds. Seeded below.
3. **Post-event spot-checks** — for the few public events, confirm via news.

---

## Falsifiable predictions ledger (our corrections vs. the original data)

Each row is a claim we made that the original date/venue was wrong. Fill
**Outcome** once confirmed (your own check, a Facebook post, news, or the date
passing). `2nd source` = an independent corroboration of our correction.

| Event | Our correction | Original data said | Basis (source) | 2nd source | Outcome |
|---|---|---|---|---|---|
| Broward County REC | Next mtg **Jun 22** | Jun 8 | browardgop.com/next-meeting | _todo_ | ☐ |
| Republican Club of Longboat Key | **No June mtg** (seasonal Oct–Apr) | Jun 9 | rclbk.org | _todo_ | ☐ |
| Homosassa River Republican Club | **3rd Tue (Jun 16)**, Margarita Grill | Jun 4, Beverly Hills | chronicleonline / rpocitrus | _todo_ | ☐ |
| Shoal River Republican Club | **3rd Tue (Jun 16)**, Eagle's Nest | Jun 9, Hideaway Pizza | okaloosagop.com | _todo_ | ☐ |
| Republican Club of Timber Pines | **3rd Tue (Jun 16)**, Northcliffe Church | Jun 10, Timber Pines | tprepublicanclub / hernandosun | _todo_ | ☐ |
| Republican Club of The Villages | **4th Wed (Jun 24)** | Jun 9 (Tue) | sumterrepublicans.com/clubs | _todo_ | ☐ |
| Central Santa Rosa Republican Club | **3rd Thu (Jun 18)** | Jun 4 | Santa Rosa REC | _todo_ | ☐ |
| Republican Club of South Sarasota Co. | likely **2nd Thu (Jun 11)** | Jun 10 (Wed) | rcsscgop | _todo_ | ☐ |
| 30-A Republican Club | likely **defunct/renamed** | Jun 4 | waltonflgop.com/clubs | _todo_ | ☐ |
| Coral Springs Republican Club | **duplicate** of Parkland club | (own record) | browardgop | _todo_ | ☐ |
| Lake County Republican Women Federated | **duplicate** of Lake Federated RWC | (own record) | lakecountyrepublicans | _todo_ | ☐ |
| RW Club of Sarasota | **no June mtg** (next Sep 4) | Jun 5 | republicanwomensclubofsarasota.com | _todo_ | ☐ |

## Verified-sample corroboration (to run)

Pick ~12 ✅-verified events at random; confirm each from a second, independent
source. Record agreement.

| Event | Our verified date/venue | Source 1 (used) | Source 2 (independent) | Agree? |
|---|---|---|---|---|
| _to be sampled_ | | | | ☐ |

---

## Running metrics (update as the tables fill)

- **Falsifiable predictions confirmed:** `__ / 12`
- **Verified-sample 2-source agreement:** `__ / __`
- **This-week dataset confidence (auto):** see [SCHEDULE.md](SCHEDULE.md) header — currently **39 verified · 14 need-fix · 11 unverifiable** of 64 events.

_Last updated: 2026-06-04._
