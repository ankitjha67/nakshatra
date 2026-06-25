# Compliance — DPDP Act 2023 (+ GDPR / worldwide) gap analysis & remediation tracker

> **Engineering compliance read, NOT legal advice.** The ₹-crore exposure below means the
> notice/policy text and the children's-data approach must be reviewed by a qualified India
> privacy lawyer + GDPR counsel before public launch. This file tracks what the *code* does.

**Status date:** 2026-06-25 · **Phase:** beta, worldwide users · **We are the Data Fiduciary.**

The Act was read end-to-end from the official Gazette PDF (rendered page-images; the PDF's
font has no Unicode map so text extraction is unusable). Sections cited below are the real
section numbers from that read.

## Who we are
- **Data Fiduciary** (decides purpose & means): **Nakshatra / the company**.
- **Data Principals**: our users worldwide.
- **Data Processors** (sub-processors): Google Cloud/Firebase, Google Vertex/Gemini, Razorpay.
- **Trigger (§3):** we offer paid services to Data Principals in India and process digital
  personal data → DPDP applies. Worldwide users → GDPR/UK-GDPR/CPRA apply in parallel.
  **Beta gives no exemption.**

## Penalty exposure (DPDP Schedule, §33)
| Breach | Provision | Max penalty |
|---|---|---|
| Security safeguards failure | §8(5) | **₹250 cr** |
| Breach-notification failure | §8(6) | **₹200 cr** |
| Children's-data obligations | §9 | **₹200 cr** |
| Significant Data Fiduciary obligations | §10 | ₹150 cr |
| Data Principal duties | §15 | ₹10,000 |
| Voluntary-undertaking breach | §32 | up to amount applicable |
| Any other provision (catch-all) | — | **₹50 cr** |

## Section-by-section status
Legend: ✅ compliant · 🟡 partial · ❌ absent/non-compliant.

| § | Obligation | Status | Notes / code |
|---|---|---|---|
| §4 | Lawful ground (consent or §7 legitimate use) | ❌ | `PRIVACY_POLICY.md` claims GDPR "legitimate interest" for fraud/IP — **invalid under DPDP** (§7 is a closed list). Fraud/IP profiling must rest on consent+contract. |
| §5 | Itemised notice, per-purpose, rights+Board-complaint, scheduled languages | ❌ | One English sentence in `web/src/components/BirthForm.jsx` linking a GitHub markdown file. Not per-purpose, not hosted on-domain. |
| §6 | Consent free/specific/informed + **easy withdrawal** | ❌ | `/v1/consent` records version+timestamp, but **no withdrawal endpoint**; consent is a single blanket checkbox, not granular. |
| §7 | Legitimate uses (closed list) | 🟡 | §7(a) voluntary provision covers birth→reading only; not fraud/IP. |
| §8(3) | Accuracy for decisions/disclosures | 🟡 | Birth-change flow exists (admin-gated). |
| §8(4)(5) | Reasonable security safeguards | 🟡 | Good base (deny-by-default rules, hashed keys, server-only money path) but `CORS="*"`, per-instance rate limiting, TTLs unapplied, `VERIFY_TOKEN_REVOCATION=False`. |
| §8(6) | **Breach notification** to Board + each affected Principal | ❌ | No detection, runbook, template, or timeline. |
| §8(7) | Erasure on withdrawal / purpose end (+ cause processors) | 🟡 | `DELETE /v1/me` erases user/ledger/chats/keys/Firebase; not triggered by withdrawal; cache/derived data rely on (possibly unapplied) TTL. |
| §8(8) | Retention limitation | 🟡 | No documented schedule; `chat_retention_days=0` (keep forever) default. |
| §8(9)(10) | Publish DPO/contact + grievance redressal | ❌ | Not published/wired; policy §10 has empty placeholders. |
| §9 | **Children**: verifiable parental consent; no detrimental processing; **no behavioural monitoring / targeted ads to children** | ❌ | **No age gate** (`models.py` validates only lat/lon). DOB is collected but age never checked. Fraud engine behaviourally monitors all users. **Highest-likelihood risk.** |
| §10 | Significant Data Fiduciary (DPO-in-India, auditor, DPIA) | 🟢 | Only if Govt-notified; flag for scale. |
| §11 | Right to access (data + processing + recipients) | 🟡 | `GET /v1/me/export` returns user+ledger+chats; omits payments + recipient list. |
| §12 | Correction / completion / erasure | 🟡 | Erasure ok; correction is admin-gated, not self-service. |
| §13 | Grievance redressal | ❌ | No endpoint or officer. |
| §14 | Nomination | ❌ | Absent entirely. |
| §16 | Cross-border transfer (blacklist model) | 🟡 | Firestore in `asia-south1` ✅ but prod `VERTEX_LOCATION=global` → chart-derived data leaves India/EU. DPDP tolerant today; **GDPR Ch.V gap now.** |

