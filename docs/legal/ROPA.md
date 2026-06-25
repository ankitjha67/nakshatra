# Record of Processing Activities (RoPA)

> **GDPR Art 30** record (and supports DPDP accountability). Maintained by the Data Fiduciary.
> **TEMPLATE — review with counsel.** Fill `[BRACKETS]`. **Last updated:** 2026-06-25.

## 1. Controller / Data Fiduciary
- **Legal entity:** `[COMPANY LEGAL NAME]`, `[REGISTERED ADDRESS]`, `[COUNTRY: India]`.
- **Product:** Nakshatra (tiered Vedic-astrology SaaS) — `https://nakshatra-prod-2026.web.app`.
- **Grievance Officer / contact (DPDP s8(9)/s13):** Ankit Kumar — ankitjha67@gmail.com.
- **EU representative (GDPR Art 27, if EEA users):** `[NAME, CONTACT or "not appointed"]`.
- **DPO:** `[appointed? Y/N — not legally required unless SDF/large-scale special-category]`.

## 2. Categories of Data Principals / data subjects
Adult (18+) registered users worldwide who request astrology readings/chat; B2B/enterprise API
callers' end-users (where Nakshatra acts as **processor** — see the DPA). **No children** are
knowingly onboarded (18+ attestation gate).

## 3. Processing activities

### A. Account & authentication
- **Purpose:** create/operate a user account; authenticate.
- **Data:** email, Firebase UID, auth identifiers, consent record (version, timestamp, adult attestation).
- **Legal basis:** DPDP — consent + contractual necessity; GDPR — Art 6(1)(b) contract.
- **Recipients:** Google Firebase (auth), Google Firestore (storage).
- **Retention:** while account active; erased on `DELETE /v1/me`. Withdrawal of consent stops processing.
- **Security:** Firebase ID-token verification + revocation check; deny-by-default Firestore rules.

### B. Birth chart & readings (core)
- **Purpose:** compute the chart and generate the reading/report the user requested.
- **Data:** name (optional), **date / time / place / lat-lon of birth**, timezone, derived chart & findings.
  *Note: birth/astrology data can **infer** health tendencies & religious belief → treated as
  **special category** (GDPR Art 9) — see DPIA.*
- **Legal basis:** DPDP — **consent** (s6); GDPR — Art 6(1)(b) + **Art 9(2)(a) explicit consent**.
- **Recipients:** the proprietary engine (local compute); Google Vertex AI/Gemini (phrases prose from
  computed findings only — **name/email/UID are not sent**); Firestore cache (chart-hash keyed).
- **Retention:** birth lock while active; reading/chart cache TTL 90 days; erased on account deletion.

### C. Chat (follow-up questions)
- **Purpose:** answer the user's questions grounded in their own chart/findings.
- **Data:** user questions + generated answers; token counts.
- **Legal basis:** DPDP consent; GDPR Art 6(1)(b) + Art 9(2)(a).
- **Recipients:** Vertex AI/Gemini; Firestore.
- **Retention:** `CHAT_RETENTION_DAYS=90` (Firestore TTL on `messages.expireAt`); erased on deletion.

### D. Billing & token credits
- **Purpose:** meter usage, charge subscriptions/top-ups, maintain the credit ledger.
- **Data:** tier, credit balance & ledger, Razorpay payment ids/status, amount (INR), subscription id.
  **No card data** (Razorpay hosted checkout — PCI SAQ-A).
- **Legal basis:** DPDP contractual necessity + legal obligation (tax); GDPR Art 6(1)(b)/(c).
- **Recipients:** Razorpay (payment processing); Firestore.
- **Retention:** payment records ~7 years (tax/audit); ledger erased with account otherwise.

### E. Security, fraud & abuse prevention
- **Purpose:** prevent abuse, prompt-injection/jailbreaks, fraud; rate-limit; ban abusers.
- **Data:** IP address, device/user-agent, request counts/timestamps, jailbreak/malicious counts,
  abuse-sample snippets (≤240 chars), risk score/band, bans, breach register.
- **Legal basis:** DPDP — permitted uses + legal obligation (NOT open-ended "legitimate interest");
  GDPR — Art 6(1)(f) legitimate interests (security) + Art 6(1)(c).
- **Recipients:** Firestore; (no third-party sharing).
- **Retention:** security logs/processing data ≥1 year (DPDP Rule 8(3)/6(1)(e)); erased with account
  thereafter where not legally required.

### F. Data-subject rights handling
- **Purpose:** service access/export/correction/erasure/withdrawal/grievance/nomination.
- **Data:** request metadata, grievance text, nominee details.
- **Legal basis:** legal obligation (DPDP Ch.III / GDPR Ch.III).
- **Retention:** grievance/audit records retained for compliance.

## 4. Cross-border transfers
- **Firestore / Firebase:** `asia-south1` (India). **Vertex AI/Gemini:** `global` endpoint → data may
  be processed **outside India/EEA**.
- **DPDP (Rule 15):** permitted unless the Central Govt restricts by order (none currently).
- **GDPR (Ch.V):** transfer mechanism required → `[SCCs with Google — status]`; transfer-impact
  assessment `[link]`.

## 5. General security measures (Art 32 / DPDP Rule 6)
TLS in transit; encryption at rest (Firestore); deny-by-default security rules; server-only money
path; hashed API keys + pepper; constant-time secret comparison; Firebase token verification +
revocation; request body-size limit; per-user daily token ceiling + global breaker; fraud monitoring;
breach register + runbook; PII kept out of logs; TTL-based data ageing. See `SECURITY.md`,
`docs/SECURITY_AUDIT_VULN_CLASSES.md`, `docs/RETENTION_SCHEDULE.md`.
