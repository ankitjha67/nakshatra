# Go-Live Runbook, Nakshatra

Operational runbook for production. The product is **live** on Google Cloud Run
(API) + Firebase Hosting (web); the only step gated on external account setup is
**live Razorpay billing**.

## Current production state

| Piece | Value |
|------|-------|
| API | Cloud Run `jyotish-api`, region `asia-south1` → `https://jyotish-api-1075458724715.asia-south1.run.app` |
| Web | Firebase Hosting → `https://nakshatra-prod-2026.web.app` |
| Engine | `maha-jyotish-7.0` (proprietary; copied into `api/`, gitignored, uploaded at deploy) |
| LLM | Vertex `gemini-2.5-pro`, `VERTEX_LOCATION=global` |
| Store | Firestore (`STORE_BACKEND=firestore`) |
| Default tier | `free` (pay/redeem to unlock) |
| CORS | locked to the web origin(s) |
| Secrets | `admin-api-key`, `api-key-pepper`, `internal-token`, `razorpay-*` in Secret Manager |
| Birth lock | on (one native = date+place per account) |
| Payments | **off** (`PAYMENTS_PROVIDER` unset) until live keys are added |

## Deploy (when shipping changes)

```
# API (engine must be present locally in api/, it is gitignored)
cd api && gcloud run deploy jyotish-api --source . --region asia-south1 --allow-unauthenticated
# web (the firestore:rules target is REQUIRED, it ships the deny-by-default guard)
cd web && npm run build && firebase deploy --only hosting,firestore:rules
```
`--source` preserves env + secret refs across redeploys.

## Beta cohort (now)

1. Each tester signs in once (creates their Firebase uid) — they start `free`.
2. **Admin → Access codes → Generate** (`beta`, count 20, tier `enterprise`, uses 1,
   expiry e.g. 30) → copy the codes from the one-time box.
3. Share one code per tester. They redeem via **"Have an access code?"** (main
   screen or any paywall) → instant `enterprise`, tagged `beta`.
4. Track redemptions in the codes list; watch usage in **Admin** + the audit log.

## Razorpay go-live (real revenue) — REVIEW BEFORE FLIPPING (money path)

1. **In the Razorpay dashboard**
   - Create a **Plan** per paid tier (Basic ₹299 / Pro ₹999 / Enterprise ₹4999, monthly) → note `plan_…` ids.
   - (Optional) Create **Offers** for discounts → note `offer_…` ids.
   - Add a **webhook** → URL `…/webhooks/payments`, secret =
     `gcloud secrets versions access latest --secret=razorpay-webhook-secret`,
     events: `subscription.charged`, `refund.*` (and `payment.captured` for top-ups).
2. **Add live keys + config**
   ```
   printf '%s' '<live_key_id>'     | gcloud secrets versions add razorpay-key-id --data-file=-
   printf '%s' '<live_key_secret>' | gcloud secrets versions add razorpay-key-secret --data-file=-
   gcloud run services update jyotish-api --region asia-south1 \
     --update-env-vars "^@^PAYMENTS_PROVIDER=razorpay@RAZORPAY_PLANS=basic=plan_..,pro=plan_..,enterprise=plan_..@RAZORPAY_OFFERS=pro=offer_.."
   ```
3. **Validate** (no real charge): run the webhook harness against prod
   ```
   python api/scripts/razorpay_webhook_test.py --base <API_URL> \
     --secret "$(gcloud secrets versions access latest --secret=razorpay-webhook-secret)" \
     --uid <a-test-firebase-uid> --tier pro --charge-id ch_$(date +%s)
   ```
   Expect: grant-once · idempotent replay · bad-signature rejected.
4. Do **one real ₹ test** on Basic from the web checkout, confirm tier + credits +
   an audit entry, then refund it from **Admin → Refund requests**.
5. **Admin → Revoke all beta** to move testers to `free`. Real users now pay; the
   webhook tags them `payment`, so beta-revoke never touches them.

## Rollback

- **Bad API release:** `gcloud run services update-traffic jyotish-api --region asia-south1 --to-revisions <PREV>=100` (list: `gcloud run revisions list --service jyotish-api --region asia-south1`).
- **Bad web release:** Firebase Console → Hosting → roll back to the previous version (or `firebase hosting:rollback`).
- **Disable payments fast:** `gcloud run services update jyotish-api --region asia-south1 --update-env-vars PAYMENTS_PROVIDER=none` (webhook returns 501; no grants).
- **Runaway LLM spend:** set `DAILY_GLOBAL_TOKEN_BREAKER` to a cap; per-user daily ceiling + per-turn cap already bound spend.
- **Cache/version issues:** bump the version stamps in `api/app/__init__.py` to bust cached readings.

