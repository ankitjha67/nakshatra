"""Server-side chat history (anti client-injection) + beta cohort tagging."""
from app.billing import MemoryStore


def test_chat_history_is_server_authoritative_and_ordered():
    s = MemoryStore()
    s.chat_save_turn("u1", "c1", "h", "hello", "hi there", 10, "m1")
    s.chat_save_turn("u1", "c1", "h", "and my career?", "career looks strong", 12, "m2")
    turns = s.chat_get_turns("u1", "c1")
    # user before assistant within a turn, turns in order
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert [t["text"] for t in turns] == ["hello", "hi there", "and my career?", "career looks strong"]


def test_chat_history_limit():
    s = MemoryStore()
    for i in range(20):
        s.chat_save_turn("u1", "c1", "h", f"q{i}", f"a{i}", 1, f"m{i}")
    turns = s.chat_get_turns("u1", "c1", limit=4)
    assert len(turns) == 4
    assert turns[-1]["text"] == "a19"     # most recent retained


def test_chat_history_isolated_per_chat_and_user():
    s = MemoryStore()
    s.chat_save_turn("u1", "c1", "h", "mine", "ok", 1, "m1")
    assert s.chat_get_turns("u2", "c1") == []      # different user
    assert s.chat_get_turns("u1", "cX") == []      # different chat


def test_set_tier_source_tags_user():
    s = MemoryStore()
    s.upsert_user("u1", "a@b.com")
    s.set_tier("u1", "enterprise", source="beta")
    u = s.get_user("u1")
    assert u["tier"] == "enterprise" and u["tier_source"] == "beta"
    # revoke path
    s.set_tier("u1", "free", source="revoked")
    u = s.get_user("u1")
    assert u["tier"] == "free" and u["tier_source"] == "revoked"
