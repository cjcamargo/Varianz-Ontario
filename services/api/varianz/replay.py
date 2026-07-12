from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ReplaySession:
    id: UUID
    owner_id: UUID
    cursor: datetime
    minimum: datetime
    maximum: datetime
    reset_cursor: datetime | None = None
    speed: float = 1.0
    playing: bool = False
    revision: int = 0
    anchored_at: datetime | None = None

    @classmethod
    def create(
        cls,
        owner_id: UUID,
        minimum: datetime,
        maximum: datetime,
        *,
        initial_cursor: datetime | None = None,
    ) -> "ReplaySession":
        cursor = initial_cursor or minimum
        if not minimum <= cursor <= maximum:
            raise ValueError("invalid_initial_replay_cursor")
        return cls(uuid4(), owner_id, cursor, minimum, maximum, cursor)

    def effective_cursor(self, now: datetime | None = None) -> datetime:
        if not self.playing or self.anchored_at is None:
            return self.cursor
        now = now or datetime.now(timezone.utc)
        elapsed = (now - self.anchored_at).total_seconds() * self.speed
        return min(self.cursor + timedelta(seconds=elapsed), self.maximum)

    def mutate(
        self, action: str, expected_revision: int, *, value=None, now=None
    ) -> "ReplaySession":
        if expected_revision != self.revision:
            raise ValueError("replay_revision_conflict")
        now = now or datetime.now(timezone.utc)
        cursor = self.effective_cursor(now)
        changes = {"cursor": cursor, "revision": self.revision + 1, "anchored_at": None}
        if action == "play":
            changes.update(playing=True, anchored_at=now)
        elif action == "pause":
            changes["playing"] = False
        elif action == "seek":
            if not isinstance(value, datetime) or not self.minimum <= value <= self.maximum:
                raise ValueError("invalid_replay_cursor")
            changes.update(cursor=value, playing=False)
        elif action == "speed":
            if value not in {0.25, 1, 5, 20, 60}:
                raise ValueError("invalid_replay_speed")
            changes.update(
                speed=float(value), playing=self.playing, anchored_at=now if self.playing else None
            )
        elif action == "reset":
            changes.update(cursor=self.reset_cursor or self.minimum, playing=False)
        else:
            raise ValueError("invalid_replay_action")
        return replace(self, **changes)
