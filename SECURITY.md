# Security & Compliance, Nakshatra

This document records the technical security controls in the codebase, the status of
the security audit, the compliance posture, and the **manual/operational steps the
owner must complete** before handling real customer payments and data. It is a living
document, not a certification.

> **No absolute guarantees.** Security is continuous. This records the controls in
> place and known gaps, not a claim that the system is unbreachable.

## Reporting a vulnerability
Email the maintainer privately; do not open a public issue. Include steps to reproduce.

## Technical controls in place
- **Auth:** Firebase ID-token verification (Admin SDK), optional `check_revoked`, optional
  `require_email_verified`. B2B keys via `X-API-Key`. Both fail closed to 401.
- **Authorization:** per-user ownership checks (async jobs are owner-scoped, no IDOR);
  tier-gated endpoints; admin/internal endpoints **disabled unless a strong secret is set**
  (placeholders rejected in every environment; constant-time comparison).
- **Money path:** atomic credit debits (grant→topup, clamp ≥0); append-only ledger;
  Razorpay webhook with HMAC-SHA256 signature verification, idempotent crediting
  (no double-credit across `payment.captured`/`order.paid`; subscription grants once
  per charge), and `503` when the webhook secret is unset. Unit-tested.
- **Cost controls:** per-turn output cap, per-user daily token ceiling, **global daily
  spend breaker**, bounded chat input (message + history length caps).
- **Data protection:** server-side metering only (no client token counts); GDPR
  endpoints `GET /v1/me/export` and `DELETE /v1/me` (purges Firestore data + API keys +
  best-effort Firebase identity); configurable chat retention (`expireAt` + TTL policy)
  and opt-out (`PERSIST_CHAT`); B2B API keys stored **hashed** at rest; PII kept out of logs.
- **Datastore:** Firestore deny-by-default rules (`web/firestore.rules`), clients read
  their own data only, never write balances/ledger.
- **Transport/at-rest:** HTTPS (Cloud Run + Hosting); Firestore encrypted at rest.
- **Supply chain:** Dependabot (`.github/dependabot.yml`); committed `package-lock.json`.

## Audit
A multi-agent adversarial audit confirmed 29 findings (1 critical, 5 high, rest medium/low),
each independently verified. Critical/high and quick wins are remediated; the remaining
items (distributed per-minute rate limiting, chat reserve-then-debit concurrency, chat
output grounding validation, fully-pinned/hashed Python lockfile, cache TTL) are tracked
for the next hardening pass.

## Compliance posture (honest)
| Regime | Status |
|---|---|
| **PCI-DSS** | **SAQ-A** - Razorpay hosted checkout; the app never sees/stores card data. Keep it that way. |
| **GDPR** | Technical rights implemented (export/erasure, retention, minimization). **Organizational work outstanding:** privacy notice, lawful basis/consent, DPAs with Google Cloud + Razorpay, breach-notification process, and a DPIA (profiling + birth data). |
| **ISO 27001** | An audited ISMS (policies, risk register, supplier/incident/BCP management). These controls *support* Annex A; certification is a company program. |
| **SOX** | **Not applicable** (governs public-company financial reporting). |

## Required manual / operational steps before launch
1. **Verify & deploy Firestore rules now:** `firebase deploy --only firestore:rules`, then
   confirm in the console (Firestore → Rules) the live ruleset is deny-by-default - **a DB
   created in test mode is world-readable/writable.**
2. **Secrets in Secret Manager:** set strong `ADMIN_API_KEY`, `INTERNAL_TOKEN`,
   `RAZORPAY_WEBHOOK_SECRET`, `API_KEY_PEPPER` (the deploy scripts wire `--update-secrets`).
3. **Deploy via `api/deploy/gcp_deploy.sh`** (sets `APP_ENV=prod`, `CORS_ORIGINS`,
   `DEFAULT_USER_TIER=free`, `VERIFY_TOKEN_REVOCATION`, `REQUIRE_EMAIL_VERIFIED`), not the
   bare `gcloud run deploy` command.
4. **Enable a Firestore TTL policy** on `users/*/chats/*/messages.expireAt` if using chat
   retention; set `CHAT_RETENTION_DAYS`.
5. **Edge protection:** put Cloud Armor (per-IP rate limiting / WAF) in front of Cloud Run;
   set a non-zero `DAILY_GLOBAL_TOKEN_BREAKER`.
6. **Org/legal:** publish a privacy policy + terms; sign DPAs; define retention + incident
   response; appoint a data-protection contact.