## DPDP Rules 2025 (G.S.R. 846(E), 13 Nov 2025) — mapping
**Commencement (Rule 1):** Rules 1–2 & 17–21 in force on publication; **Rule 4** (Consent Managers)
+1 year (~Nov 2026); **Rules 3, 5–16, 22–23** in force **18 months after publication ≈ 13 May 2027**.
So the detailed Rule obligations become enforceable ~May 2027 — but the Act and GDPR bind us now, so
we build to comply early.

| Rule | Requirement | Our status |
|---|---|---|
| r3 | Notice: standalone, itemised data + purposes, links to withdraw / exercise rights / complain to Board | 🟡 policy + rights notice updated; in-app notice still a short checkbox (improve copy) |
| r6 | Security minimums: encryption, access control, **logs+monitoring+review**, backups, **1-yr log retention**, processor contracts, tech/org measures | 🟡 Firestore encryption-at-rest + Cloud Logging ✓; need 1-yr log retention config + DPAs |
| r7 | Breach: to each principal "without delay" (nature/extent/timing, consequences, mitigation, safety steps, responder); to Board immediately + **detailed within 72h** | ✅ register fields match r7; runbook in `INCIDENT_RESPONSE.md` |
| r8 | Retention: Third-Schedule classes erase after 3y inactivity (+48h notice); **all** keep logs ≥1y | ✅ not in a Third-Schedule class; 1-yr log rule documented in `RETENTION_SCHEDULE.md` |
| r9 | Publish DPO/contact on site + in every rights response | ✅ Grievance Officer set (Ankit Kumar), surfaced in `/v1/me` + Account UI |
| r10/r11 | Verifiable parental/guardian consent for children/PwD | ✅ avoided — adults-only 18+ gate (Fourth Schedule Pt B item 6 blesses age-confirmation) |
| r13 | SDF: yearly DPIA+audit, algorithmic due-diligence, **data localisation** for notified data | 🟢 only if notified as SDF (not yet) |
| r14 | Publish means to exercise rights + identifier; **90-day** grievance response; nomination | ✅ endpoints + `DATA_PRINCIPAL_RIGHTS.md` (90-day stated); email = identifier |
| r15 | Cross-border transfer allowed unless Central Govt restricts by order | 🟡 permissive under DPDP; Vertex `global` still a GDPR Ch.V gap (SCCs) |

## Other laws (worldwide beta)
- **EU/UK GDPR**: birth+astrology can infer **health/religion → Art 9 special category** (explicit
  consent + DPIA); Art 6 basis, Art 13/14 notice, Art 15–22 rights, **Art 22 automated decisions**
  (fraud auto-ban), Art 30 RoPA, **Art 33/34 72-hour breach**, Ch.V transfers, Art 27 EU rep,
  UK Children's Code (under-18 profiling).
- **California CPRA**: notice-at-collection, "Do Not Sell/Share" statement, delete/correct/know,
  sensitive-PI handling.
- **ePrivacy/cookies**: keep auth-only storage or add a consent banner.
- **PCI-DSS**: ✅ SAQ-A via Razorpay hosted checkout (we never see card data).
- **Advertising/consumer**: visible "entertainment, not professional advice" disclaimer.

## Remediation roadmap (phased)
**Phase 0 — this document.** ☑

