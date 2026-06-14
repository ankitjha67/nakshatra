"""Unit tests for the credit ledger (money path).

Covers the invariants from docs/CREDIT_LEDGER.md and the BUILD_PLAN Phase-4
"Done when": debit decrements correctly, never below zero, spends grant before
topup, respects the daily ceiling, persists topups across a cycle reset, and
writes ledger entries. Pure math is tested directly; persistence is tested
through MemoryStore (single-threaded → same atomic semantics as the Firestore
transaction). Firestore security rules are not unit-tested here (they need the
emulator), see docs/CREDIT_LEDGER.md and web/firestore.rules.
"""
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

from app import credits
from app.billing import MemoryStore, TIERS


UTC = timezone.utc
T0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _bal(grant, topup, *, monthly=500_000, now=T0):
    return credits.Balance(
        tier="pro", grant_balance=grant, topup_balance=topup, monthly_tokens=monthly,
        cycle_start=now, cycle_end=now + relativedelta(months=1),
        daily_tokens_used=0, daily_date=now.date().isoformat(),
    )


# --------------------------- pure debit math ------------------------------- #
def test_debit_spends_grant_first():
    bal, entry = credits.debit(_bal(100, 50), 30, "chat turn", "m1", T0)
    assert bal.grant_balance == 70
    assert bal.topup_balance == 50            # topup untouched until grant exhausted
    assert bal.available == 120
    assert entry["type"] == "debit" and entry["tokens"] == 30 and entry["balance_after"] == 120


def test_debit_spills_into_topup_after_grant():
    bal, entry = credits.debit(_bal(100, 50), 120, "chat turn", "m1", T0)
    assert bal.grant_balance == 0
    assert bal.topup_balance == 30            # 20 of the 120 came from topup
    assert bal.available == 30
    assert entry["balance_after"] == 30


def test_debit_clamps_at_zero_never_negative():
    bal, entry = credits.debit(_bal(100, 50), 1000, "chat turn", "m1", T0)
    assert bal.grant_balance == 0 and bal.topup_balance == 0
    assert bal.available == 0                 # never below zero, even on overshoot
    assert entry["tokens"] == 1000            # ledger records the true cost
    assert entry["balance_after"] == 0
    assert bal.daily_tokens_used == 1000      # daily counter still sees the full cost


def test_debit_exactly_grant_leaves_topup():
    bal, _ = credits.debit(_bal(100, 50), 100, "chat turn", None, T0)
    assert bal.grant_balance == 0 and bal.topup_balance == 50


def test_negative_cost_is_treated_as_zero():
    bal, entry = credits.debit(_bal(100, 50), -5, "x", None, T0)
    assert bal.grant_balance == 100 and bal.topup_balance == 50 and entry["tokens"] == 0


# --------------------------- topup + grant --------------------------------- #
def test_topup_adds_to_topup_balance():
    bal, entry = credits.topup(_bal(10, 0), 100_000, "razorpay pack 100k", "pay_1", T0)
    assert bal.topup_balance == 100_000 and bal.grant_balance == 10
    assert entry["type"] == "topup" and entry["balance_after"] == 100_010


# --------------------------- cycle / daily resets -------------------------- #
def test_cycle_reset_refreshes_grant_keeps_topup():
    # balance whose cycle ended; topup must survive, grant must refresh to monthly
    bal = _bal(5, 200, monthly=500_000)
    later = T0 + relativedelta(months=2)      # well past cycle_end
    bal2, entries = credits.apply_resets(bal, "pro", 500_000, later)
    assert bal2.grant_balance == 500_000      # refreshed
    assert bal2.topup_balance == 200          # untouched by reset
    assert any(e["type"] == "reset" for e in entries)
    # cycle window now contains `later`
    assert bal2.cycle_start <= later < bal2.cycle_end


def test_no_reset_within_cycle():
    bal2, entries = credits.apply_resets(_bal(5, 200), "pro", 500_000, T0 + relativedelta(days=3))
    assert bal2.grant_balance == 5 and entries == []


def test_tier_upgrade_grants_new_allowance_mid_cycle():
    # free user (no grant) upgrades to enterprise three days into the cycle: they must
    # get the enterprise allowance NOW, not wait for the next monthly reset.
    free = credits.Balance(
        tier="free", grant_balance=0, topup_balance=0, monthly_tokens=0,
        cycle_start=T0, cycle_end=T0 + relativedelta(months=1),
        daily_tokens_used=0, daily_date=T0.date().isoformat())
    ent = TIERS["enterprise"]
    bal2, entries = credits.apply_resets(free, ent.key, ent.monthly_tokens, T0 + relativedelta(days=3))
    assert bal2.tier == "enterprise"
    assert bal2.grant_balance == ent.monthly_tokens          # granted immediately
    assert any(e["type"] == "grant" for e in entries)


