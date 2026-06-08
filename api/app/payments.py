"""Payment webhook handling (Razorpay), MONEY PATH, review carefully.

The browser is never trusted with entitlements. A signed webhook from the
provider is the only thing that changes a tier or adds top-up credits. This
module:
  * verifies the Razorpay HMAC-SHA256 signature over the RAW body,
  * routes subscription events → tier change + monthly grant,
  * routes one-time payments → a top-up pack (by INR amount),
  * is idempotent: every entity is marked processed first, so webhook retries
    (Razorpay redelivers) never double-credit.

All persistence is the store's job; this stays pure/testable (the store and a
settings-like object are injected).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

# One-time top-up packs: INR (rupees) -> tokens. Server-authoritative; the amount
# on the verified payment selects the pack (never a client-sent token count).
TOPUP_PACKS: dict[int, int] = {99: 100_000, 299: 350_000, 799: 1_000_000}


class PaymentError(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def verify_razorpay_signature(raw: bytes, signature: str | None, secret: str) -> bool:
    """True iff HMAC-SHA256(raw, secret) matches the X-Razorpay-Signature header."""
    if not (signature and secret):
        return False
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def keys_configured(key_id: str, key_secret: str) -> bool:
    """True only when real (non-placeholder) Razorpay API keys are present."""
    return bool(key_id and key_secret and not key_id.startswith("REPLACE")
                and not key_secret.startswith("REPLACE"))


def create_razorpay_order(amount_inr: int, key_id: str, key_secret: str,
                          notes: dict, receipt: str) -> dict:
    """Create a Razorpay order for the discounted amount. Returns the order JSON.
    Called only when real keys are configured; raises PaymentError on failure."""
    import base64
    import urllib.error
    import urllib.request

    body = json.dumps({
        "amount": int(amount_inr) * 100,            # paise
        "currency": "INR",
        "receipt": receipt,
        "notes": {k: str(v) for k, v in (notes or {}).items()},
    }).encode("utf-8")
    auth = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        "https://api.razorpay.com/v1/orders", data=body, method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:                       # noqa: BLE001
        raise PaymentError(502, f"Razorpay order creation failed ({e.code}).")
    except Exception:                                          # noqa: BLE001
        raise PaymentError(502, "Could not reach the payment gateway.")


def _razorpay_post(path: str, body: dict, key_id: str, key_secret: str) -> dict:
    import base64
    import urllib.error
    import urllib.request
    auth = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        "https://api.razorpay.com/v1" + path,
        data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:                       # noqa: BLE001
        raise PaymentError(502, f"Razorpay request failed ({e.code}).")
    except Exception:                                          # noqa: BLE001
        raise PaymentError(502, "Could not reach the payment gateway.")


def create_razorpay_subscription(plan_id: str, key_id: str, key_secret: str, notes: dict,
                                 total_count: int = 12, offer_id: str | None = None) -> dict:
    """Create a recurring Razorpay subscription on a per-tier plan. Returns the
    subscription JSON (its id drives the Checkout widget). A discount is applied
    via a Razorpay Offer id when one is configured for the tier."""
    body: dict = {
        "plan_id": plan_id,
        "total_count": int(total_count),       # number of billing cycles
        "customer_notify": 1,
        "notes": {k: str(v) for k, v in (notes or {}).items()},
    }
    if offer_id:
        body["offer_id"] = offer_id
    return _razorpay_post("/subscriptions", body, key_id, key_secret)


def _entity(payload: dict, key: str) -> dict:
    ent = (((payload.get("payload") or {}).get(key) or {}).get("entity")) or {}
    return ent if isinstance(ent, dict) else {}


def handle_razorpay_webhook(raw: bytes, signature: str | None, secret: str,
                            store: Any, tiers: dict) -> dict:
    """Verify + route a Razorpay webhook. Returns a small status dict.
    Raises PaymentError(400) on a bad signature."""
    if not verify_razorpay_signature(raw, signature, secret):
        raise PaymentError(400, "Invalid webhook signature")

    try:
        payload = json.loads(raw or b"{}")
    except (ValueError, TypeError):
        raise PaymentError(400, "Malformed webhook body")

    event = str(payload.get("event") or "")
    payment = _entity(payload, "payment")
    sub = _entity(payload, "subscription")
    refund = _entity(payload, "refund")

    # --- refund → reverse credited tokens (and downgrade a refunded subscription) ---
    if event.startswith("refund.") or refund.get("id"):
        rid = refund.get("id") or ""
        pay_id = refund.get("payment_id") or payment.get("id") or ""
        if not (rid and pay_id):
            return {"status": "ignored", "reason": "no refund/payment id"}
        if not store.mark_payment_processed(f"refund:{rid}"):
            return {"status": "duplicate", "id": rid}
        rec = store.get_payment(pay_id) or {}
        uid = rec.get("uid")
        if not uid:
            return {"status": "ignored", "reason": "refund for unknown payment"}
        tokens = int(rec.get("tokens") or 0)
        if rec.get("kind") == "subscription":
            store.set_tier(uid, "free")                # refunded subscription → downgrade
            tier = tiers["free"]
        else:
            tier = tiers.get((store.get_user(uid) or {}).get("tier", "free"), tiers["free"])
        store.credit_refund(uid, tier, tokens, reason=f"refund {rid}", ref=pay_id)
        store.set_payment_status(pay_id, "refunded")
        return {"status": "refund", "uid": uid, "tokens": tokens, "payment_id": pay_id}

    # --- subscription: grant exactly once per CHARGE (not per lifecycle event) ---
    # Razorpay emits many subscription.* events (authenticated/activated/updated/...)
    # with the same subscription id; only `subscription.charged` is a real paid period.
    if event == "subscription.charged":
        notes = sub.get("notes") or payment.get("notes") or {}
        uid = notes.get("user_id") or notes.get("uid")
        tier = notes.get("tier")
        if not (uid and tier in tiers):
            return {"status": "ignored", "reason": "missing uid/tier in subscription notes"}
        charge_id = payment.get("id") or sub.get("id") or ""
        if not charge_id:
            return {"status": "ignored", "reason": "no charge id"}
        if not store.mark_payment_processed(f"subgrant:{charge_id}"):
            return {"status": "duplicate", "id": charge_id}
        store.set_tier(uid, tier)
        store.credit_grant(uid, tiers[tier], reason="subscription charged")
        store.record_payment(charge_id, {
            "uid": uid, "kind": "subscription", "tier": tier,
            "tokens": tiers[tier].monthly_tokens,
            "amount_inr": int(payment.get("amount") or 0) // 100, "status": "captured"})
        return {"status": "subscription", "uid": uid, "tier": tier}

    # --- one-time top-up: credit once per PAYMENT id (event-independent) ---
    # `invoice_id` is present on subscription charges; require it absent so a
    # subscription payment can never be mistaken for a top-up pack of equal amount.
    if event == "payment.captured" and not payment.get("invoice_id"):
        pid = payment.get("id") or ""
        notes = payment.get("notes") or {}
        uid = notes.get("user_id") or notes.get("uid")
        amount_inr = int(payment.get("amount") or 0) // 100       # paise -> rupees
        tokens = TOPUP_PACKS.get(amount_inr)
        if not (pid and uid and tokens):
            return {"status": "ignored", "reason": "no matching pack or uid"}
        # Key on the payment id ALONE so payment.captured + order.paid (same id) can't double-credit.
        if not store.mark_payment_processed(f"topup:{pid}"):
            return {"status": "duplicate", "id": pid}
        user = store.get_user(uid) or {}
        tier = tiers.get(user.get("tier", "free"), tiers["free"])
        store.credit_topup(uid, tier, tokens, reason=f"top-up ₹{amount_inr}", ref=pid)
        store.record_payment(pid, {
            "uid": uid, "kind": "topup", "tokens": tokens,
            "amount_inr": amount_inr, "status": "captured"})
        return {"status": "topup", "uid": uid, "tokens": tokens}

    return {"status": "ignored", "reason": f"unhandled event {event}"}
