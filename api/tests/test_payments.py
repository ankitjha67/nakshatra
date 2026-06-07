"""Unit tests for the Razorpay payment webhook (money path).

Covers BUILD_PLAN Phase-8 "Done when": a subscription moves tier and grants
tokens; a top-up pack adds top-up; replays don't double-credit. Plus signature
verification. Logic is tested directly with a MemoryStore (no HTTP/env plumbing).
"""
import hashlib
import hmac
import json

import pytest

from app.billing import MemoryStore, TIERS
from app.payments import (
    handle_razorpay_webhook, verify_razorpay_signature, PaymentError, TOPUP_PACKS,
)

SECRET = "whsec_test"


def _signed(payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


def _sub(event, uid, tier, sub_id="sub_1"):
    return {"event": event, "payload": {"subscription": {"entity": {"id": sub_id, "notes": {"user_id": uid, "tier": tier}}}}}


def _payment(amount_paise, uid, pay_id="pay_1", event="payment.captured"):
    return {"event": event, "payload": {"payment": {"entity": {"id": pay_id, "amount": amount_paise, "notes": {"user_id": uid}}}}}


# --------------------------- signature ------------------------------------- #
def test_signature_valid_and_invalid():
    raw, sig = _signed({"event": "x"})
    assert verify_razorpay_signature(raw, sig, SECRET) is True
    assert verify_razorpay_signature(raw, "deadbeef", SECRET) is False
    assert verify_razorpay_signature(raw, sig, "wrong") is False
    assert verify_razorpay_signature(raw, None, SECRET) is False


def test_bad_signature_raises():
    raw, _ = _signed({"event": "payment.captured"})
    with pytest.raises(PaymentError) as ei:
        handle_razorpay_webhook(raw, "bad", SECRET, MemoryStore(), TIERS)
    assert ei.value.code == 400


# --------------------------- subscription ---------------------------------- #
def test_subscription_sets_tier_and_grants_tokens():
    s = MemoryStore()
    raw, sig = _signed(_sub("subscription.charged", "u1", "pro"))
    res = handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)
    assert res["status"] == "subscription" and res["tier"] == "pro"
    bal = s.credit_balance("u1", TIERS["pro"])
    assert bal["grant"] == TIERS["pro"].monthly_tokens == 500_000
    assert any(e["type"] in ("grant",) for e in s.credit_ledger("u1"))


def test_subscription_missing_notes_ignored():
    s = MemoryStore()
    payload = {"event": "subscription.charged", "payload": {"subscription": {"entity": {"id": "sub_x", "notes": {}}}}}
    raw, sig = _signed(payload)
    assert handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)["status"] == "ignored"


# --------------------------- top-up ---------------------------------------- #
def test_topup_pack_adds_topup_balance():
    s = MemoryStore()
    raw, sig = _signed(_payment(29900, "u1"))           # ₹299 -> 350k
    res = handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)
    assert res["status"] == "topup" and res["tokens"] == TOPUP_PACKS[299] == 350_000
    bal = s.credit_balance("u1", TIERS["free"])
    assert bal["topup"] == 350_000 and bal["available"] == 350_000


def test_topup_unknown_amount_ignored():
    s = MemoryStore()
    raw, sig = _signed(_payment(12300, "u1"))            # ₹123 — no pack
    assert handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)["status"] == "ignored"


# --------------------------- idempotency ----------------------------------- #
def test_replay_does_not_double_credit():
    s = MemoryStore()
    raw, sig = _signed(_payment(9900, "u1"))             # ₹99 -> 100k
    first = handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)
    second = handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)   # retry, same entity
    assert first["status"] == "topup"
    assert second["status"] == "duplicate"
    assert s.credit_balance("u1", TIERS["free"])["topup"] == 100_000   # credited once


def test_subscription_replay_no_double_grant():
    s = MemoryStore()
    raw, sig = _signed(_sub("subscription.charged", "u1", "basic"))
    handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)
    # simulate top-up so a second grant (which resets grant_balance) would be visible
    s.credit_topup("u1", TIERS["basic"], 5_000, reason="t")
    again = handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)
    assert again["status"] == "duplicate"
    bal = s.credit_balance("u1", TIERS["basic"])
    assert bal["grant"] == 50_000 and bal["topup"] == 5_000


def _refund(payment_id, refund_id="rfnd_1"):
    return {"event": "refund.processed", "payload": {"refund": {"entity": {"id": refund_id, "payment_id": payment_id}}}}


