# docs/CREDIT_LEDGER.md, Token credits, metering, and grounded chat

The chat is pay-as-you-go on a **token credit ledger**. Each tier grants a monthly token allowance;
higher tiers grant more; users can buy top-up packs; every chat turn debits actual tokens used.
**All metering is server-side and atomic.** This is a money path, see the guardrails.

## Unit

Meter in **LLM tokens** (prompt + completion, from Vertex `usage_metadata`). Display to users as a
friendly balance / progress bar (optionally "credits" where 1 credit = 1,000 tokens). Token-based is
honest because message sizes vary; don't meter "per message".

## Firestore schema

```
users/{uid}
  tier            : "free" | "basic" | "pro" | "enterprise"
  grant_balance   : int     # resets each cycle to tier.monthly_tokens
  topup_balance   : int     # purchased tokens; PERSISTS across cycles
  monthly_tokens  : int     # cached from tier at last grant (audit)
  cycle_start     : Timestamp
  cycle_end       : Timestamp
  updated_at      : Timestamp
  daily_tokens_used : int    # resets daily (abuse ceiling, independent of balance)
  daily_date      : "YYYY-MM-DD"

users/{uid}/ledger/{autoId}        # append-only audit trail
  type        : "grant" | "debit" | "topup" | "refund" | "reset"
  tokens      : int                 # signed not required; type implies direction
  balance_after : int               # grant_balance + topup_balance after this entry
  reason      : str                 # "monthly grant" | "chat turn" | "razorpay pack 350k" | ...
  ref         : str|null            # chat message id / payment id
  ts          : Timestamp

users/{uid}/chats/{chatId}
  chart_hash  : str                 # the cast chart this conversation is grounded in
  title       : str
  created_at  : Timestamp
users/{uid}/chats/{chatId}/messages/{autoId}
  role        : "user" | "assistant"
  text        : str
  tokens      : int|null            # tokens this turn cost (assistant turns)
  ts          : Timestamp
```

**Tier monthly grants** (tune later): free 0 (no chat) or a tiny one-time trial; basic 50,000;
pro 500,000; enterprise 5,000,000. **Top-up packs** (examples): ₹99→100k, ₹299→350k, ₹799→1M. Top-ups
land in `topup_balance` and do not expire on cycle reset.

Available = `grant_balance + topup_balance`. **Debit order: grant first, then topup.**

## Cycle reset (grant refresh)

On the first request after `cycle_end` (or via a scheduled job): set
`grant_balance = tier.monthly_tokens`, advance `cycle_start/cycle_end` by one month, write a `reset`
ledger entry. `topup_balance` is untouched. Lazy reset (on request) is fine; a Cloud Scheduler job is a
nice-to-have, not required.

## Server-side metering flow (the chat turn)

`POST /v1/chat` with `Authorization: Bearer <idToken>` and `{chart (birth details or chart_hash),
chat_id?, message, history?}`:

1. **Verify** the Firebase ID token → `uid` (reuse `auth.require_principal`). Load `users/{uid}`,
   running cycle-reset and daily-reset if due.
2. **Pre-check (advisory):** if `available <= 0` → `402` `{detail:"You're out of chat credits, upgrade
   or add a top-up."}`. If `daily_tokens_used >= DAILY_TOKEN_CEILING` → `429` (abuse ceiling).
   *Do not call the LLM if blocked.*
3. **Build the grounded prompt:** load/compute the chart + `derive_findings(chart)` (reuse `pipeline`).
   System prompt: *"Answer ONLY from these findings about the user's chart; if the findings don't
   address the question, say so plainly. No new placements, no doom, no medical/legal/financial
   directives."* Provide: the findings, the recent `history` (trimmed), and the `message`.
4. **Call Vertex** with a **hard per-turn cap** `max_output_tokens = CHAT_MAX_OUTPUT` (e.g. 800) so one
   turn can't exceed a bounded size. Read `usage_metadata` → `cost = prompt_tokens + completion_tokens`.
5. **Debit atomically** in a Firestore **transaction** on `users/{uid}`:
   - spend `grant_balance` first, remainder from `topup_balance`; clamp each at 0 (never below).
   - `daily_tokens_used += cost`.
   - write a `debit` ledger entry `{tokens:cost, balance_after, ref:messageId}` and the two chat messages.
   (The LLM call already happened, so a turn that slightly overshoots the last few credits is allowed
   once, then `available` is 0 and the next pre-check blocks. The per-turn cap keeps any overshoot tiny.)
6. **Respond** `{answer, tokens_used, balance:{grant, topup, available}}`.

### Ceilings (defense in depth)
- `CHAT_MAX_OUTPUT` per-turn output cap (bounded turn size).
- `DAILY_TOKEN_CEILING` per-user/day, independent of balance (stops runaway loops / abuse).
- Optional global daily Vertex spend breaker (env flag) for total cost safety.

## Firestore security rules (critical)

The client may **read** its own balance but must **never write** balances or the ledger. Only the
backend (Firebase Admin SDK, which bypasses rules) writes them.

```
match /users/{uid} {
  allow read: if request.auth != null && request.auth.uid == uid;
  allow write: if false;                         // backend (Admin SDK) only
  match /ledger/{e}   { allow read: if request.auth.uid == uid; allow write: if false; }
  match /chats/{c}    { allow read: if request.auth.uid == uid; allow write: if false;
    match /messages/{m} { allow read: if request.auth.uid == uid; allow write: if false; } }
}
```
The web shows balance by reading `users/{uid}` (or from the chat response). It never mutates credits.

## Payments (Phase 8)

- **Subscriptions** (tier change): Razorpay subscription webhook → `POST /webhooks/payments` (verify
  signature) → set `users/{uid}.tier` and grant `tier.monthly_tokens` (ledger `grant`). The existing
  `/admin/users/tier` is the internal mutation.
- **Top-up packs** (one-time): payment webhook → add pack tokens to `topup_balance` (ledger `topup`).
- Verify webhook signatures server-side; never trust client "I paid" claims. Map `razorpay_payment_id`
  → entitlement idempotently (store processed payment ids to avoid double-credit on webhook retries).

## What Claude Code must not do here

- No client-side token counting or balance mutation. Ever.
- No debit outside a Firestore transaction. No removing the per-turn / daily ceilings.
- No ungrounded chat. The model answers only from the user's findings.
- Don't merge this subsystem or the payment webhook without the owner reviewing the diff.
