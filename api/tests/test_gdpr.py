"""GDPR data-subject rights: export returns the user's data; delete purges it."""
from app.billing import MemoryStore, TIERS


def test_export_returns_user_data():
    s = MemoryStore()
    s.credit_balance("u1", TIERS["pro"])                 # creates the user/balance + opening grant
    s.chat_save_turn("u1", "c1", "hash", "hi", "there", 10, "m1")
    exp = s.export_user("u1")
    assert exp["user"] is not None
    assert len(exp["ledger"]) >= 1                        # opening grant
    assert "c1" in exp["chats"]


def test_delete_purges_everything():
    s = MemoryStore()
    s.create_key("k_u1", "u1", "pro")
    s.credit_balance("u1", TIERS["pro"])
    s.chat_save_turn("u1", "c1", "hash", "hi", "there", 10, "m1")
    res = s.delete_user("u1")
    assert res["deleted"] and res["api_keys"] == 1 and res["chats"] == 1
    # nothing left
    assert s.get_user("u1") is None
    assert s.export_user("u1") == {"user": None, "ledger": [], "chats": {}, "payments": []}
    assert s.get_key("k_u1") is None


def test_delete_is_scoped_to_one_user():
    s = MemoryStore()
    s.credit_balance("u1", TIERS["pro"])
    s.credit_balance("u2", TIERS["pro"])
    s.delete_user("u1")
    assert s.get_user("u1") is None
    assert s.get_user("u2") is not None                  # untouched
