"""Stress + fraud test for the payments & token-credit paths.

Run against a LOCAL dev server (mock engine/LLM/gateway). It does two things:

  1. LOAD  — fires concurrent mixed traffic (readings, chat, mock checkout) and
     reports throughput + latency percentiles + error rates under peak load.
  2. FRAUD — attempts the known payment/token modus operandi and asserts each is
     blocked (signature forgery, replay, duplicate-event, amount tamper, IDOR,
     cross-user refund, auth bypass, refund double-reversal, unknown pack), and
     PROBES the known concurrency gaps (chat race / per-minute limit) and reports
     observed behaviour honestly.

Boot the server first, e.g.:
  APP_ENV=dev STORE_BACKEND=memory LLM_PROVIDER=mock PAYMENTS_PROVIDER=razorpay \
  RAZORPAY_WEBHOOK_SECRET=whsec_test ADMIN_API_KEY=test-admin-secret \
  uvicorn app.main:app --port 8091
Then:  python scripts/stress_payments_tokens.py
"""
import concurrent.futures as cf
import hashlib
import hmac
import json
import os
import statistics
import time
import urllib.error
import urllib.request

B = os.environ.get("STRESS_BASE", "http://127.0.0.1:8091")
SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
ADMIN = os.environ.get("ADMIN_API_KEY", "test-admin-secret")
BIRTH = {"date": "1990-08-15", "time": "14:30", "tz": "+05:30", "lat": 19.07, "lon": 72.87}


def req(method, path, body=None, key=None, admin=None, sig=None, raw=None):
    h = {}
    if body is not None or raw is not None:
        h["Content-Type"] = "application/json"
    if key:
        h["X-API-Key"] = key
    if admin:
        h["X-Admin-Key"] = admin
    if sig:
        h["X-Razorpay-Signature"] = sig
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(B + path, data=data, method=method, headers=h)
    t0 = time.perf_counter()
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, json.loads(resp.read() or b"{}"), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, _safe(e), time.perf_counter() - t0
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}, time.perf_counter() - t0


def _safe(e):
    try:
        return json.loads(e.read())
    except Exception:
        return {}


def signed(payload):
    raw = json.dumps(payload).encode()
    return raw, hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# 1. LOAD
# --------------------------------------------------------------------------- #
def load_test(total=300, workers=24):
    def op(i):
        m = i % 3
        if m == 0:
            return req("POST", "/v1/reading", {**BIRTH, "report_type": "natal"}, key="pro_dev_key")
        if m == 1:
            return req("POST", "/v1/chat", {"birth": BIRTH, "message": "career?"}, key="pro_dev_key")
        return req("POST", "/mock/razorpay/checkout", {"kind": "topup", "amount_inr": 99}, key="pro_dev_key")

    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(op, range(total)))
    dur = time.perf_counter() - t0
    lat = sorted(r[2] * 1000 for r in res)
    ok = sum(1 for r in res if r[0] == 200)
    codes = {}
    for r in res:
        codes[r[0]] = codes.get(r[0], 0) + 1
    pct = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))]
    print(f"\n=== LOAD: {total} reqs / {workers} workers ===")
    print(f"  wall={dur:.2f}s  throughput={total/dur:.1f} req/s  ok={ok}/{total}")
    print(f"  latency ms  p50={pct(.50):.0f}  p95={pct(.95):.0f}  p99={pct(.99):.0f}  max={lat[-1]:.0f}")
    print(f"  status codes: {codes}")


# --------------------------------------------------------------------------- #
# 2. FRAUD MATRIX
# --------------------------------------------------------------------------- #
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name} {('— ' + detail) if detail else ''}")


