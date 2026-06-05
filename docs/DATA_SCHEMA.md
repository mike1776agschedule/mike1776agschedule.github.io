# Data Schema

Every record in the dataset has exactly **21 fields**, in this order:

| # | Field | Type | Required | Example | Notes |
|---|---|---|---|---|---|
| 1 | `Region` | string | yes | `Northwest Florida` | One of six. See list below. |
| 2 | `County` | string | yes | `Escambia` | One of the 67 Florida counties. |
| 3 | `Category` | string | yes | `Political Infrastructure` | Top-level grouping. |
| 4 | `Subcategory` | string | yes | `Republican Executive Committee` | Drives the icon/badge on the card. |
| 5 | `Record_Classification` | string | yes | `Verified Opportunity` | Free text label. Common: `Verified Opportunity`, `Organization Contact`. |
| 6 | `Organization_or_Event_Name` | string | yes | `Escambia County REC Meeting` | Display title on the card. |
| 7 | `Contact_Name` | string | yes (can be org name) | `Jim Stansel` | Person OR `<Org> Office` placeholder. |
| 8 | `Contact_Title` | string | no | `Chairman` | |
| 9 | `Email` | string | no | `chair@escambiagop.com` | |
| 10 | `Phone` | string | no | `(850) 555-1234` | Must match `(###) ###-####` format. |
| 11 | `Website` | string | yes | `https://escambiagop.com/` | Org's public site. |
| 12 | `Meeting_or_Event_Date` | string | no | `June 15, 2026` | `Month DD, YYYY` format. Blank if TBD. |
| 13 | `Meeting_or_Event_Time` | string | no | `6:30 PM` | Free text. May describe multi-stage events. |
| 14 | `Recurrence` | string | no | `3rd Tuesday monthly` | Drives roll-forward logic. |
| 15 | `Venue` | string | no | `Pensacola Library, 200 Spring St` | Address goes here, not in Notes. |
| 16 | `City` | string | no | `Pensacola` | |
| 17 | `Notes` | string | no | `Public meeting. RSVP not required.` | Anything else. |
| 18 | `Source_URL` | string | yes | `https://florida.gop/republican-parties/escambia/` | Where this data was verified. |
| 19 | `Facebook_URL` | string | no | `https://www.facebook.com/groups/swbrogop/` | Org's Facebook page or group. Added 2026-06; used for human verification of dates that only live on Facebook. |
| 20 | `Priority_Tier` | integer | yes | `3` | 0–4. 0 = unrated, 4 = top. |
| 21 | `Priority_Label` | string | no | `Strong Impact` | Maps to tier. |

## Region values (exactly 6)

- `Northwest Florida`
- `North Central Florida`
- `Northeast Florida`
- `Central Florida`
- `Southwest Florida`
- `South Florida`

## Category values

- `Political Infrastructure` — REC, Republican Clubs, Federated Women, Young Republicans, RNHA, etc.
- `Agricultural and Industry Associations` — Farm Bureau, Cattlemen, Forestry, FFA, etc.
- `Law Enforcement and Public Safety` — PBA, FOP, IAFF firefighter unions
- `Business Organizations` — Chambers of Commerce
- `County Fairs and Festivals` — Annual fairs
- `Local Events and Forums` — Other one-off events

## Recurrence patterns (parsed by roll_forward.py)

- `3rd Tuesday monthly` — single Nth-weekday
- `2nd and 4th Thursdays of each month` — multi-ordinal, both apply
- `1st Monday monthly except July` — exclusion clauses
- `September-May` — implies June/July/Aug are off
- `1st Tuesday at 5 PM; 1st Monday dinners in even months` — multiple patterns
- `Annual` — non-monthly; not rolled forward
- `One-time` — non-recurring; removed when past

## Date format

Always `Month DD, YYYY` (e.g. `June 5, 2026`). Single-digit days are NOT
zero-padded (`June 5, 2026`, not `June 05, 2026`). The `roll_forward.py`
script enforces this.

## Schema enforcement

- `scripts/encrypt.py` automatically normalizes every record to the 21-field
  schema in canonical order, filling missing fields with `""` (or `0` for
  `Priority_Tier`). You cannot ship a malformed record.
- `scripts/audit.py` Check #1 verifies schema integrity against the live blob.
