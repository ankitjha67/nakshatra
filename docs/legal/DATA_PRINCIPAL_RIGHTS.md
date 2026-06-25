# Your data rights & how to exercise them

> Published per **DPDP Rules 2025, Rule 9 & Rule 14** (a Data Fiduciary must prominently publish the
> means to exercise rights, the identifier needed, and a grievance system that responds within 90
> days) and **Rule 3** (notice must explain how to withdraw consent, exercise rights, and complain
> to the Board). For the full picture see the [Privacy Policy](PRIVACY_POLICY.md).

You are the **Data Principal**; Nakshatra is the **Data Fiduciary**. We identify your requests by the
**email address on your account** (your "identifier"). All actions below are self-service in the app
under **Account → Privacy & your data**, or via the API.

| Your right (DPDP) | How to exercise it | Endpoint |
|---|---|---|
| **Access / know** what we hold (s11) | "Export my data" — downloads your profile, ledger and chats as JSON | `GET /v1/me/export` |
| **Correction / update** of birth details (s12) | "Request a change" on the Account tab (reviewed by us) | `POST /v1/birth-change-request` |
| **Erasure** (s12) | "Delete my account" — removes profile, chats, ledger, API keys & sign-in | `DELETE /v1/me` |
| **Withdraw consent** (s6) — as easy as giving it | "Withdraw consent" — we stop processing your birth data | `POST /v1/consent/withdraw` |
| **Grievance redressal** (s13) | "File a privacy grievance" | `POST /v1/grievance` |
| **Nominate** someone to act for you on death/incapacity (s14) | "Nominee" form | `POST /v1/nominee` |

## Grievance & response time
File a grievance in-app or email the **Grievance Officer: Ankit Kumar — ankitjha67@gmail.com**. We
will respond within **90 days** (Rule 14(3)) — usually much sooner.

## Escalation
If you are not satisfied with our response, you may complain to the **Data Protection Board of
India**. If you are in the EEA/UK, you may also contact your local data-protection supervisory
authority.

## Age
Nakshatra is for adults only. You must confirm you are **at least 18** before any birth data is
processed; we do not knowingly process, profile, or behaviourally monitor children.