def test_tier_upgrade_preserves_topup_and_resets_window():
    bal = _bal(50_000, 12_345, monthly=TIERS["basic"].monthly_tokens)
    bal = credits.Balance(**{**bal.__dict__, "tier": "basic"})
    pro = TIERS["pro"]
    later = T0 + relativedelta(days=10)
    bal2, _ = credits.apply_resets(bal, pro.key, pro.monthly_tokens, later)
    assert bal2.grant_balance == pro.monthly_tokens          # upgraded allowance
    assert bal2.topup_balance == 12_345                      # purchased tokens survive
    assert bal2.cycle_start == later                         # fresh month from the upgrade


def test_downgrade_keeps_paid_cycle_balance():
    # downgrade must NOT wipe the allowance the user already paid for this cycle.
    bal = _bal(400_000, 0, monthly=TIERS["pro"].monthly_tokens)
    bal = credits.Balance(**{**bal.__dict__, "tier": "pro"})
    basic = TIERS["basic"]
    bal2, entries = credits.apply_resets(bal, basic.key, basic.monthly_tokens, T0 + relativedelta(days=2))
    assert bal2.tier == "basic"
    assert bal2.grant_balance == 400_000                     # untouched (no upgrade grant)
    assert not any(e["type"] == "grant" for e in entries)


def test_same_tier_read_does_not_regrant():
    bal = _bal(123, 0, monthly=TIERS["pro"].monthly_tokens)  # mid-cycle, partially spent
    bal2, entries = credits.apply_resets(bal, "pro", TIERS["pro"].monthly_tokens, T0 + relativedelta(days=2))
    assert bal2.grant_balance == 123 and entries == []       # no phantom top-up on a plain read


def test_store_upgrade_then_read_shows_new_credits():
    # end-to-end through MemoryStore: a free user with a balance doc upgrades; the next
    # /v1/me-style read (credit_balance with the new tier) reflects the enterprise grant.
    s = MemoryStore()
    assert s.credit_balance("u1", TIERS["free"], now=T0)["available"] == 0
    s.set_tier("u1", "enterprise", source="beta")
    b = s.credit_balance("u1", TIERS["enterprise"], now=T0 + relativedelta(days=1))
    assert b["available"] == TIERS["enterprise"].monthly_tokens


def test_daily_reset_zeroes_counter_on_new_day():
    bal = _bal(100, 0)
    bal = credits.Balance(**{**bal.__dict__, "daily_tokens_used": 7777})
    bal2, _ = credits.apply_resets(bal, "pro", 500_000, T0 + relativedelta(days=1))
    assert bal2.daily_tokens_used == 0


def test_exceeds_daily_ceiling():
    bal = credits.Balance(**{**_bal(100, 0).__dict__, "daily_tokens_used": 200_000})
    assert credits.exceeds_daily(bal, 200_000) is True
    assert credits.exceeds_daily(_bal(100, 0), 200_000) is False


def test_new_balance_opens_with_monthly_grant():
    bal, entry = credits.new_balance("pro", 500_000, T0)
    assert bal.grant_balance == 500_000 and bal.topup_balance == 0
    assert entry["type"] == "grant" and entry["balance_after"] == 500_000


# --------------------------- MemoryStore integration ----------------------- #
def test_store_first_balance_is_opening_grant_and_logs_it():
    s = MemoryStore()
    b = s.credit_balance("u1", TIERS["pro"], now=T0)
    g = TIERS["pro"].monthly_tokens
    assert b["available"] == g and b["grant"] == g and b["topup"] == 0
    led = s.credit_ledger("u1")
    assert led and led[0]["type"] == "grant"


def test_store_debit_decrements_and_writes_ledger():
    s = MemoryStore()
    s.credit_balance("u1", TIERS["pro"], now=T0)              # init 500k
    b = s.credit_debit("u1", TIERS["pro"], 1234, reason="chat turn", ref="msg1", now=T0)
    assert b["available"] == TIERS["pro"].monthly_tokens - 1234
    assert b["daily_used"] == 1234
    led = s.credit_ledger("u1")
    assert led[0]["type"] == "debit" and led[0]["tokens"] == 1234 and led[0]["ref"] == "msg1"


def test_store_debit_never_below_zero():
    s = MemoryStore()
    s.credit_balance("u1", TIERS["basic"], now=T0)            # init 50k
    b = s.credit_debit("u1", TIERS["basic"], 10_000_000, now=T0)
    assert b["available"] == 0                                # clamped, not negative


def test_store_topup_then_debit_order():
    s = MemoryStore()
    g = TIERS["basic"].monthly_tokens
    s.credit_balance("u1", TIERS["basic"], now=T0)            # opening grant
    s.credit_topup("u1", TIERS["basic"], 100_000, reason="pack", ref="pay1", now=T0)
    b = s.credit_debit("u1", TIERS["basic"], g + 10_000, now=T0)  # exhaust grant + 10k from topup
    assert b["grant"] == 0 and b["topup"] == 90_000 and b["available"] == 90_000


def test_store_free_tier_has_no_grant():
    s = MemoryStore()
    b = s.credit_balance("u1", TIERS["free"], now=T0)
    assert b["available"] == 0 and b["monthly_tokens"] == 0
