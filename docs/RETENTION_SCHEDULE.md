# Data retention schedule

> Satisfies DPDP **§8(7)/(8)** (retain only as long as needed for the purpose / legal requirement;
> erase thereafter) and GDPR **Art 5(1)(e)** (storage limitation). Operationalise the TTLs below
> with Firestore TTL policies; the app stamps `expireAt` where a window is configured.

| Data class | Store / collection | Retention | Mechanism |
|---|---|---|---|
| Account profile (`users/{uid}`) | Firestore | While account active; erased on `DELETE /v1/me` | User self-delete / admin delete |
| Birth lock (`users/{uid}.birth_lock`) | Firestore | While active; stops being processed on consent withdrawal | Erased with account |
| Chat transcripts (`users/{uid}/chats/**`) | Firestore | `CHAT_RETENTION_DAYS` (recommend 90) | `expireAt` + Firestore TTL policy |
| Chart/reading cache (`cache/**`) | Firestore | `CACHE_TTL_DAYS` (default 90) | `expireAt` + Firestore TTL policy |
| Credit ledger (`users/{uid}/ledger/**`) | Firestore | Erased with account; keep **payment** records per tax law | Erased with account |
| Payment records (`payments/**`) | Firestore | **7 years** (India GST/audit) then purge | Manual/scheduled purge — *TODO* |
| Activity / IP (`activity/{uid}`) | Firestore | 90 days rolling; erased with account | *TODO: scheduled purge* |
| Jailbreak/abuse samples | `users/{uid}` + `users/{uid}/jailbreaks` | Erased with account; review annually | Erased with account |
| Audit log (`audit/**`) | Firestore | Retain for compliance (e.g. 3 years) | *TODO: scheduled purge* |
| Grievances / breaches register | `grievances/**`, `breaches/**` | Retain for compliance | Manual |

## DPDP Rules 2025 specifics (Rule 8)
- **Rule 8(3) — 1-year minimum:** personal data, associated traffic data and processing **logs**
  must be retained for **at least one year** for breach detection/investigation (Rule 6(1)(e) says
  the same for security logs), then erased unless another law requires longer. Practical effect:
  even after a user deletes their account, transaction/payment records and security logs are kept
  ~1 year (see the Rules' own illustration: an e-book order's logs survive account deletion for a
  year). Our `DELETE /v1/me` erases the user's profile/chats/ledger immediately; **payment records
  and security logs are intentionally retained** for this window + tax/audit law.
- **Rule 8(1)/(2) + Third Schedule — does NOT apply to us:** the 3-years-of-inactivity auto-erase
  (with a 48-hour pre-erasure notice) binds only e-commerce (≥2 cr users), online-gaming (≥50 lakh)
  and social-media (≥2 cr) intermediaries. Nakshatra is none of these, so we are not in a listed
  class. We still apply voluntary chat/cache TTLs below as data-minimisation good practice.

## Apply the TTL policies (one-time ops, per docs/GO_LIVE.md)
```bash
# chat transcripts
gcloud firestore fields ttls update expireAt \
  --collection-group=messages --enable-ttl --project=nakshatra-prod-2026
# reading/chart cache
gcloud firestore fields ttls update expireAt \
  --collection-group=cache --enable-ttl --project=nakshatra-prod-2026
```
Set `CHAT_RETENTION_DAYS=90` and `CACHE_TTL_DAYS=90` on the Cloud Run service so `expireAt` is
stamped. Items marked *TODO* need a scheduled Cloud Run job / Cloud Scheduler to purge by age.
