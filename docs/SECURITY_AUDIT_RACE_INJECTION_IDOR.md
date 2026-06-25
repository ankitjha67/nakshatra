# Security audit — race conditions, prompt injection, API fuzzing / data disclosure

**Date:** 2026-06-25 · **Scope:** redeem/beta claiming, all LLM chat paths, every API route.

## 🔴 CRITICAL incident found & remediated: dev-key auth bypass (live)
`APP_ENV` was **unset** on the production Cloud Run service, so `is_prod` was `False`. Two live,
exploitable consequences:
1. **`get_store()` seeded dev API keys into the persistent Firestore store** (`free/basic/pro/ent_dev_key`).
   Those key strings are **in this public repo**, so `curl -H "X-API-Key: ent_dev_key" /v1/me` returned
   **200 as `u_ent`, tier `enterprise`** — a trivial, free enterprise/pro auth bypass for anyone.
2. **`/mock/razorpay/checkout`** (dev tooling) was reachable and accepts a `uid` override → any signed-in
   user could grant **anyone** a paid tier + credits for free.

**Remediation (done):**
- Set `APP_ENV=prod` on the live service (rev `jyotish-api-00056-kv2`) → stops dev-key seeding, 404s the
  mock routes, and activates the prod startup warnings.
- **Deleted the already-seeded dev keys + dummy users** from Firestore (the flag stops re-seeding but
  doesn't remove what past boots wrote). Verified: `ent_dev_key`/`pro_dev_key` now **401**.
- **Root-cause code fix:** `get_store()` no longer seeds dev keys into the Firestore (persistent) store
  *at all* — dev keys belong only to the ephemeral `MemoryStore` (local dev), where they vanish on
  restart. So a future `APP_ENV` misconfiguration can never persist an exploitable key again.

## ✅ Race conditions — redeem codes & beta claiming: SAFE
The user-facing claim path is `/v1/redeem` (beta = `source="beta"`). `FirestoreStore.code_redeem`
wraps read→check→update in `@fs.transactional`, and `_code_redeem_check` validates **both**
`uid in redeemed_by` (same-user double-redeem) **and** `uses >= max_uses` (different users racing a
single-use code) *inside* the transaction. Firestore optimistic concurrency makes the second of two
racing redemptions retry and then fail. Verified:
- Same user, two concurrent redemptions of one code → exactly one succeeds (the other gets
  "already redeemed"); no double tier/credit grant.
- Two users, one single-use code → exactly one wins (`uses >= max_uses`).
- The endpoint's `redeemed_codes` pre-check is a harmless fast-path + cross-regeneration backstop; the
  codes-doc transaction is the authoritative guard, so its TOCTOU is non-exploitable.
- Credit grants/debits (`_credit_apply`) are transactional and idempotent (grant **sets** the balance
  absolutely), so racing balance reads after an upgrade can't double-grant.
*(MemoryStore's non-transactional variant is dev-only/single-threaded — not a prod path.)*

## ✅ Prompt injection — chat & all LLM paths: WELL-DEFENDED
The anti-slop architecture doubles as the injection defense:
- **User text reaches the LLM as a JSON data value, never concatenated into the prompt** (chat
  `_chat_payload` json-dumps message+history with an "untrusted data" note; the system prompt is a
  separate role). Renderer/prashna/BTR/match send only computed findings/numbers — no user free-text.
- **Tier data is filtered OUT of context before the call** (`filter_findings`/`chart_facts` by tier),
  so a free/basic user cannot injection-extract pro-tier findings that aren't present.
- **Citations are validated against server-side finding codes**; sections not in the tier are dropped.
- **Injected turns are never persisted** to history, so they can't poison later answers; history is
  loaded server-authoritatively (client history ignored for grounding).
- The regex layers (`_INJECTION_RE`, `_MALICIOUS_RE`, `_SECRET_RE`) are evadable (translation/leet/
  encoding) but **non-load-bearing** telemetry/defense-in-depth — a bypass only undercounts fraud
  flags; no secret or other-user data is in the model's context to leak.
No high/medium exploitable injection issue.

## API fuzzing & customer-data disclosure (IDOR) — findings
IDOR ownership checks are present on every user-facing id route (`/v1/reading/{job_id}` owner-check,
`/v1/refunds` uid-check, `/v1/me/payments` scoped, chat history uid-scoped). Every `/admin/*` and
`/internal/*` route is guarded (fail-closed on weak secrets, constant-time compare). Real fixes made:
- **R4 (info disclosure) — fixed:** async-job failures returned raw `str(exc)` to the job owner
  (Firestore paths / project ids). Now a generic message; the real error stays in logs only.
- **R5/R6 (fuzzing) — fixed:** `PrashnaRequest.tz` and `.category` were unbounded (flow into the
  engine). Added `max_length`.
- **R2 (privacy/fuzzing) — fixed:** `NomineeIn.email` accepted any string; added format validation.
- **Accepted/admin-scoped (not fixed here):** admin uid-targeted mutators can create ghost records
  (admin-gated); `admin_economics` numeric params unbounded (admin-gated). Low priority.

## Follow-up
- The prod startup warnings now fire (`APP_ENV=prod`) — review them and set any flagged secrets.
- Consider deleting the `/mock/*` routes entirely before GA (they're dev-only and prod-gated, but
  least-privilege says remove them from the production image).
