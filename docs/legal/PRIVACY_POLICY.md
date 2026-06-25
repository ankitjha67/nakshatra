# Privacy Policy, Nakshatra

> **TEMPLATE, NOT LEGAL ADVICE.** For review by a qualified privacy lawyer. Must be
> reconciled with the India DPDP Act 2023 (Data Principal rights, Consent, Grievance
> Officer) and GDPR if you serve EU residents. **Effective date:** `[DATE]`.

`[COMPANY LEGAL NAME]` ("we") operates Nakshatra. This policy explains what personal data
we collect, why, how we share and protect it, and your rights.

## 1. Data we collect
- **Account:** email address and authentication identifiers (via Firebase Authentication).
- **Birth details you enter:** name (optional), date, time, and place/coordinates of birth,
  and the chart computed from them. *Birth date/time/place can be considered sensitive; we
  process it only to generate your readings.*
- **Chat content:** the questions you ask and the answers generated, if chat is used.
- **Usage & billing metadata:** tier, token-credit balance and ledger, request counts,
  timestamps. Payments are processed by **Razorpay**; we receive payment status/ids, **not
  full card details**.
- **Technical data:** IP address, approximate location derived from it, device/user-agent,
  and logs, used for security, abuse prevention, and debugging.

## 2. Why we use it (purposes & legal bases)
We process your data for these purposes: to generate your readings and chat; to meter and bill;
to secure the Service and prevent fraud/abuse (including anomaly detection and banning); and to
comply with law.

**Legal basis — India (DPDP Act 2023):** we rely on your **consent** for processing your birth
details and chat, and on the certain-legitimate-uses / contractual-necessity grounds the Act
permits for service delivery, billing, and security. (DPDP does not recognise an open-ended
"legitimate interest" basis.) **Legal basis — GDPR (if you are in the EEA/UK):** performance of a
contract (Art 6(1)(b)), legitimate interests for security/fraud (Art 6(1)(f)), legal obligation
(Art 6(1)(c)), and — because birth/astrology data can reveal special-category information —
**explicit consent (Art 9(2)(a))** for that data.

**Withdrawing consent.** You may withdraw consent at any time (as easily as you gave it) via the
app or `POST /v1/consent/withdraw`; we then stop processing your birth data. To also erase it,
delete your account (Section 6).

## 3. Sharing and sub-processors
We share data only with service providers that process it on our behalf under contract:
- **Google Cloud / Firebase** (hosting, authentication, Firestore database).
- **Google Vertex AI / Gemini** (the language model that phrases readings/chat from your
  computed findings).
- **Razorpay** (payment processing).
- **Umami** (privacy-first, **cookieless** product analytics — aggregate usage/page/event counts;
  no cookies and no personal data; honors Do-Not-Track).
We do not sell your personal data. We may disclose data if required by law or to protect
rights, safety, and the integrity of the Service. International transfers are protected by
appropriate safeguards.

## 4. Retention
We keep account and ledger data while your account is active and as required for legal,
tax, and audit purposes. Chat transcripts may be retained for a configurable window and
then deleted (TTL). You can delete your data at any time (Section 6).

## 5. Security
Data is encrypted in transit (HTTPS) and at rest. Access is least-privilege; balances and
the ledger are written only server-side; client database rules are deny-by-default. API
keys are stored hashed. No system is perfectly secure; we maintain controls and an incident
process and will notify you of breaches as required by law.

## 6. Your rights
Subject to law, you may access, correct, export, or delete your data, and object to or
restrict certain processing. We provide self-service:
- **Export** your data: `GET /v1/me/export`.
- **Delete** your account and data (right to erasure): `DELETE /v1/me` (removes your
  profile, ledger, chats, API keys, and Firebase identity).
- **Withdraw consent**: `POST /v1/consent/withdraw` (DPDP s6 / GDPR Art 7).
- **Nominate** someone to exercise your rights on your death/incapacity (DPDP s14): `POST /v1/nominee`.
- **File a grievance** (DPDP s13): `POST /v1/grievance`, or email the Grievance Officer below.
Or contact our Grievance Officer below. We respond within the timeframe the law requires.

## 7. Cookies & local storage
We use storage strictly necessary for authentication/session. We do not use third-party
advertising trackers. Our product analytics (**Umami**) is **cookieless** and collects no personal
data, so no analytics consent banner is required; we will add one if cookie-based or marketing
trackers are ever introduced.

## 8. Children
The Service is for adults only. At sign-up we require you to confirm you are **at least 18 years
old** before any birth data is processed (DPDP s9 / GDPR Art 8). We do not knowingly collect data
from, profile, or behaviourally monitor children. If we learn we have collected a child's data
without verifiable parental consent, we will delete it.

## 9. Changes
We will post updates here and, for material changes, notify you as required by law.

## 10. Contact / Grievance Officer
**Grievance Officer (India DPDP Act 2023, s8(9)/s13 + Rules 2025 r9/r14):** Ankit Kumar —
`ankitjha67@gmail.com`. You may file a grievance in-app (Account → Privacy & your data) or by
email; we aim to respond within **90 days** (the period prescribed by Rule 14(3)), and usually much
sooner. If unsatisfied, you may complain to the **Data Protection Board of India**. EU
representative (if applicable): `[NAME, CONTACT]`.
