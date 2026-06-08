I'll synthesize the verified findings into a prioritized report. Note that the verdicts re-rated several findings from their original severity, so I'll group by the **confirmed** (verdict) severity, which represents the verified assessment.

# Nakshatra Security & Compliance Audit â€” Prioritized Report

This report groups findings by their **verified severity** (the adversarially-confirmed verdict rating), which in several cases differs from the originally-reported severity. Where a finding was downgraded, the original rating is noted for traceability.

---

## CRITICAL

*No findings remain critical after verification.* The one item originally filed as critical â€” async readings bypassing the credit ledger â€” was confirmed as a real metering bypass but re-rated **HIGH**, because exploitation is bounded to already-paying Pro/Enterprise accounts and the worst case is daily-call-limited cost amplification, not unbounded spend or data exposure. It appears under HIGH below.

---

## HIGH

### 1. Refund idempotency keyed on refund id, not payment â€” repeated/partial refunds claw back paid tokens
- **File:** `api/app/payments.py:141-160`
- **Why it matters:** The refund branch dedupes only on `mark_payment_processed(f"refund:{rid}")` (the refund entity id), never checks `rec.get("status")`, and reverses the **full** original token grant plus unconditionally downgrades subscriptions to `free`. Razorpay legitimately emits multiple refund entities per payment (partial refunds, `refund.created` + `refund.processed`, `refund.speed_changed`), each with a distinct `rid` that passes the dedupe. Empirically reproduced: a user who later buys an unrelated top-up has those legitimately-paid tokens clawed back by a second reversal of an already-refunded payment (`credits.refund` clamps at zero but drains `topup_balance` first). A â‚¹1 partial refund reverses the entire monthly grant and downgrades the subscriber. Direct financial harm to paying users via normal Razorpay behavior, no attacker sophistication required. The refund-*request* endpoint (`main.py:835`) already has the exact `status=="refunded"` guard that the webhook branch is missing.
- **Fix:** After looking up `rec`, return early if `rec.get("status") == "refunded"`, and/or add a second idempotency key `mark_payment_processed(f"refunded:{pay_id}")` so a payment can only be reversed once regardless of how many refund entities arrive. For partial refunds, reverse tokens proportional to `refund.entity.amount` (paise) rather than the full grant, and only downgrade tier on a full refund.

### 2. Birth-lock fully bypassed via `/v1/reading/async` â€” one subscription reads unlimited people
- **File:** `api/app/main.py` (`reading_async` lines 407-422)
- **Why it matters:** `enforce_birth_lock` is applied on `/v1/chart` (163), `/v1/anchor` (179), `/v1/reading` (191), `/v1/chat` (245), and `/v1/btr` (378), but **not** on the async reading endpoint, nor in `_run_job` (395-404) or the worker callback `/internal/run-reading` (441-449) â€” enforcement lives purely at the HTTP layer, so the async path has zero fallback. `birth_lock_enabled` defaults to `True`, so the bypass is live out of the box. Since `/v1/reading/async` returns the same full reading as the locked sync path and is available to Pro/Enterprise, a paying user can request readings for arbitrarily many natives, nullifying the one-native-per-account commercial lock the docstring at line 142 explicitly claims to close.
- **Fix:** Call `enforce_birth_lock(p.user_id, birth)` inside `reading_async` before enqueuing (mirror `/v1/reading:191`) so the `409` reaches the caller synchronously. Add a regression test that a second async reading for a different date/place returns `409`.

### 3. Async readings bypass the credit ledger â€” no balance check, no debit (uncapped paid-LLM spend)
- **File:** `api/app/main.py` (`reading_async` 407-422, `_run_job` 395-404)
- **Why it matters:** *(Originally filed twice, once as high and once as critical; merged here, verdict HIGH.)* The sync `/v1/reading` both pre-checks `credit_balance(...)["available"] <= 0` (line 194) and debits via `store.credit_debit(...)` (200-201). The async path does **neither**: no balance pre-check before enqueue, and `_run_job` calls `get_reading()` (full engine+rules+LLM render) and `store.record()` but never `credit_debit`. `store.record()` only bumps usage counters and the global breaker â€” it never touches the per-user ledger. `credit_debit` is invoked *only* at `main.py:201` and `:259`. The Cloud Tasks production worker path (`/internal/run-reading`) is equally unmetered. A Pro/Enterprise user can generate full Maha-Kundali readings with zero credits remaining and never consume their metered allowance â€” bounded only by the per-day **call** count (500â€“10,000), far exceeding the monthly token grant. `enforce_quota` is call-count limiting (not tokens) and the global breaker is platform-wide (and off by default), so the per-user allowance is genuinely unprotected.
- **Fix:** In `reading_async`, replicate the sync out-of-credits pre-check before enqueuing. In `_run_job`, after `get_reading`, debit `cost = resp.meta.tokens_in + resp.meta.tokens_out` (when nonzero) via `store.credit_debit(...)` for cache-miss cost. Thread `uid` through `_TaskPayload`/`_run_job` (it currently carries the API key/tier, and for Firebase principals `p.key != p.user_id`) so the resolved Tier and uid reach `credit_debit`.