# --- refunds reverse credits -------------------------------------------------- #
def test_refund_reverses_topup_and_marks_payment():
    s = MemoryStore()
    cap, sig = _signed(_payment(29900, "u1", pay_id="pay_R"))    # ₹299 -> 350k
    assert handle_razorpay_webhook(cap, sig, SECRET, s, TIERS)["status"] == "topup"
    assert s.credit_balance("u1", TIERS["free"])["topup"] == 350_000
    raw, sig2 = _signed(_refund("pay_R"))
    res = handle_razorpay_webhook(raw, sig2, SECRET, s, TIERS)
    assert res["status"] == "refund" and res["tokens"] == 350_000
    assert s.credit_balance("u1", TIERS["free"])["topup"] == 0          # reversed
    assert s.get_payment("pay_R")["status"] == "refunded"


def test_refund_is_idempotent():
    s = MemoryStore()
    cap, sig = _signed(_payment(9900, "u1", pay_id="pay_R2"))
    handle_razorpay_webhook(cap, sig, SECRET, s, TIERS)
    raw, sig2 = _signed(_refund("pay_R2", refund_id="rfnd_2"))
    assert handle_razorpay_webhook(raw, sig2, SECRET, s, TIERS)["status"] == "refund"
    assert handle_razorpay_webhook(raw, sig2, SECRET, s, TIERS)["status"] == "duplicate"
    assert s.credit_balance("u1", TIERS["free"])["topup"] == 0          # not over-reversed


def test_refund_of_subscription_downgrades_to_free():
    s = MemoryStore()
    raw, sig = _signed(_sub("subscription.charged", "u1", "pro", sub_id="sub_R"))
    handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)
    assert s.get_user("u1")["tier"] == "pro" and s.credit_balance("u1", TIERS["pro"])["grant"] == 500_000
    rraw, rsig = _signed(_refund("sub_R", refund_id="rfnd_3"))
    res = handle_razorpay_webhook(rraw, rsig, SECRET, s, TIERS)
    assert res["status"] == "refund"
    assert s.get_user("u1")["tier"] == "free"
    assert s.credit_balance("u1", TIERS["free"])["grant"] == 0          # period grant reversed


def test_unhandled_event_ignored():
    s = MemoryStore()
    raw, sig = _signed({"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_z"}}}})
    assert handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)["status"] == "ignored"


# --- regression: the two double-credit bugs the audit found ------------------ #
def test_order_paid_after_captured_does_not_double_credit():
    # Razorpay delivers BOTH payment.captured and order.paid for one payment.
    s = MemoryStore()
    cap, sig1 = _signed(_payment(9900, "u1", pay_id="pay_X", event="payment.captured"))
    op = {"event": "order.paid", "payload": {"payment": {"entity": {"id": "pay_X", "amount": 9900, "notes": {"user_id": "u1"}}}}}
    raw2 = json.dumps(op).encode(); sig2 = hmac.new(SECRET.encode(), raw2, hashlib.sha256).hexdigest()
    assert handle_razorpay_webhook(cap, sig1, SECRET, s, TIERS)["status"] == "topup"
    assert handle_razorpay_webhook(raw2, sig2, SECRET, s, TIERS)["status"] == "ignored"   # order.paid not credited
    assert s.credit_balance("u1", TIERS["free"])["topup"] == 100_000                       # once only


def test_subscription_noncharge_events_do_not_grant():
    s = MemoryStore()
    for ev in ("subscription.authenticated", "subscription.activated", "subscription.updated"):
        raw, sig = _signed(_sub(ev, "u1", "pro"))
        assert handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)["status"] == "ignored"
    # nothing granted yet
    assert s.credit_balance("u1", TIERS["free"])["available"] == 0


def test_subscription_charge_amount_equal_to_pack_is_not_a_topup():
    # A Basic sub charge is ₹299 — same as the ₹299 top-up pack. invoice_id must prevent a topup.
    s = MemoryStore()
    pay = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_sub1", "amount": 29900, "invoice_id": "inv_1", "notes": {"user_id": "u1"}}}}}
    raw = json.dumps(pay).encode(); sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert handle_razorpay_webhook(raw, sig, SECRET, s, TIERS)["status"] == "ignored"
    assert s.credit_balance("u1", TIERS["free"])["topup"] == 0