## Operate

- **Admin dashboard** (web, requires the Firebase `admin` claim): platform stats,
  set-tier, beta grant/revoke, access codes, refund requests, birth-change
  requests, flagged users/bans, audit log.
- **Admin claim:** set `{"admin": true}` on a Firebase user (Identity Toolkit
  `accounts:update` with `customAttributes`).
- **Birth-detail changes:** users request from **Account**; admin approves
  (unlocks) — or use `POST /admin/users/{uid}/reset-birth` for an instant fix.
- **Secrets:** add a new version with `gcloud secrets versions add <name> --data-file=-`;
  the service reads `:latest` on next revision.

## Pre-launch checklist

- [x] Engine + Vertex live; readings grounded (anti-slop), tier-gated, no leakage.
- [x] Chat tiered + jailbreak/exfiltration hardened; server-side history.
- [x] Birth-details lock (one native per account) + change-request flow.
- [x] Access codes (hashed) + redemption; beta grant/revoke; discounts.
- [x] CORS locked; secrets in Secret Manager; default tier free; admin gated + audited.
- [ ] **Razorpay live keys + Plans/Offers + webhook; flip `PAYMENTS_PROVIDER` (your step).**
- [ ] Legal docs reviewed by counsel + linked in footer/checkout (`docs/legal/`).
- [ ] (Optional) email notifications; `DAILY_GLOBAL_TOKEN_BREAKER` set.

## Scheduled metrics digest (Cloud Scheduler)

`POST /internal/digest` (guarded by `X-Internal-Token: <INTERNAL_TOKEN>`) compiles a
metrics digest (users, tier mix, signups 7d, MRR, net revenue, tokens) — it logs it
and, if `DIGEST_WEBHOOK_URL` is set, POSTs `{text}` to that URL (point it at a Slack
incoming webhook, Zapier/Make, or an email relay).

```
# optional: where to deliver the digest
gcloud run services update jyotish-api --region asia-south1 \
  --update-env-vars DIGEST_WEBHOOK_URL=https://hooks.slack.com/services/XXX
# daily 8am IST cron -> the digest endpoint
gcloud scheduler jobs create http nakshatra-digest --location asia-south1 \
  --schedule "30 2 * * *" --uri "<API_URL>/internal/digest" --http-method POST \
  --message-body "{}" \
  --headers "X-Internal-Token=$(gcloud secrets versions access latest --secret=internal-token)"
# NOTE: --message-body "{}" is required; Cloud Run rejects a body-less POST with 411.
```

## Continuous fraud monitoring (Cloud Scheduler)

`POST /internal/fraud-scan` (guarded by `X-Internal-Token`) scores every user with the
risk model (app/fraud.py: malicious intent, injection attempts, refund abuse, token
velocity, shared IPs), persists each user's risk band (drives the in-app warning
banner), and auto-suspends anyone at/over `FRAUD_AUTOBAN_SCORE` (default 100; set 0 to
disable auto-ban). Destructive chat ("drop all the database", rm -rf, SQLi) is also
blocked in real time at `/v1/chat`. Tune `FRAUD_WATCH_SCORE` / `FRAUD_HIGH_SCORE`.

```
# every 10 minutes (--message-body required; Cloud Run rejects a body-less POST)
gcloud scheduler jobs create http nakshatra-fraud-scan --location asia-south1 \
  --schedule "*/10 * * * *" --uri "<API_URL>/internal/fraud-scan" --http-method POST \
  --message-body "{}" \
  --headers "X-Internal-Token=$(gcloud secrets versions access latest --secret=internal-token)"
```

## Other ops items (from the security sweep)
- **Firestore TTL:** enable a TTL policy on the `cache` collection's `expireAt` field
  (Firestore console → TTL) so birth-derived cache rows auto-purge (`CACHE_TTL_DAYS`, default 90).
- **Global spend breaker:** set `DAILY_GLOBAL_TOKEN_BREAKER` (the startup log warns if unset).
- **Consent:** the web captures consent (version `CONSENT_VERSION`) before the first cast and
  records it server-side (`POST /v1/consent`, surfaced in `/v1/me`). Bump the version to force re-consent.