### 4. Reading/chart cache retains birth-derived personal data and is never deleted on erasure
- **File:** `api/app/billing.py` (`FirestoreStore.delete_user` 754-767, `cache_put` 787-798); `api/app/pipeline.py` (`get_chart` 34, `get_reading` 77) â€” *verdict re-rated to MEDIUM*
- **Why it matters:** `get_chart`/`get_reading` persist the full computed chart and rendered reading â€” exact planetary placements, interpretive prose, and the engine `input`/`numerology` blocks (which can include the person's name) â€” to the Firestore `cache` collection. `delete_user` removes only the user doc, ledger/chats subcollections, and api_keys; no cache-deletion code exists anywhere, and the cache has no TTL. After `DELETE /v1/me` (right to erasure), the personal reading persists indefinitely â€” a GDPR Art. 17 / privacy-policy-accuracy gap. *(Re-rated medium because cache docs are keyed by SHA-256 of `chart_hash`, carry no `user_id`, and sit behind deny-by-default Firestore rules â€” the residual data is orphaned and not directly enumerable or attributable without independent knowledge of the exact birth inputs.)*
- **Fix:** On `delete_user`, also delete cache entries for the user. Either recompute `chart_hash` from the stored `birth_lock` (it has name/date/time/tz/lat/lon; ayanamsa/house_system default deterministically) and delete the `chart:*`/`read:*` docs, or maintain a `uid -> cache doc id` reverse index at `cache_put` time. Independently, add a Firestore TTL (`expireAt`) so cache docs age out even for users who never explicitly delete.

---

## MEDIUM

### 5. Daily per-user token ceiling enforced only for chat, not for readings/prashna/btr
- **File:** `api/app/main.py` â€” *originally high, verdict MEDIUM*
- **Why it matters:** `daily_token_ceiling` (default 200,000, the "independent-of-balance" abuse ceiling) is enforced only in `/v1/chat` (line 239). `/v1/reading`, `/v1/prashna`, and `/v1/btr` never compare `daily_used` against it. Worse, `/v1/prashna` and `/v1/btr` call `render_reading()` (a real LLM render) but **never debit credits** (`credit_debit` appears only at `main.py:201` and `:259`) â€” they are un-metered LLM spend bounded solely by per-day call count. *(Re-rated medium because `/v1/reading` does debit and gate on `available<=0`, so the paid allowance itself can't be exceeded via readings â€” the readings concern is a burn-rate issue within an already-paid balance. The genuinely un-metered surface is prashna/btr, and its abuse is call-count-bounded, not unbounded.)*
- **Fix:** Extract the chat daily-ceiling check into a shared helper and call it in `/v1/reading`, `/v1/prashna`, `/v1/btr` before invoking the LLM. Separately decide whether prashna/btr should debit credits â€” they currently render full LLM output for free â€” and gate/charge them consistently.

### 6. Global daily token breaker (financial-DoS backstop) disabled by default and not warned about
- **File:** `api/app/config.py` (line 60) â€” *originally high, verdict MEDIUM*
- **Why it matters:** `daily_global_token_breaker` defaults to `0`, and `enforce_global_breaker` (`billing.py:1114-1119`) is a no-op when the cap is falsy (`if cap and ...`). So the platform-wide spend circuit-breaker â€” the only backstop against a coordinated/credential-stuffed cost-amplification attack spanning many accounts (total = per-user ceiling Ã— number of accounts, with no aggregate cap) â€” is OFF unless explicitly set. `startup_warnings()` warns about weak admin keys, open CORS, mock LLM, etc., but emits nothing for this, so the gap ships silently. *(Re-rated medium because per-account spend is still bounded by the default-on per-user daily ceiling, rate/call limits, and credit ledger; what's missing is the cross-account aggregate ceiling â€” a secondary defense-in-depth backstop.)*
- **Fix:** Set a sane non-zero default for `daily_global_token_breaker`, and/or add a `startup_warnings()` warning when `is_prod and daily_global_token_breaker == 0`.

---

## LOW

### 7. Email-verification and token-revocation checks default OFF with no prod-readiness warning
- **File:** `api/app/config.py` (lines 45-46) â€” *originally medium, verdict LOW*
- **Why it matters:** `verify_token_revocation` and `require_email_verified` both default `False`. With the defaults, a Firebase ID token stays valid for its ~1h lifetime after sign-out/disable/revocation, and unverified-email accounts get full metered LLM/credit access. `startup_warnings()` warns about ADMIN_API_KEY/INTERNAL_TOKEN/CORS but says nothing about these two, and the documented prod env vars don't include them, so default-False is the likely live posture. *(Low: the flags are wired correctly and work when enabled; revoked-token reuse is bounded to <=1h, a standard Firebase tradeoff; and abuse is capped by the per-user daily ceiling, credit ledger, birth-lock, and ban/anomaly enforcement on the same path â€” "unbounded spend" is not achievable.)*
- **Fix:** In `startup_warnings()`, warn when `is_prod` and either flag is `False`. Consider defaulting `verify_token_revocation=True` for prod; at minimum gate credit-debiting endpoints behind email verification.

### 8. Subscription recurring charges silently skipped when `payment.id` is absent
- **File:** `api/app/payments.py:171-184` â€” *originally medium, verdict LOW*
- **Why it matters:** `subscription.charged` dedupes on `charge_id = payment.get("id") or sub.get("id")`. If a charged event lacks `payment.entity.id`, the fallback is the subscription id â€” identical across every billing cycle. After cycle 1 records `subgrant:{sub_id}`, every later renewal is treated as a duplicate and skipped, so a paying customer is never re-granted monthly tokens nor re-applied tier. The test helper `_sub` already builds payloads with no payment entity, confirming the fallback path is live. *(Low: in normal Razorpay traffic `subscription.charged` always includes `payment.entity.id`, so triggering needs a malformed payload; harm is under-entitlement, not double-credit or leak.)*
- **Fix:** Require a real per-charge id: prefer `payment.entity.id`, else the invoice id or a composite of `sub.id` + billing period. Never use the bare subscription id. If no per-charge id can be derived, log and return `ignored` rather than consuming the per-subscription dedupe slot.

### 9. X-Forwarded-For trusted blindly â€” clients can spoof the abuse-correlation IP
- **File:** `api/app/auth.py` (`_client_ip` 82-87) â€” *originally medium, verdict LOW*
- **Why it matters:** `_client_ip()` returns `request.headers.get("x-forwarded-for").split(",")[0].strip()` with no proxy-trust validation. On Cloud Run the trustworthy client IP is appended at the **right** of XFF, so taking `[0]` reads the left-most, fully client-controlled entry. The IP is persisted via `record_activity()` and feeds the "N accounts share IP" admin heuristic (`main.py:977-979`) and the `last_ip` shown in `/admin/users`. A caller can spoof XFF to evade the shared-IP heuristic or pollute their own recorded IP. *(Low: the IP is advisory only â€” bans key on `uid`, quota is per-Principal; it's never used for any authorization/ban/rate-limit decision. The cross-user "framing" sub-claim is overstated since `record_activity` is keyed to the caller's own authenticated uid.)*
- **Fix:** Read the right-most untrusted hop appended by the load balancer (or the platform-provided client IP), and ignore XFF when the request didn't arrive via the expected proxy. At minimum, document that `last_ip` is advisory and never use it for authorization.

### 10. Client IP addresses retained indefinitely with no expiry, not purged on deletion, not exported
- **File:** `api/app/billing.py` (`FirestoreStore.record_activity`) â€” *originally medium, verdict LOW; finding's specifics partly inaccurate*
- **Why it matters:** `FirestoreStore.record_activity` stores caller IPs via `ArrayUnion([ip])` with **no cap** (the in-memory store caps to 10; Firestore grows unbounded). IP is personal data under GDPR/DPDP, with no TTL/rotation/auto-purge. **Corrections to the original finding:** the IP is written to a separate top-level `activity/{uid}` collection (not the user doc); `export_user` reads only user/ledger/chats, so IP is **not** exported (a right-of-access gap, the opposite of the original claim); and `delete_user` never touches `activity/{uid}`, so IP data **survives account deletion** (a right-to-erasure gap, worse than claimed). The referenced `PRIVACY_POLICY.md` sections/line numbers do not exist in the repo. *(Low: a data-retention/erasure-coverage defect requiring existing DB access or a compliance audit to manifest harm, not a directly exploitable vulnerability.)*
- **Fix:** Cap the Firestore IP history (ring buffer with timestamps) to match the in-memory path, add explicit retention/auto-purge for IP data, include `activity/{uid}` in `delete_user` and `export_user`, and state the IP retention period in the privacy policy.

### 11. No consent capture in the web app for processing sensitive birth data
- **File:** `web/src/` (`SignIn.jsx`, `BirthForm.jsx`, `App.jsx`) â€” *originally medium, verdict LOW*
- **Why it matters:** A repo-wide search of `web/src` finds zero references to consent/privacy/terms/agree. Users enter name, date, time, and place of birth (the project's own policy calls this "sensitive") with no consent gate, privacy-notice link, or terms acceptance at signup or birth-detail entry. The legal docs exist only as templates under `docs/legal/` and are never surfaced in the hosted app. India's DPDP Act 2023 requires notice + consent. *(Low: a regulatory/legal-compliance gap, not a technically exploitable vulnerability; also clearly pre-launch state â€” the policy is still a placeholder template and CLAUDE.md lists other launch-blocking items pending.)*
- **Fix:** Add a consent step (with links to privacy policy + terms) at account creation and/or first birth-detail submission, record consent (version + timestamp) server-side, and wire the legal docs into the hosted UI. Must be addressed before processing real users' birth data under DPDP/GDPR.

### 12. Dev mock refund endpoint can re-trigger reversal on an already-refunded payment
- **File:** `api/app/main.py:1151-1155, 850-855` â€” *verdict LOW (as filed)*
- **Why it matters:** `/mock/razorpay/refund` (admin-gated, non-prod) and `_process_refund` mint a fresh `rid` per call; since refund idempotency keys only on `rid` (the root cause of finding #1), repeated calls for the same `payment_id` reverse tokens each time. *(Low: non-prod-only â€” `is_prod` 404 gate is real â€” and admin-gated; the effect is token reversal that clamps at 0, so no value can be minted. The production refund path `admin_approve_refund` is independently protected by the refund-request status check.)*
- **Fix:** Covered automatically once the per-payment refund guard from finding #1 lands; additionally have `_process_refund` check `get_payment(payment_id).status == 'refunded'` and refuse before firing another reversal.

### 13. `/v1/chart` over-exposes interpretive engine blocks to all tiers (deny-list gating)
- **File:** `api/app/gating.py` â€” *verdict LOW (as filed)*
- **Why it matters:** `filter_chart_for_features` is a deny-list: it strips only `vargas`, `dasha_systems`, and seven `_FULL_TABLE_BLOCKS`. Every other documented engine block â€” `ashtakavarga`, `shadbala`, `arudha_padas`, `sahams`, `yogas`, `upagrahas`, `vedic_aspects`, `fixed_stars`, etc. â€” passes through unfiltered to free/basic users over `/v1/chart`. *(Low: the current frontend renders none of these, so no presently-sold paid table leaks and there's no PII/secret/money exposure. The risk is future-tense â€” these interpretive outputs are likely Pro monetization candidates, and default-open means any later gating is a no-op and the data is already scrapeable.)*
- **Fix:** Switch to a capability-keyed **allow-list** (free: `chart.planets`/`asc`/`cusps`/`panchang`; `tables_basic` adds `dasha_systems[vimshottari]`; `tables_full` adds the rest) so newly added engine blocks are locked by default rather than exposed by default.

### 14. Per-minute rate limit is per-instance in-memory; multiplies under autoscaling
- **File:** `api/app/billing.py` (`hit_rate`) â€” *originally medium, verdict LOW*
- **Why it matters:** Both `MemoryStore.hit_rate` and `FirestoreStore.hit_rate` keep the sliding-window burst counter in a process-local dict. On Cloud Run with N instances, the effective per-minute limit a key experiences is N Ã— `tier.per_minute`. The daily call limit *is* durable (Firestore Increment), but the front-line burst throttle (covering `/v1/redeem`, `/v1/checkout`, and LLM endpoints) is not shared. *(Low: the security-load-bearing backstops hold â€” the durable daily ceiling bounds total calls regardless of instance count, redeem codes are high-entropy salted-SHA-256 so burst rate doesn't aid brute-force, the global token breaker backstops cost amplification, and limits key on the authenticated principal. Already documented as a known tradeoff.)*
- **Fix:** Move per-minute limiting to a shared atomic counter (Firestore `Increment` on a `usage/{key}__{minute}` doc, or Redis/Memorystore). At minimum, cap Cloud Run max-instances and document the multiplier so `tier.per_minute` is set with the effective limit understood.

---

## Overall security posture

Nakshatra's anti-slop core (deterministic rules â†’ constrained LLM) and its identity boundary are fundamentally sound â€” every user endpoint flows through Firebase token verification, bans key on `uid`, and Firestore sits behind deny-by-default rules â€” and verification dissolved the single "critical" claim down to a bounded high. The concentration of real risk is unambiguously on the **money and metering path**: the refund logic double-reverses paid tokens under normal Razorpay partial-refund behavior (#1), and the **asynchronous reading endpoint is a systematic blind spot** that independently bypasses both the birth-lock commercial control (#2) and the credit ledger (#3) because enforcement was implemented per-endpoint at the HTTP layer rather than in the shared pipeline â€” a structural pattern worth correcting by centralizing birth-lock, balance checks, and debits in `get_reading`/`_run_job` so no future surface can skip them. A secondary theme is **insecure-by-default hardening flags shipping silently** (token revocation, email verification, and the global spend breaker all default off with no `startup_warnings()` coverage), which is cheap to fix and high-leverage. The remaining items are genuine but lower-blast-radius privacy/compliance and defense-in-depth gaps (cache/IP retention not honoring erasure, missing DPDP consent capture, deny-list chart gating) that are appropriate to resolve as part of pre-launch readiness rather than emergency patches. Net: no active data-exfiltration or auth-bypass exposure, but the payment/refund and async-metering defects are exploitable through ordinary product use by paying customers and should block launch until fixed, with all changes to refund, ledger, and token-verification code reviewed by the owner per the repo's money-path guardrails.
---

## Remediation status (post-audit fixes shipped)

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | Refund idempotency keyed on refund id (multi/partial refunds claw back tokens) | HIGH | **Fixed** — payment-level guard (status==refunded), proportional reversal, downgrade only on full refund (payments.py); regression tests added |
| 2 | Birth-lock bypassed via /v1/reading/async | HIGH | **Fixed** — enforce_birth_lock now runs in reading_async before enqueue |
| 3 | Async readings bypass the credit ledger (no balance check / no debit) | HIGH | **Fixed** — async pre-checks balance + debits in _run_job; uid threaded through Cloud Tasks payload |
| 4 | Reading/chart cache retains birth-derived PII with no TTL | MEDIUM | **Mitigated** — cache rows now carry an expireAt (cache_ttl_days, default 90); enable a Firestore TTL policy on cache.expireAt. Per-user immediate purge tracked as follow-up (cache is hash-keyed, no uid, behind deny-by-default rules) |
| 5 | Daily token ceiling only enforced for chat; prashna/btr unmetered | MEDIUM | **Fixed** — _meter_precheck (credits + daily ceiling) and _meter_debit applied to reading, prashna, and btr |
| 6 | Global daily token breaker off by default, no warning | MEDIUM | **Fixed** — startup warning added (set DAILY_GLOBAL_TOKEN_BREAKER in prod) |
| 7 | /v1/chart over-exposes interpretive engine blocks to all tiers | LOW | **Fixed** — chart gating switched to an allow-list (only tier-unlocked blocks returned) |
| 8 | Subscription renewals skipped when payment.id absent | LOW | **Fixed** — idempotency key prefers invoice_id (unique per renewal) |
| 9 | Email-verification / token-revocation default off, no warning | LOW | **Fixed** — startup warning for VERIFY_TOKEN_REVOCATION |
| 10 | X-Forwarded-For trusted for IP correlation | LOW | **Accepted** — correlation-only (not auth); robust fix needs Cloud Armor / trusted-proxy config |
| 11 | Client IP retained indefinitely on profile | LOW | **Accepted/noted** — abuse-prevention legitimate interest; add rotation/retention at scale |
| 12 | No web consent capture for sensitive birth data | LOW | **Follow-up** — add an explicit consent checkbox at sign-up/first cast (tracked) |
| 13 | Per-minute rate limit is per-instance (multiplies under autoscale) | LOW | **Accepted/noted** — needs a shared limiter (Redis/Firestore) for strict global limits |
| 14 | Dev mock refund can re-trigger on refunded payment | LOW | **Fixed transitively** — webhook now rejects refund of an already-refunded payment |

Audit run: multi-agent workflow, 8 dimensions, adversarial verification, 33 agents, 15/23 findings confirmed.
