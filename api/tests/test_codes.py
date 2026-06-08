"""Beta / discount access codes: hashing, redemption, single-use, expiry."""
from datetime import datetime, timedelta, timezone

from app.billing import MemoryStore
from app.codes import generate_plaintext, hash_code, normalize


def test_hash_is_stable_and_format_insensitive():
    c = "NK-ABCD-EFGH-JKLM"
    assert hash_code(c) == hash_code(" nk-abcd-efgh-jklm ")     # case/space/dash agnostic
    assert hash_code(c) != hash_code("NK-ABCD-EFGH-JKLN")       # different code -> different hash
    assert normalize("nk-ab cd") == "NKABCD"
    assert len(hash_code(c)) == 64                              # sha256 hex


def test_generate_is_random_and_well_formed():
    codes = {generate_plaintext() for _ in range(200)}
    assert len(codes) == 200                                    # no collisions in a batch
    assert all(c.startswith("NK-") and c.count("-") == 3 for c in codes)


def test_beta_code_grants_then_is_single_use():
    s = MemoryStore()
    code = generate_plaintext()
    s.code_create(hash_code(code), {"kind": "beta", "tier": "enterprise", "max_uses": 1,
                                    "uses": 0, "redeemed_by": [], "active": True})
    r = s.code_redeem(hash_code(code), "userA")
    assert r["ok"] and r["meta"]["tier"] == "enterprise"
    # same user can't reuse
    assert s.code_redeem(hash_code(code), "userA")["ok"] is False
    # another user can't use a 1-use code that's spent
    assert s.code_redeem(hash_code(code), "userB")["ok"] is False


def test_multi_use_code():
    s = MemoryStore()
    code = generate_plaintext()
    s.code_create(hash_code(code), {"kind": "beta", "tier": "pro", "max_uses": 3,
                                    "uses": 0, "redeemed_by": [], "active": True})
    assert s.code_redeem(hash_code(code), "u1")["ok"]
    assert s.code_redeem(hash_code(code), "u2")["ok"]
    assert s.code_redeem(hash_code(code), "u3")["ok"]
    assert s.code_redeem(hash_code(code), "u4")["ok"] is False   # exhausted


def test_invalid_inactive_and_expired():
    s = MemoryStore()
    assert s.code_redeem(hash_code("NOPE"), "u1")["ok"] is False  # unknown
    code = generate_plaintext()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    s.code_create(hash_code(code), {"kind": "beta", "tier": "pro", "max_uses": 1,
                                    "uses": 0, "redeemed_by": [], "active": True, "expires_at": past})
    assert s.code_redeem(hash_code(code), "u1")["ok"] is False    # expired


def test_list_codes_never_exposes_plaintext():
    s = MemoryStore()
    code = generate_plaintext()
    s.code_create(hash_code(code), {"kind": "beta", "tier": "enterprise", "max_uses": 1, "uses": 0})
    listed = s.list_codes()
    assert len(listed) == 1
    row = listed[0]
    assert normalize(code) not in str(row)          # plaintext never present
    assert row["id"] == hash_code(code)              # the hash (irreversible), never the code


def test_deactivate_blocks_redemption():
    s = MemoryStore()
    code = generate_plaintext()
    h = hash_code(code)
    s.code_create(h, {"kind": "beta", "tier": "pro", "max_uses": 5, "uses": 0,
                      "redeemed_by": [], "active": True})
    assert s.code_set_active(h, False) is True
    assert s.code_redeem(h, "u1")["ok"] is False     # deactivated -> unredeemable
    assert s.code_set_active(h, True) is True
    assert s.code_redeem(h, "u1")["ok"] is True       # reactivated -> works again
    assert s.code_set_active("nonexistent", False) is False
