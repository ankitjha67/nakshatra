# Security audit — SSTI / ReDoS / LPDoS / Secret leak / NoSQL-SQLi / Clipboard / Replay

**Date:** 2026-06-25 · **Scope:** entire repo (`api/`, `web/`). **Result: no critical or high
exploitable vulnerabilities.** The money path and input handling are notably defensive. Real,
lower-severity findings were remediated or documented below.

## Verdict by class
| Class | Verdict | Why |
|---|---|---|
| **SSTI / code injection** | ✅ Clean | No template engine; no `eval/exec/compile/pickle`; no `.format()` on user-controlled templates. LLM prompts are constant literals; user data is `json.dumps`'d into the model `contents`, never used as a format string. |
| **ReDoS** | ✅ Clean | Every regex (`fraud._MALICIOUS_RE`, `llm._INJECTION_RE/_EXFIL/_SECRET`, `models` date/time, `gating`) is linear — benchmarked < 5 ms on 6 KB–200 KB adversarial input. Attacker input is length-bounded *before* the regex runs (chat ≤ 6000, name ≤ 80, place ≤ 120). |
| **NoSQL / SQL injection** | ✅ Clean | Firestore only (no SQL backend). `uid` always from the verified Firebase token; user-derived doc IDs (code, cache key, API key) are SHA-256 hashed; `chat_id` is regex-validated `^[A-Za-z0-9_-]{1,64}$` and nested under the token `uid`; `.where()` uses equality on token/admin values; IDOR ownership checks present on `/v1/reading/{job_id}` and `/v1/refunds`. |
| **Clipboard attack** | ✅ N/A | No clipboard API surface anywhere in `web/` (no `navigator.clipboard`, `execCommand`, paste handlers). Nothing reads/writes the clipboard. |
| **Replay attack** | ✅ Strong | Razorpay webhook: HMAC-SHA256 (constant-time) + **atomic Firestore-transaction idempotency** (`mark_payment_processed`) → replays return `duplicate`, no double-grant. Redeem codes single-use via atomic transaction (no TOCTOU). Credit debits atomic. `VERIFY_TOKEN_REVOCATION` now **on** in prod. |
| **LPDoS / L7 DoS** | 🟡 Hardened | See findings below. |
| **Secret-key leak** | ✅ Strong | No hardcoded prod secrets (all empty defaults, weak values rejected); secrets never returned in responses or logged; engine + `.env` gitignored & untracked; only the public Firebase web key ships in the client. One dev-only string removed (below). |

## Findings remediated this round
1. **No request body-size limit (MEDIUM).** `await request.body()` on the **pre-auth** payments webhook (and all endpoints) read unbounded bodies into memory. **Fixed:** `_limit_body_size` middleware rejects `Content-Length > max_request_bytes` (default **1 MB**) with 413, before the handler/body read. (`api/app/main.py`, `config.max_request_bytes`.)
2. **Dev admin string in committed client source (LOW, no prod impact).** `web/src/lib/api.js` hardcoded `PREVIEW_ADMIN_KEY = "test-admin-secret"` (only used in DEV-without-Firebase). **Fixed:** now read from `import.meta.env.VITE_PREVIEW_ADMIN_KEY` (nothing committed).
3. **Global token breaker OFF (LOW-MED, config).** `DAILY_GLOBAL_TOKEN_BREAKER=0`. **Fixed (ops):** set to a platform-wide daily backstop on the live service (tune via `docs/COST_MODEL.md`).

## Findings fixed in a follow-up
- **Per-minute rate limit was per-instance** (`billing.hit_rate`) — multi-instance autoscaling
  multiplied the burst. **Fixed:** `FirestoreStore.hit_rate` is now a **shared atomic fixed-window
  counter** in Firestore (one doc per key+minute, transactional increment, TTL-cleaned, fail-open on
  error). The per-minute ceiling is now enforced across all Cloud Run instances; the durable daily cap
  remains. Edge rate limiting (Cloud Armor) is still worthwhile as a pre-app layer but no longer
  required for correctness.

## Findings accepted / documented (not code-fixable here)
- **Chunked requests without Content-Length** bypass the body-size header check; bounded by the Cloud Run platform cap (≈32 MiB). Acceptable.
- **Admin fraud scan is O(users)** unpaginated — admin-gated, internal concern only.
- **Free `/v1/chart` etc. run the CPU-heavy engine uncredited** — bounded by the daily quota (free = 5/day).

## Standing prod config (verified live)
`VERIFY_TOKEN_REVOCATION=true`, `CORS_ORIGINS` locked to the two Firebase origins,
`max_request_bytes=1MB`, `DAILY_GLOBAL_TOKEN_BREAKER` set. Per-user daily token ceiling and atomic
credit ledger remain the primary cost controls.
