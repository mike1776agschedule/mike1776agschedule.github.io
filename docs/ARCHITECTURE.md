# Architecture

## TL;DR

A single-file HTML dashboard hosted on GitHub Pages. The campaign outreach data
is embedded in the HTML as an AES-GCM encrypted blob. On page load, a 6-digit
PIN derives a key (PBKDF2-HMAC-SHA256, 600,000 iterations), decrypts the blob
in the browser, and renders the dashboard.

```
                          ┌────────────────────────────────────────────┐
                          │  GitHub Pages: mike1776agschedule.github.io │
                          │                                             │
                          │  index.html (~1.6 MB)                       │
                          │  ┌──────────────────────────────────────┐   │
                          │  │ <style>...login + dashboard CSS...   │   │
                          │  │ <body>                                │   │
                          │  │   <div id="login-overlay">            │   │
                          │  │     6 PIN boxes                       │   │
                          │  │   </div>                              │   │
                          │  │   <div class="shell">                 │   │
                          │  │     dashboard tabs (hidden until ok)  │   │
                          │  │   </div>                              │   │
                          │  │ <script>                              │   │
                          │  │   window.FL_AG_ENCRYPTED = {          │   │
                          │  │     salt, iv, ciphertext, iterations  │   │
                          │  │   };                                  │   │
                          │  │   attemptUnlock(pin) → decrypt →      │   │
                          │  │     initDashboard()                   │   │
                          │  │ </script>                             │   │
                          │  └──────────────────────────────────────┘   │
                          └────────────────────────────────────────────┘
```

## Why a single HTML file?

- Zero backend, zero infrastructure cost (GitHub Pages = free static hosting)
- Zero build step — view it locally by opening `index.html`
- All data ships with the page; no separate API to maintain
- Easy to back up: the file IS the deployment

## Why encryption?

The site is publicly reachable (no auth in front of GitHub Pages). The data —
campaign contact info, scheduled meetings, internal priority labels — should
NOT be in clear view of competitors or random visitors. Client-side AES-GCM
with a PIN provides a low-friction gate; only people who know the PIN
can decrypt and read the data.

## Files

| File | Purpose |
|---|---|
| `index.html` | Main dashboard. The GitHub Pages default — what people see when they visit the site. |
| `campaign_schedule_outreach.html` | Identical mirror (kept in sync for legacy links). |
| `county_outreach.html` | Older Master Console layout. Not encrypted. Legacy. |
| `scripts/` | Python tooling for the encrypt/decrypt/audit/deploy lifecycle. |
| `docs/` | This documentation. |
| `data/records.json` | Local-only decrypted records (gitignored). |
| `campaign-ops/` | Separate Python project for sign-deployment ops. Self-contained. |

## Encryption details

| Parameter | Value |
|---|---|
| Cipher | AES-GCM (256-bit) |
| Key derivation | PBKDF2-HMAC-SHA256 |
| Iterations | 600,000 |
| Salt | 16 random bytes (regenerated on every encrypt) |
| IV | 12 random bytes (regenerated on every encrypt) |
| PIN | 6 digits (currently `040476`) |
| Implementation | Browser: `crypto.subtle`. Tooling: Python `cryptography` package. |

**Important:** The salt and IV are regenerated on every `scripts/encrypt.py` run.
This is required for AES-GCM security (never reuse an IV with the same key).

## Page load flow

1. Browser fetches `index.html`
2. CSS renders the empty PIN screen (no card, no logo — just 6 input boxes)
3. User types 6 digits → `attemptUnlock(pin)` is called automatically
4. JS derives key via PBKDF2, decrypts the embedded ciphertext
5. On success: hide overlay, parse JSON, call `initDashboard()`, render tabs
6. On failure: shake the boxes red, clear them, refocus the first box
7. PIN cached in `sessionStorage` so reloads don't require re-entry
