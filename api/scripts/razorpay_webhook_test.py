#!/usr/bin/env python
"""End-to-end Razorpay webhook harness (the money path).

Posts correctly-SIGNED events through the real `/webhooks/payments` endpoint and
checks the outcome: a subscription charge grants the tier, a replay is idempotent
(never double-grants), and a tampered signature is rejected (400).

Self-contained (stdlib only). Point it at a running API and give the same webhook
secret the service is configured with.

  python scripts/razorpay_webhook_test.py \
      --base https://jyotish-api-...run.app \
      --secret "$(gcloud secrets versions access latest --secret=razorpay-webhook-secret)" \
      --uid <firebase-uid> --tier pro --charge-id ch_$(date +%s)

Against prod the service must have payments_provider=razorpay and the matching
RAZORPAY_WEBHOOK_SECRET; otherwise the endpoint returns 501/503 by design.
"""
import argparse
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request


def sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def post(base: str, raw: bytes, sig: str):
    req = urllib.request.Request(
        base.rstrip("/") + "/webhooks/payments", data=raw, method="POST",
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def subscription_charged(uid: str, tier: str, charge_id: str) -> bytes:
    body = {"event": "subscription.charged", "payload": {
        "payment": {"entity": {"id": charge_id, "amount": 99900}},
        "subscription": {"entity": {"id": "sub_test", "notes": {"user_id": uid, "tier": tier}}}}}
    return json.dumps(body).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--uid", required=True)
    ap.add_argument("--tier", default="pro")
    ap.add_argument("--charge-id", default="ch_test_0001")
    a = ap.parse_args()

    raw = subscription_charged(a.uid, a.tier, a.charge_id)
    good = sign(raw, a.secret)
    ok = True

    print("1) valid subscription.charged ->", end=" ")
    st, body = post(a.base, raw, good)
    print(st, body)
    ok &= (st == 200 and '"subscription"' in body)

    print("2) replay (idempotent)        ->", end=" ")
    st, body = post(a.base, raw, good)
    print(st, body)
    ok &= (st == 200 and '"duplicate"' in body)

    print("3) tampered signature (->400) ->", end=" ")
    st, body = post(a.base, raw, good[:-1] + ("0" if good[-1] != "0" else "1"))
    print(st, body)
    ok &= (st == 400)

    print("\nRESULT:", "PASS" if ok else "FAIL",
          "(grant once, idempotent replay, bad-signature rejected)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
