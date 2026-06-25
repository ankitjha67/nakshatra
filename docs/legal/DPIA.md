# Data Protection Impact Assessment (DPIA)

> **GDPR Art 35** (and DPDP **Rule 13(1)** for a Significant Data Fiduciary). A DPIA is warranted
> here because we (a) process data that **infers special-category** information (health tendencies,
> religious belief) and (b) carry out **profiling** (automated fraud risk scoring + auto-ban).
> **TEMPLATE — review with counsel.** **Date:** 2026-06-25 · **Owner:** Ankit Kumar.

## 1. Description of the processing
- **Nature:** users submit birth details (date/time/place); a deterministic engine computes a chart;
  a rules layer derives findings; an LLM (Vertex/Gemini) phrases grounded prose; a chat lets users
  ask follow-ups. Billing via Razorpay; security/fraud monitoring throughout.
- **Scope:** adult (18+) users worldwide (beta). Volumes: `[current user count]`. Data categories per
  the [RoPA](ROPA.md). Special-category **inference** from birth/astrology data.
- **Context:** B2C subscription + B2B/enterprise API. Sub-processors: Google Cloud/Firebase, Google
  Vertex AI/Gemini, Razorpay. Firestore in India; Vertex `global`.
- **Purposes:** deliver readings/chat; bill; secure the service.

## 2. Necessity & proportionality
- **Lawful basis:** consent for birth/chat data (DPDP s6; GDPR Art 6(1)(b) + **Art 9(2)(a) explicit
  consent**); contract/legal-obligation for billing; legitimate interests/legal obligation for security.
- **Data minimisation:** name is **optional and excluded** from the chart hash and from the LLM
  prompt; only computed findings (not raw identity) are sent to the LLM; engine runs locally.
- **Retention:** TTL-bounded (chat/cache 90d; security logs ≥1y; payments ~7y) — see RETENTION_SCHEDULE.
- **Transparency:** notice + Privacy Policy + Data Principal Rights notice; in-app consent with 18+ gate.

## 3. Consultation
- Internal: engineering + owner. External: `[privacy counsel — pending]`. Data-subject views:
  beta-tester feedback channel. Sub-processor assurances: Google/Razorpay DPAs + certifications.

## 4. Risks to data subjects (likelihood × severity → rating)
| # | Risk | L | S | Rating | 
|---|------|---|---|--------|
| R1 | **Special-category inference** (health/religion) exposed or misused | Low | High | **Medium** |
| R2 | **Children** mis-onboarded and profiled | Low | High | **Medium** |
| R3 | **Personal-data breach** (unauthorised access/disclosure) | Low | High | **Medium** |
| R4 | **Cross-border** exposure via Vertex `global` (GDPR Ch.V) | Med | Med | **Medium** |
| R5 | **Automated decision** (fraud auto-ban) wrongly restricts a user (Art 22) | Low | Med | Low-Med |
| R6 | **Re-identification / profiling** beyond expectation | Low | Med | Low-Med |
| R7 | **LLM harm** — fatalistic/“doom”, health-as-diagnosis, hallucinated placements | Low | Med | Low-Med |
| R8 | **Excessive retention** | Low | Med | Low |

## 5. Measures to address each risk
- **R1:** explicit consent for special-category; minimisation (no name/email to LLM; findings only);
  encryption at rest + deny-by-default rules; output filters strip secrets/echoes.
- **R2:** **18+ attestation gate** (no children knowingly onboarded → no children's data/profiling);
  Privacy Policy children clause; revisit if verifiable parental consent is ever added.
- **R3:** Art-32 controls (RoPA §5); **breach register + runbook** (`INCIDENT_RESPONSE.md`) with
  Board + 72-hour + affected-principal notification; least-privilege; body-size limit; audited admin.
- **R4:** `[SCCs with Google + transfer-impact assessment — pending]`; document Vertex region; DPDP
  Rule 15 currently permissive; consider an in-region model when available.
- **R5:** auto-ban is **temporary, decaying, and reversible**; risk is transparent (banner) and an
  **admin/human-review path** can unban; `[add a user-facing appeal — planned]`.
- **R6:** profiling limited to security signals; risk decays with good behaviour; no ad/marketing use.
- **R7:** anti-slop SYSTEM_PROMPT forbids invented placements, doom, flattery; health = tendencies not
  diagnosis; remedies optional; citations validated ⊆ findings; disclaimers shown.
- **R8:** TTL policies live (chat/cache); retention schedule documented; erasure on request.

## 6. Residual risk & sign-off
- **Residual:** R4 (cross-border) is the main open item pending SCCs/transfer assessment; others
  reduced to **Low** by the measures above.
- **Outcome:** `[ ] Proceed  [ ] Proceed with conditions  [ ] Consult DPB/SA` — `[decision]`.
- **Approved by:** Ankit Kumar — `[date]`. **Review:** at least every 12 months or on material change
  (DPDP Rule 13(1) cadence for an SDF).
