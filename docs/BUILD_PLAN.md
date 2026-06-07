# docs/BUILD_PLAN.md — Phased plan for Claude Code

Work top-down. Each phase is a reviewable unit with acceptance criteria. Keep diffs small. After any
rules/renderer/section/tier change, **bump the version stamp** in `api/app/__init__.py`. Read
`CLAUDE.md`, `REPORT_TYPES.md`, `CREDIT_LEDGER.md` before starting.

## Phase 0 — Repo hygiene & run both apps
- Confirm `api/` runs locally (mock engine + MockProvider ok without secrets) and the existing
  `/v1/reading` works against the deployed service.
- Confirm `web/` runs (`npm run dev`) and signs in with Firebase, and the Natal tab renders a reading
  from the live API.
- Verify `.gitignore` excludes the engine, `.env`, secrets, `node_modules`, build dirs. Verify
  `api/.gcloudignore` keeps the engine but drops `../web`, `../docs`, `.git`.
- **Done when:** clean `git status` (no secrets/engine staged); both apps run locally.

## Phase 1 — Frontend tab shell (visual)
- Build the tab bar: **Natal · Maha-Kundali · Yearly · Prashna · Chat · Birth-Time**. Tier-gate tabs:
  locked tabs render a paywall card (read tier from the user doc / `/v1/tiers`).
- Natal & Maha-Kundali tabs reuse one `<BirthForm/>` + `<Reading/>`; both call `/v1/reading` (Maha sends
  `report_type=maha_kundali`, Natal sends `natal` — backend may ignore until Phase 2). Port the city
  picker + section rendering + "Drawn from" footer from the existing single-file app.
- **Done when:** signed-in user can switch tabs; Natal/Maha render real readings; locked tabs show upgrade.

## Phase 2 — `report_type` on the reading flow (backend)
- Add `report_type` to the reading request; add `REPORT_SECTIONS` map; effective sections =
  `REPORT_SECTIONS[report_type] & tier.sections`; include `report_type` in the cache key. Bump renderer
  stamp. Extend `/v1/tiers` to advertise report-type entitlements.
- **Done when:** Natal returns 6 sections, Maha returns up to 16, gated by tier; cache keys differ.

## Phase 3 — Yearly (Varshphal) report type
- Backend: `_yearly(chart, year)` generator (reads vimshottari antardasha/pratyantardasha across the
  year + `double_transit` + `planetary_ingress`) → `yearly` category + section in `SECTION_SPEC`. Add
  `year` to the request for `report_type=yearly`. Bump rules stamp.
- Frontend: Yearly tab = BirthForm + year picker.
- **Done when:** a year produces a grounded, timing-forward reading.

## Phase 4 — Credit ledger (backend) — REVIEW REQUIRED
- Implement the Firestore schema, lazy cycle-reset + daily-reset, transactional debit helper, and
  ledger writes per `CREDIT_LEDGER.md`. Add tier `monthly_tokens`. Add Firestore **security rules**
  (client read-only on balances/ledger). Unit-test the debit (grant→topup order, clamping, ceilings).
- **Done when:** a simulated debit decrements correctly, never below zero, writes a ledger entry; rules
  deny client writes. **Owner reviews the diff.**

## Phase 5 — Grounded chat + credits UI
- Backend `POST /v1/chat`: grounded system prompt (answer only from the user's findings), per-turn
  `CHAT_MAX_OUTPUT` cap, read Vertex usage, debit via the Phase-4 helper, persist messages, return
  `{answer, tokens_used, balance}`.
- Frontend: Chat tab grounded to the user's last cast chart; a `<CreditsWidget/>` showing
  grant/topup/available; graceful 402/429 handling (upgrade / top-up prompts).
- **Done when:** a chat turn answers from the chart, debits real tokens, and the balance updates live.

## Phase 6 — Prashna / KP horary mode
- Backend `POST /v1/prashna` (chart for now, KP CSL by question→house, premise-neutrality, grounded
  verdict). Frontend Prashna tab (question + location). Tier: pro+.
- **Done when:** a question yields a grounded KP verdict with the sub-lord reasoning and a neutral
  "if-not" branch; no invented specifics.

## Phase 7 — Birth-Time Rectification mode
- Backend `POST /v1/btr` wrapping `rectify_birth_time(...)`. Frontend BTR tab (birth details + gender +
  sunrise + 3–5 events). Tier: enterprise.
- **Done when:** events produce candidate times + a confidence meter, grounded in the engine output.

## Phase 8 — Payments (Razorpay) — REVIEW REQUIRED
- Subscriptions → tier change + monthly grant; top-up packs → `topup_balance`. Verify webhook signatures;
  idempotent payment-id handling; wire to `/webhooks/payments`.
- **Done when:** a test subscription moves tier and grants tokens; a test pack adds top-up; replays don't
  double-credit. **Owner reviews the diff.**

## Phase 9 — Launch hardening
- `APP_ENV=prod` (stop seeding dev keys), `ADMIN_API_KEY` → Secret Manager, tighten `CORS_ORIGINS` to the
  web origin, custom domain + DNS, basic rate-limit/abuse review, error monitoring.
- **Done when:** no dev keys in prod, secrets out of env where possible, CORS locked, domain live.

## Cross-cutting acceptance checks
- Every reading line cites a finding (anti-slop intact). No doom; health = tendencies; remedies optional.
- Version stamps bumped on rules/renderer/section/tier changes (cache correctness).
- No secrets or engine committed. Money/auth diffs reviewed by the owner.
