"""Relógio que o teste avança à mão."""

from __future__ import annotations

from datetime import datetime

from tests.fakes.agent import SAO_PAULO

SUNDAY = datetime(2026, 11, 1, 10, 0, tzinfo=SAO_PAULO)


class MovableClock:
    def __init__(self, now: datetime = SUNDAY) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current
