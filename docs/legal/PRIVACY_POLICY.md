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
To provide readings and chat (performance of contract); to meter and bill (contract / legal
obligation); to secure the Service and prevent fraud/abuse including anomaly detection and
banning (legitimate interests / legal obligation); to comply with law; and, only with your
consent where required, for optional communications. Where we rely on consent you may
withdraw it at any time.

## 3. Sharing and sub-processors
We share data only with service providers that process it on our behalf under contract:
- **Google Cloud / Firebase** (hosting, authentication, Firestore database).
- **Google Vertex AI / Gemini** (the language model that phrases readings/chat from your
  computed findings).
- **Razorpay** (payment processing).
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
Or contact our Grievance Officer below. We respond within the timeframe the law requires.

## 7. Cookies & local storage
We use storage strictly necessary for authentication/session. We do not use third-party
advertising trackers. `[Update if analytics/marketing cookies are added, add a consent banner.]`

## 8. Children
The Service is not intended for anyone under 18, and we do not knowingly collect their data.

## 9. Changes
We will post updates here and, for material changes, notify you as required by law.

## 10. Contact / Grievance Officer
Data questions or requests: `[PRIVACY EMAIL]`. Grievance Officer (India DPDP): `[NAME,
EMAIL, ADDRESS]`. EU representative (if applicable): `[NAME, CONTACT]`.
