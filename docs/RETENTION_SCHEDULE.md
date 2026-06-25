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
