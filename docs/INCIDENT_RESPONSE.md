# Incident response & personal-data-breach notification

> Satisfies DPDP Act 2023 **§8(6)** (intimate the Data Protection Board of India **and each
> affected Data Principal**) and GDPR **Art 33/34** (notify the supervisory authority within
> **72 hours**, and affected individuals "without undue delay" when risk is high).
> A "personal data breach" (DPDP §2) = any unauthorised processing, or accidental disclosure,
> acquisition, sharing, use, alteration, destruction, or loss of access to, personal data.

## Roles
- **Incident Lead:** `[NAME / EMAIL]` (owns the timeline & decisions).
- **Grievance Officer (DPDP):** `GRIEVANCE_OFFICER_EMAIL` (handles Data Principal comms).
- **Tech on-call:** whoever holds GCP/Firebase admin.

## The clock starts when we *become aware* of a breach. Steps:
1. **Contain (hour 0–2):** revoke leaked credentials/keys, rotate `ADMIN_API_KEY`/`INTERNAL_TOKEN`/
   Razorpay secrets, tighten `firestore.rules` if exposure is rule-related, disable affected
   endpoints. Snapshot logs (Cloud Logging) before they roll off.
2. **Assess (hour 0–24):** what data, how many Data Principals, severity, ongoing or contained.
   Record it in the register: `POST /admin/breach` (description, severity, affected_count,
   discovered_at). This is the auditable trail; read it back via `GET /admin/breaches`.
3. **Notify the Board (DPDP §8(6)):** intimate the Data Protection Board of India as soon as the
   breach is known (use the form/portal the DPDP Rules prescribe). Do **not** wait for full
   root-cause. Set `notified_board=true` on the register entry.
4. **Notify Data Principals (DPDP §8(6); GDPR Art 34):** email each affected user — what happened,
   what data, likely consequences, what we're doing, what they should do (e.g. reset password),
   and the Grievance Officer contact. Set `notified_principals=true`.
5. **GDPR (if any EEA/UK user is affected):** notify the lead supervisory authority within **72
   hours** of awareness (Art 33). If you have no EU establishment, notify via your Art 27 EU rep.
6. **Remediate & close:** root-cause fix, add a regression test/control, post-mortem, update this
   runbook. Keep the register entry for audit.

## Notification template (to affected Data Principals)
```
Subject: Important security notice about your Nakshatra account

We are writing to inform you of a security incident that may have affected your personal data.

What happened: [brief, factual]
When: discovered on [date]; the incident occurred around [date].
Data involved: [e.g. email, birth details, chat history — be specific and honest].
Likely impact: [what could happen].
What we have done: [containment + fixes].
What you should do: [reset password / be alert to phishing / etc.].

You can contact our Grievance Officer at [GRIEVANCE_OFFICER_EMAIL] with any questions, and you may
also complain to the Data Protection Board of India.

— The Nakshatra team
```

## Do-not
- Do not delete logs or evidence before assessment.
- Do not under-report scope to "look better" — DPDP penalties for breach-notification failure
  reach **₹200 crore**, and under-notification is itself a violation.