def fraud_matrix():
    print("\n=== FRAUD MATRIX ===")
    # webhook: unsigned
    raw, _ = signed({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "f1", "amount": 9900, "notes": {"user_id": "u_pro"}}}}})
    s, _, _ = req("POST", "/webhooks/payments", raw=raw)
    check("webhook missing signature rejected", s == 400, f"HTTP {s}")
    # webhook: bad signature
    s, _, _ = req("POST", "/webhooks/payments", raw=raw, sig="deadbeef")
    check("webhook bad signature rejected", s == 400, f"HTTP {s}")
    # webhook: tampered amount after signing (re-serialize, keep old sig)
    body = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "f2", "amount": 9900, "notes": {"user_id": "u_pro"}}}}}
    raw2, sig2 = signed(body)
    body["payload"]["payment"]["entity"]["amount"] = 79900   # claim the ₹799 pack
    tampered = json.dumps(body).encode()
    s, _, _ = req("POST", "/webhooks/payments", raw=tampered, sig=sig2)
    check("tampered amount (stale signature) rejected", s == 400, f"HTTP {s}")
    # replay: same signed valid event twice -> credited once
    p = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "rep1", "amount": 9900, "notes": {"user_id": "u_fraud1"}}}}}
    raw, sig = signed(p)
    a, ab, _ = req("POST", "/webhooks/payments", raw=raw, sig=sig)
    b, bb, _ = req("POST", "/webhooks/payments", raw=raw, sig=sig)
    check("replay does not double-credit", ab.get("status") == "topup" and bb.get("status") == "duplicate", f"{ab.get('status')}/{bb.get('status')}")
    # duplicate event: payment.captured + order.paid same id -> once
    op = {"event": "order.paid", "payload": {"payment": {"entity": {"id": "rep1", "amount": 9900, "notes": {"user_id": "u_fraud1"}}}}}
    raw, sig = signed(op)
    s, ob, _ = req("POST", "/webhooks/payments", raw=raw, sig=sig)
    check("order.paid after captured not credited", ob.get("status") == "ignored", ob.get("status"))
    # auth: no key
    s, _, _ = req("POST", "/v1/chat", {"birth": BIRTH, "message": "x"})
    check("unauthenticated request blocked", s == 401, f"HTTP {s}")
    # admin: wrong key
    s, _, _ = req("POST", "/admin/refunds/x/approve", {}, admin="wrong")
    check("admin wrong key blocked", s in (401, 403), f"HTTP {s}")
    # IDOR: another user reads the owner's async job (owner = enterprise: high rate limit)
    s, jb, _ = req("POST", "/v1/reading/async", {**BIRTH}, key="ent_dev_key")
    job = jb.get("job_id")
    if not job:
        check("async job created for IDOR test", False, f"create HTTP {s}")
    else:
        time.sleep(0.3)
        s, _, _ = req("GET", f"/v1/reading/{job}", key="pro_dev_key")
        check("IDOR on async job blocked", s == 404, f"HTTP {s}")
        s2, _, _ = req("GET", f"/v1/reading/{job}", key="ent_dev_key")
        check("owner can read own async job", s2 == 200, f"HTTP {s2}")
    # unknown top-up pack via mock
    s, _, _ = req("POST", "/mock/razorpay/checkout", {"kind": "topup", "amount_inr": 123}, key="pro_dev_key")
    check("unknown top-up pack rejected", s == 422, f"HTTP {s}")
    # cross-user refund request
    pc = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "xu1", "amount": 9900, "notes": {"user_id": "u_pro"}}}}}
    raw, sig = signed(pc)
    req("POST", "/webhooks/payments", raw=raw, sig=sig)
    s, _, _ = req("POST", "/v1/refunds", {"payment_id": "xu1", "reason": "mine!"}, key="basic_dev_key")
    check("cross-user refund request blocked", s == 404, f"HTTP {s}")
    # refund double-reversal idempotent
    rf = {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rf_x", "payment_id": "xu1"}}}}
    raw, sig = signed(rf)
    r1, rb1, _ = req("POST", "/webhooks/payments", raw=raw, sig=sig)
    r2, rb2, _ = req("POST", "/webhooks/payments", raw=raw, sig=sig)
    check("refund not double-reversed", rb1.get("status") == "refund" and rb2.get("status") == "duplicate", f"{rb1.get('status')}/{rb2.get('status')}")


# --------------------------------------------------------------------------- #
# 3. CONCURRENCY PROBES (known gaps — report, don't assert)
# --------------------------------------------------------------------------- #
def concurrency_probes():
    print("\n=== CONCURRENCY PROBES (known gaps; informational) ===")
    # per-minute rate limit under burst (basic per_minute=10)
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        res = list(ex.map(lambda _: req("POST", "/v1/reading", {**BIRTH}, key="basic_dev_key")[0], range(40)))
    blocked = sum(1 for c in res if c == 429)
    print(f"  per-minute limit: 40 concurrent basic reqs -> {blocked} got 429 (in-process limiter; "
          f"distributed gap tracked in SECURITY.md)")
    # chat race: many concurrent chats for one user
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        res = list(ex.map(lambda _: req("POST", "/v1/chat", {"birth": BIRTH, "message": "hi"}, key="ent_dev_key")[0], range(20)))
    ok = sum(1 for c in res if c == 200)
    print(f"  chat race: 20 concurrent chats (ample balance) -> {ok} succeeded as expected; "
          f"the check-then-debit race only risks overspend NEAR zero balance — tracked in SECURITY.md")


if __name__ == "__main__":
    print(f"Target: {B}")
    h = req("GET", "/health")
    if h[0] != 200:
        raise SystemExit(f"server not up at {B} (got {h[0]})")
    fraud_matrix()         # before the load burst, so rate buckets are fresh
    concurrency_probes()
    load_test()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n=== FRAUD MATRIX: {passed}/{len(RESULTS)} blocked as expected ===")
    if passed != len(RESULTS):
        print("  FAILURES:", [n for n, ok, _ in RESULTS if not ok])
