"""Credit-ledger math — PURE and deterministic (no I/O).

This is the money path. All the rules live here in one place so they can be
read and unit-tested in isolation: lazy cycle reset (monthly grant refresh),
daily reset, and the **grant-first-then-topup** debit with hard clamping at zero.
Persistence and atomicity are the store's job (see billing.py); *correctness*
is here. Time is always injected (`now`, a tz-aware datetime) so behaviour is
fully testable.

Time fields (`cycle_start`, `cycle_end`, ledger `ts`) are tz-aware `datetime`s.
The Firestore client serialises those to native `Timestamp`s on write; the API
boundary exposes them as ISO-8601 strings (see `Balance.as_public`). `daily_date`
stays a "YYYY-MM-DD" string (it's a calendar-day key, not an instant).

Invariants (enforced + tested):
  - available == grant_balance + topup_balance, and neither balance ever < 0.
  - a debit spends grant_balance first, the remainder from topup_balance.
  - the ledger records the full turn `cost` even if it slightly overshoots the
    last credits (the LLM call already happened); balances clamp at 0, so the
    next pre-check blocks. The per-turn output cap keeps any overshoot tiny.
  - topup_balance is never touched by a cycle reset.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from dateutil.relativedelta import relativedelta

# Per-user/day abuse ceiling (tokens), independent of balance. Stops runaway
# loops even if a user has a large balance. Tunable via config (Settings).
DAILY_TOKEN_CEILING = 200_000

LedgerType = str  # "grant" | "debit" | "topup" | "refund" | "reset"


@dataclass(frozen=True)
class Balance:
    tier: str
    grant_balance: int          # resets each cycle to tier.monthly_tokens
    topup_balance: int          # purchased; persists across cycles
    monthly_tokens: int         # cached from tier at last grant (audit)
    cycle_start: datetime       # tz-aware; stored as a Firestore Timestamp
    cycle_end: datetime         # tz-aware; stored as a Firestore Timestamp
    daily_tokens_used: int      # resets daily (abuse ceiling)
    daily_date: str             # "YYYY-MM-DD"

    @property
    def available(self) -> int:
        return self.grant_balance + self.topup_balance

    def as_public(self) -> dict:
        """JSON-stable shape for the API (datetimes → ISO strings)."""
        return {"grant": self.grant_balance, "topup": self.topup_balance,
                "available": self.available, "daily_used": self.daily_tokens_used,
                "tier": self.tier, "monthly_tokens": self.monthly_tokens,
                "cycle_start": self.cycle_start.isoformat(),
                "cycle_end": self.cycle_end.isoformat()}


def _entry(type_: LedgerType, tokens: int, balance_after: int,
           reason: str, ref: str | None, now: datetime) -> dict:
    return {"type": type_, "tokens": int(tokens), "balance_after": int(balance_after),
            "reason": reason, "ref": ref, "ts": now}


def new_balance(tier_key: str, monthly_tokens: int, now: datetime) -> tuple[Balance, dict]:
    """Initial balance for a user's first credit access: the opening monthly grant."""
    monthly_tokens = max(0, int(monthly_tokens))
    bal = Balance(
        tier=tier_key, grant_balance=monthly_tokens, topup_balance=0,
        monthly_tokens=monthly_tokens,
        cycle_start=now, cycle_end=now + relativedelta(months=1),
        daily_tokens_used=0, daily_date=now.date().isoformat(),
    )
    return bal, _entry("grant", monthly_tokens, bal.available, "opening monthly grant", None, now)


def apply_resets(bal: Balance, tier_key: str, monthly_tokens: int,
                 now: datetime) -> tuple[Balance, list[dict]]:
    """Lazy cycle + daily resets. Returns the (possibly) updated balance and any
    ledger entries to append (one `reset` entry if the cycle rolled over)."""
    monthly_tokens = max(0, int(monthly_tokens))
    entries: list[dict] = []
    bal = replace(bal, tier=tier_key)

    # --- cycle reset: refresh grant to the (current) tier's monthly allowance ---
    if now >= bal.cycle_end:
        # advance the window to the cycle containing `now` (collapse missed cycles)
        cstart = bal.cycle_end
        while now >= cstart + relativedelta(months=1):
            cstart = cstart + relativedelta(months=1)
        bal = replace(bal,
                      grant_balance=monthly_tokens, monthly_tokens=monthly_tokens,
                      cycle_start=cstart, cycle_end=cstart + relativedelta(months=1))
        entries.append(_entry("reset", monthly_tokens, bal.available, "monthly grant reset", None, now))

    # --- daily reset: abuse counter rolls at the date boundary ---
    today = now.date().isoformat()
    if bal.daily_date != today:
        bal = replace(bal, daily_tokens_used=0, daily_date=today)

    return bal, entries


def debit(bal: Balance, cost: int, reason: str, ref: str | None,
          now: datetime) -> tuple[Balance, dict]:
    """Spend grant first, then topup; clamp each at 0. Bump the daily counter by
    the full cost. The ledger entry records the full `cost` and the resulting
    available balance (which is 0 on an overshoot)."""
    cost = max(0, int(cost))
    from_grant = min(bal.grant_balance, cost)
    from_topup = min(bal.topup_balance, cost - from_grant)
    bal = replace(bal,
                  grant_balance=bal.grant_balance - from_grant,
                  topup_balance=bal.topup_balance - from_topup,
                  daily_tokens_used=bal.daily_tokens_used + cost)
    return bal, _entry("debit", cost, bal.available, reason, ref, now)


def topup(bal: Balance, tokens: int, reason: str, ref: str | None,
          now: datetime) -> tuple[Balance, dict]:
    """Add purchased tokens to topup_balance (persists across cycles)."""
    tokens = max(0, int(tokens))
    bal = replace(bal, topup_balance=bal.topup_balance + tokens)
    return bal, _entry("topup", tokens, bal.available, reason, ref, now)


def grant(bal: Balance, monthly_tokens: int, reason: str,
          now: datetime) -> tuple[Balance, dict]:
    """Explicit monthly grant (e.g. on a subscription change) — resets the cycle
    window now and sets grant_balance to the tier allowance. topup untouched."""
    monthly_tokens = max(0, int(monthly_tokens))
    bal = replace(bal,
                  grant_balance=monthly_tokens, monthly_tokens=monthly_tokens,
                  cycle_start=now, cycle_end=now + relativedelta(months=1))
    return bal, _entry("grant", monthly_tokens, bal.available, reason, None, now)


def exceeds_daily(bal: Balance, ceiling: int) -> bool:
    """True if the user has hit the per-day abuse ceiling (chat pre-check, Phase 5)."""
    return bal.daily_tokens_used >= max(0, int(ceiling))
