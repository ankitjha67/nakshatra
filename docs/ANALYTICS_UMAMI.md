# Product analytics — Umami

Umami is privacy-first, **cookieless** web analytics (no cookies, no personal data, honors
Do-Not-Track) — so it complements the internal admin analytics (tokens/revenue/funnel) with
product/web usage **without** needing a cookie-consent banner. It's wired but **dormant until
configured**.

## Enable it
Pick one:
- **Umami Cloud** (umami.is) — create a website, copy its **Website ID** and the script URL
  (`https://cloud.umami.is/script.js`, or the EU host).
- **Self-hosted** — run Umami (Docker/Node + Postgres), add your site, use your own script URL.

Then set in `web/.env` (and your CI/hosting build env):
```
VITE_UMAMI_SRC=https://cloud.umami.is/script.js
VITE_UMAMI_WEBSITE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```
Rebuild + deploy the web. With both unset, `analytics.js` is a no-op (nothing loads, no requests).

## What's tracked (`web/src/lib/analytics.js`)
- **Auto:** the initial pageview (Umami default); plus **`trackPage(tab)`** — each tab view as an SPA
  pageview so the Pages report reflects feature usage.
- **Acquisition:** `sign_up` / `login` (with `{method: google|email}`; Google new-vs-returning distinguished).
- **Activation:** `reading` `{type, locked}`, `chat`, `match`, `prashna`, `btr`, `panchang`, `transits`.
- **Monetization:** `checkout_start` `{tier}`, `redeem` `{kind}`.
- **Engagement / compliance ops:** `feedback` `{category}`, `data_export`, `consent_withdraw`,
  `account_delete`, `grievance`, `nominee`.
- Add more with `track("event_name", {…})` — never throws, safe when analytics is off.

## Privacy
Cookieless + no PII → disclosed as a sub-processor in `legal/PRIVACY_POLICY.md` (§3, §7),
`legal/ROPA.md` (activity F) and `legal/DPA.md` (Part A). No consent banner required. Prefer the EU
Umami host or self-hosting if you want data residency control.