**Phase 1 — Age gate (§9 / GDPR Art 8 / UK Children's Code). ☑ shipped**
- [x] Adult (18+) attestation captured at consent (`/v1/consent` requires `is_adult`; 403 otherwise);
      stored as `adult_confirmed`/`adult_confirmed_at`; surfaced in `/v1/me`; consent text bumped to
      state "I am at least 18 years old"; `CONSENT_VERSION` bumped so all users re-attest.
- [x] We refuse to onboard minors at all (no consent → no cast), so there are no *known* children to
      behaviourally monitor. (When verifiable parental consent is added later, revisit profiling.)
- [x] Config `min_user_age` (default 18).

**Phase 2 — Consent withdrawal + lawful-basis fix (§4/§6/§13/§14). ☑ shipped**
- [x] `POST /v1/consent/withdraw` → stops processing (clears consent/adult flag, forces re-consent);
      points to `DELETE /v1/me` for erasure. Exposed in Account → "Privacy & your data".
- [x] DPDP legal-basis text corrected in `PRIVACY_POLICY.md` (consent + permitted uses; dropped the
      open-ended "legitimate interest"; GDPR bases stated separately incl. Art 9 explicit consent).
- [x] §13 grievance intake (`POST /v1/grievance`, admin `GET /admin/grievances`) + published officer
      (`grievance_officer_name`/`_email` config, surfaced in `/v1/me`).
- [x] §14 nomination (`GET/POST/DELETE /v1/nominee`).
- [x] Self-service Export/Withdraw/Delete/Grievance/Nominee UI in `AccountTab`. Tests: 92 passing.
- [ ] *Deferred:* fully granular per-purpose consent toggles (chat vs profiling vs marketing).

**Phase 3 — Breach notification + §8(5) hardening. ☑ shipped (code/docs); ops pending**
- [x] `docs/INCIDENT_RESPONSE.md` — breach runbook (DPDP §8(6) Board + Principal, GDPR Art33/34
      72-hour) + notification template.
- [x] Breach register: `POST /admin/breach` + `GET /admin/breaches` (audited) + store methods.
- [x] `docs/RETENTION_SCHEDULE.md` — per-class retention (DPDP §8(7)/(8)) + TTL apply commands.
- [x] Prod startup check added for unset Grievance Officer (existing checks already flag `CORS="*"`,
      `VERIFY_TOKEN_REVOCATION=False`, weak admin/internal secrets, missing global breaker).
- [ ] **Ops (must be done on the live service):** set `CORS_ORIGINS` to the web origin,
      `VERIFY_TOKEN_REVOCATION=True`, `GRIEVANCE_OFFICER_NAME/_EMAIL`, `CHAT_RETENTION_DAYS=90`;
      **apply the two Firestore TTL policies** (see RETENTION_SCHEDULE.md); add edge rate limiting.

**Phase 4 — Governance (ongoing).**
- [x] Retention schedule (`RETENTION_SCHEDULE.md`); Rules-2025 mapping (above).
- [x] **Live ops applied** (rev jyotish-api-00049-n8z): `GRIEVANCE_OFFICER_NAME/_EMAIL` set
      (Ankit Kumar / ankitjha67@gmail.com), `VERIFY_TOKEN_REVOCATION=true`, `CHAT_RETENTION_DAYS=90`,
      `CORS_ORIGINS` locked to the two Firebase hosting origins (verified: web origin allowed, others
      rejected). **Firestore TTL policies enabled** on `messages.expireAt` and `cache.expireAt`.
- [x] **RoPA** (`docs/legal/ROPA.md`), **DPIA** (`docs/legal/DPIA.md`), **DPA** (`docs/legal/DPA.md`
      — Part A sub-processor register + Part B processor template) drafted (pre-filled templates).
- [x] Complete `/v1/me/export` (payments + sub-processor/recipient list) — shipped v0.40.0.
- [ ] **Execute** the sub-processor DPAs (Google Cloud DPA + SCCs, Razorpay DPA), confirm Vertex
      no-training/retention, complete the SCCs/transfer-impact assessment for Vertex `global`.
- [ ] EU representative (Art 27) if EEA users retained; appoint/confirm DPO status.
- [ ] 1-year security-log retention config (Cloud Logging bucket); user-facing **auto-ban appeal**.
- [ ] Lawyer review + fill `[BRACKETS]` (legal name/address) + host policy/terms/rights/RoPA notice
      on the product domain (still GitHub-markdown links).
