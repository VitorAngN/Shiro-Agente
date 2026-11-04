"""Relógio do sistema no fuso configurado (porta ``Clock``)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


class SystemClock:
    def __init__(self, timezone: ZoneInfo) -> None:
        self._tz = timezone

    def now(self) -> datetime:
        return datetime.now(self._tz)
