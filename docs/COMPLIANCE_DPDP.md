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

**Phase 2 — Consent withdrawal + lawful-basis fix (§4/§6).**
- [ ] Withdrawal endpoint → stops processing + offers erasure.
- [ ] Granular/per-purpose consent; correct DPDP legal-basis text (drop "legitimate interest").
- [ ] §13 grievance intake + published officer; §14 nomination.

**Phase 3 — Breach notification + §8(5) hardening.**
- [ ] Breach runbook + Board/Principal notification template + 72-hour process.
- [ ] `CORS_ORIGINS` to domain, `VERIFY_TOKEN_REVOCATION=True`, apply Firestore TTL policies, edge rate limiting.

**Phase 4 — Governance (ongoing).**
- [ ] DPIA, RoPA, retention schedule, DPAs (Google/Razorpay), SCCs/transfer assessment for Vertex,
      EU representative; complete `/v1/me/export` (payments + sub-processors); human review for auto-bans.
