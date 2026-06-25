# Data Processing Agreements (DPA)

> **TEMPLATE — review with counsel.** Two parts: **Part A** is the register of sub-processor DPAs we
> (as Data Fiduciary/controller) rely on; **Part B** is the DPA we offer business customers when *we*
> act as a **processor** (enterprise/API tier). Fill `[BRACKETS]`. **Date:** 2026-06-25.

---

## PART A — Sub-processor register (Nakshatra is the controller)
Under DPDP s8(2)/Rule 6(1)(f) and GDPR Art 28, every processor we use must be bound by a DPA with
security + sub-processing + breach + deletion + transfer terms. We rely on each provider's standard
DPA — **execute/accept these and record the date**.

| Sub-processor | Service | Data | Region | DPA to accept | Status |
|---|---|---|---|---|---|
| Google Cloud / Firebase | Hosting, Auth, Firestore | account, birth, chat, billing, logs | asia-south1 (India) | Google Cloud Data Processing Addendum (+ SCCs module) | `[ ] executed [date]` |
| Google Vertex AI / Gemini | LLM phrasing of findings | computed findings (no name/email/UID) | **global** | Google Cloud DPA / Vertex terms; **confirm no-training + retention** | `[ ] confirmed [date]` |
| Razorpay | Payment processing | payment ids/status, amount, contact | India | Razorpay DPA / merchant terms | `[ ] executed [date]` |

**Actions:** (1) accept each DPA; (2) for GDPR, ensure **SCCs** cover the Vertex `global` transfer +
a transfer-impact assessment; (3) confirm Vertex/Gemini **does not train** on our prompts and its
retention window; (4) keep this register current; new sub-processors require a DPA before go-live.

---

## PART B — DPA template (Nakshatra is the processor)
Use this when a **business customer** (Controller) uses the Nakshatra enterprise/API tier to process
their end-users' personal data. This DPA supplements the service agreement.

**Parties:** `[CUSTOMER LEGAL NAME]` ("Controller") and `[COMPANY LEGAL NAME]` operating Nakshatra
("Processor").

1. **Subject-matter & duration.** Processing of personal data by the Processor solely to provide the
   Nakshatra API/service for the term of the agreement and until deletion/return per clause 9.
2. **Nature & purpose.** Computing astrology charts/readings/chat from birth data supplied by the
   Controller, and related metering/security. Details in **Annex 1**.
3. **Controller instructions.** The Processor processes personal data only on the Controller's
   documented instructions (this DPA + the API requests), including for transfers, unless required by
   law (in which case it informs the Controller unless legally prohibited).
4. **Confidentiality.** Personnel with access are bound by confidentiality.
5. **Security.** The Processor implements the technical & organisational measures in **Annex 2**
   (Art 32 / DPDP Rule 6): encryption in transit/at rest, access control, logging/monitoring,
   backups, deny-by-default rules, hashed credentials, ≥1-year security-log retention.
6. **Sub-processing.** The Controller authorises the sub-processors in **Annex 3** (Google Cloud,
   Vertex AI, Razorpay). The Processor imposes equivalent terms on each and remains liable; it gives
   `[30]` days' notice of changes, allowing objection.
7. **Data-subject rights.** The Processor assists the Controller (by appropriate technical/org
   measures, insofar as possible) to respond to access/correction/erasure/portability/withdrawal/
   objection requests, and forwards any request it receives directly.
8. **Personal-data breach.** The Processor notifies the Controller **without undue delay** after
   becoming aware, with the information needed for the Controller's own notifications (nature, extent,
   timing, likely impact, mitigation, contact) — aligned to DPDP Rule 7 / GDPR Art 33.
9. **Deletion / return.** On termination, the Processor deletes or returns all personal data and
   deletes existing copies, unless law requires retention (e.g. payment/tax records, ≥1-year security
   logs); it confirms in writing.
10. **Audits.** The Processor makes available information necessary to demonstrate compliance and
    allows/contributes to audits `[once per year / on reasonable notice]`, including via third-party
    certifications/reports where available.
11. **International transfers.** Transfers outside the Controller's jurisdiction occur only with
    appropriate safeguards (SCCs / adequacy) and subject to DPDP Rule 15 / GDPR Ch.V (note Vertex
    `global`).
12. **Liability & precedence.** Liability per the service agreement; this DPA prevails over it on
    data-protection matters; governing law `[JURISDICTION]`.

### Annex 1 — Processing details
- **Categories of data subjects:** the Controller's end-users.
- **Categories of data:** birth details (date/time/place), optional name, questions/answers, account
  identifiers, usage/billing metadata. *May infer special-category data — Controller must have a
  lawful basis (e.g. explicit consent).*
- **Purpose:** generate readings/chat; meter; secure. **Duration:** term + deletion window.

### Annex 2 — Technical & organisational measures
Per RoPA §5 / `SECURITY.md`: TLS; encryption at rest; deny-by-default Firestore rules; server-only
money path; hashed API keys + pepper; constant-time secret compare; Firebase token verification +
revocation; request body-size limit; per-user daily token ceiling + global breaker; fraud monitoring;
breach register + runbook; PII out of logs; TTL data ageing.

### Annex 3 — Authorised sub-processors
Google Cloud / Firebase (hosting/auth/DB, India); Google Vertex AI / Gemini (LLM, global); Razorpay
(payments, India). See Part A for status.
