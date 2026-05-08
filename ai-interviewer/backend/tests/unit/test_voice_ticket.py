"""Tests for one-time voice WebSocket tickets."""
from __future__ import annotations

from app.core.voice_ticket import MemoryVoiceTicketStore, RedisVoiceTicketStore


def test_memory_voice_ticket_consumes_once() -> None:
    store = MemoryVoiceTicketStore(ttl_seconds=30)
    ticket = store.issue("sess-1", now=100.0)

    assert store.consume(ticket, "sess-1", now=101.0) is True
    assert store.consume(ticket, "sess-1", now=102.0) is False


def test_memory_voice_ticket_rejects_expired_ticket() -> None:
    store = MemoryVoiceTicketStore(ttl_seconds=5)
    ticket = store.issue("sess-1", now=100.0)

    assert store.consume(ticket, "sess-1", now=106.0) is False


def test_memory_voice_ticket_wrong_session_burns_ticket() -> None:
    store = MemoryVoiceTicketStore(ttl_seconds=30)
    ticket = store.issue("sess-1", now=100.0)

    assert store.consume(ticket, "sess-2", now=101.0) is False
    assert store.consume(ticket, "sess-1", now=102.0) is False


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}
        self.deleted: list[str] = []

    def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiry[key] = ex
        return True

    def eval(self, _script: str, numkeys: int, *args) -> int:
        assert numkeys == 1
        key = str(args[0])
        expected_session_id = str(args[1])
        value = self.values.pop(key, None)
        self.deleted.append(key)
        return int(value == expected_session_id)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.deleted.append(key)
            self.values.pop(key, None)

    def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in sorted(self.values):
            if key.startswith(prefix):
                yield key


def test_redis_voice_ticket_consumes_once() -> None:
    fake = _FakeRedis()
    store = RedisVoiceTicketStore(
        redis_client=fake,
        ttl_seconds=30,
        redis_prefix="test-voice",
    )

    ticket = store.issue("sess-1")

    assert fake.values[f"test-voice:{ticket}"] == "sess-1"
    assert fake.expiry[f"test-voice:{ticket}"] == 30
    assert store.consume(ticket, "sess-1") is True
    assert store.consume(ticket, "sess-1") is False


def test_redis_voice_ticket_wrong_session_burns_ticket() -> None:
    fake = _FakeRedis()
    store = RedisVoiceTicketStore(
        redis_client=fake,
        ttl_seconds=30,
        redis_prefix="test-voice",
    )
    ticket = store.issue("sess-1")

    assert store.consume(ticket, "sess-2") is False
    assert store.consume(ticket, "sess-1") is False


def test_redis_voice_ticket_clear_removes_prefixed_keys() -> None:
    fake = _FakeRedis()
    store = RedisVoiceTicketStore(
        redis_client=fake,
        ttl_seconds=30,
        redis_prefix="test-voice",
    )
    first = store.issue("sess-1")
    second = store.issue("sess-2")

    store.clear()

    assert fake.deleted == [f"test-voice:{first}", f"test-voice:{second}"]
