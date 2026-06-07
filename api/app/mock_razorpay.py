"""Mock Razorpay gateway — DEV/TEST ONLY.

Builds correctly-*signed* webhook payloads (subscription charge, one-time top-up,
refund) so they flow through the real `handle_razorpay_webhook` path — signature
verification, idempotency, crediting/reversal — without contacting Razorpay.
Gated to non-prod in main.py. Used by the /mock/razorpay/* endpoints and the
payments stress test.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid


def _sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _wrap(payload: dict, secret: str) -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    return raw, _sign(raw, secret)


def checkout_event(kind: str, uid: str, secret: str, *, tier: str | None = None,
                   amount_inr: int = 0) -> tuple[str, bytes, str]:
    """Return (payment_id, raw_body, signature) for a successful purchase."""
    pid = "pay_" + uuid.uuid4().hex[:16]
    amount = int(amount_inr) * 100  # paise
    if kind == "subscription":
        sid = "sub_" + uuid.uuid4().hex[:12]
        payload = {"event": "subscription.charged", "payload": {
            "subscription": {"entity": {"id": sid, "notes": {"user_id": uid, "tier": tier}}},
            "payment": {"entity": {"id": pid, "amount": amount, "invoice_id": "inv_" + uuid.uuid4().hex[:10]}},
        }}
    else:  # one-time top-up
        payload = {"event": "payment.captured", "payload": {
            "payment": {"entity": {"id": pid, "amount": amount, "notes": {"user_id": uid}}}}}
    raw, sig = _wrap(payload, secret)
    return pid, raw, sig


def refund_event(payment_id: str, secret: str) -> tuple[str, bytes, str]:
    """Return (refund_id, raw_body, signature) for a processed refund."""
    rid = "rfnd_" + uuid.uuid4().hex[:12]
    payload = {"event": "refund.processed", "payload": {
        "refund": {"entity": {"id": rid, "payment_id": payment_id}}}}
    raw, sig = _wrap(payload, secret)
    return rid, raw, sig
