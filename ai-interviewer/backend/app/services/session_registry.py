from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any


class SessionRegistry:
    """Thread-safe wrapper around the in-memory SessionHandle map.

    The manager still owns the backing dict for compatibility with existing
    tests and narrow debugging hooks; this class centralizes the lock usage.
    """

    def __init__(
        self,
        sessions: dict[str, Any] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self.sessions = sessions if sessions is not None else {}
        self.lock = lock if lock is not None else threading.Lock()

    def add(self, session_id: str, handle: Any, *, replace: bool = False) -> None:
        with self.lock:
            if not replace and session_id in self.sessions:
                raise ValueError("session_id already exists")
            self.sessions[session_id] = handle

    def get(self, session_id: str, *, touch: bool = True) -> Any | None:
        with self.lock:
            handle = self.sessions.get(session_id)
        if handle is not None and touch:
            handle.touch()
        return handle

    def contains(self, session_id: str) -> bool:
        with self.lock:
            return session_id in self.sessions

    def remove(self, session_id: str) -> bool:
        with self.lock:
            return self.sessions.pop(session_id, None) is not None

    def snapshot_pairs(self) -> list[tuple[str, Any]]:
        with self.lock:
            return list(self.sessions.items())

    def expired_session_ids(self, *, now: datetime, ttl: timedelta) -> list[str]:
        victims: list[str] = []
        with self.lock:
            for sid, handle in self.sessions.items():
                if (now - handle.last_activity_at) > ttl:
                    victims.append(sid)
        return victims
