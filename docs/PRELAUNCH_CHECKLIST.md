# Pre-launch checklist — 8-point review results

**Date:** 2026-06-25. Verdicts against the customer-facing readiness checklist.
Stack: FastAPI (Cloud Run) + React/Vite (Firebase Hosting) + Firestore + Firebase Auth +
Vertex/Gemini + **Razorpay** (not Stripe). Payments handle INR.

| # | Check | Verdict | Notes |
|---|-------|---------|-------|
| 1 | **API rate limits + row-level privacy** (no other users' data in responses) | ✅ Pass | Shared Firestore per-minute limiter + durable daily cap. `/v1/me`, export, etc. return only the caller's own data; deny-by-default Firestore rules; `uid` always from the verified token. No user-table leakage in responses. |
| 2 | **Ownership enforcement** (user B can't open user A's data) | ✅ Pass | SPA has **no per-user/shareable data URLs** — all data is fetched via authenticated API with the caller's own token. The id routes that exist (`/v1/reading/{job_id}`, `/v1/refunds`) verify ownership (404 on mismatch). Pasting one user's session/URL into another gets only the second user's data. |
| 3 | **Payment refunds/cancellations revoke access** | ✅ **Fixed** | Refund (full) already downgraded to free. **Gap fixed:** the webhook now also handles `subscription.cancelled/completed/halted` → downgrade to free, so a **failed renewal / cancellation no longer keeps premium** (previously they did, and even kept the free monthly credit refresh). HMAC + idempotency throughout. |
| 4 | **Error handling / offline** (no white screen / infinite spinner) | ✅ **Fixed** | Busy states always reset in `finally` (no infinite spinner). **Added:** a React **ErrorBoundary** (render crash → recovery screen instead of white page) and **offline-aware API errors** ("You appear to be offline…" instead of raw "Failed to fetch"). |
| 5 | **Secret / credential audit** | ✅ Pass (+ action) | No hardcoded prod secrets; engine + `.env` gitignored & untracked; only the public Firebase web key ships client-side. The **critical dev-key bypass** (public-repo `*_dev_key` seeded into Firestore via unset `APP_ENV`) was found & fixed last round. **Action for owner:** rotate any secret ever pasted into an external AI chat / tool — those transcripts are outside our control. |
| 6 | **Performance on old phones / weak signal** | ✅ Improved | Bundle ~114 KB gzip (fine). The orrery shipped **6.6 MB of textures**; it already respected `prefers-reduced-motion`. **Added:** `OrreryBg` now **skips the WebGL orrery entirely on Save-Data, slow (2g) connections, or ≤1 GB-RAM devices**, so mid-range Androids on weak signal load fast. |
| 7 | **Duplicate workflows / double notifications** | ✅ Pass (N/A) | The app sends **no user-facing emails** (no welcome/onboarding/notification workflows) — only a single admin metrics-digest cron. Firebase owns auth emails. No duplicate triggers exist. |
| 8 | **Admin route lockdown** | ✅ Pass | Every `/admin/*` + `/internal/*` route is `require_admin`/token-gated, fail-closed on weak secrets, constant-time compare. The web Admin tab only appears if `GET /admin/ping` (server-gated by an `admin:true` Firebase claim) succeeds. A regular user typing the admin path gets 401/403; the lazy admin chunk does nothing without the claim. |

## Related deeper audits (already done this project)
- IDOR/BOLA, SSTI, ReDoS, LPDoS, NoSQL injection, replay, clipboard → `SECURITY_AUDIT_VULN_CLASSES.md`,
  `SECURITY_AUDIT_RACE_INJECTION_IDOR.md`.
- DPDP/GDPR compliance → `COMPLIANCE_DPDP.md` and `legal/`.

## Owner to-dos (not code)
1. **Rotate** any API key / DB password / service-role secret ever pasted into an AI chat or other
   third-party tool (item #5).
2. Review the now-active `PROD READINESS:` startup warnings in Cloud Run logs and set any flagged
   secrets (`ADMIN_API_KEY`, `INTERNAL_TOKEN`, `API_KEY_PEPPER`) off dev defaults.
3. Manually test a real refund + a real cancellation in the Razorpay dashboard once payments are live,
   and confirm the user drops to free (the webhook path is covered by tests, but verify the live wiring).
4. Email-enumeration on signup is handled by **Firebase Auth** — enable "Email enumeration protection"
   in the Firebase console (it's a console setting, not app code).
