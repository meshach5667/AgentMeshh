"""Availability schedules: when this machine accepts AgentMesh work, in local time.

Format (case-insensitive), windows separated by commas or semicolons:

    "mon-fri 18:00-08:00, sat-sun 00:00-24:00"
    "daily 22:00-07:00"

A window whose end is earlier than its start runs past midnight into the next day; it belongs to the day it
starts on. An empty schedule means always available.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WINDOW = re.compile(
    r"^(?P<days>[a-z]{3}(?:-[a-z]{3})?|daily|weekdays|weekends)\s+(?P<start>\d{1,2}:\d{2})-(?P<end>\d{1,2}:\d{2})$"
)


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class Window:
    days: frozenset[int]  # 0 = Monday
    start: int  # minutes after midnight
    end: int  # minutes after midnight; 1440 allowed; end <= start means it crosses midnight


def _minutes(text: str) -> int:
    hours, minutes = (int(x) for x in text.split(":"))
    if not (0 <= hours <= 24 and 0 <= minutes < 60) or (hours == 24 and minutes):
        raise ScheduleError(f"invalid time {text!r}")
    return hours * 60 + minutes


def _days(text: str) -> frozenset[int]:
    if text == "daily":
        return frozenset(range(7))
    if text == "weekdays":
        return frozenset(range(5))
    if text == "weekends":
        return frozenset({5, 6})
    parts = text.split("-")
    try:
        idx = [DAYS.index(p) for p in parts]
    except ValueError:
        raise ScheduleError(f"invalid day range {text!r}") from None
    if len(idx) == 1:
        return frozenset(idx)
    start, end = idx
    return frozenset((start + i) % 7 for i in range((end - start) % 7 + 1))


def parse(spec: str) -> list[Window]:
    windows = []
    for raw in re.split(r"[;,]", spec or ""):
        raw = " ".join(raw.strip().lower().split())
        if not raw:
            continue
        m = _WINDOW.match(raw)
        if not m:
            raise ScheduleError(f"cannot parse schedule window {raw!r} (expected e.g. 'mon-fri 18:00-08:00')")
        start, end = _minutes(m["start"]), _minutes(m["end"])
        if start == end:
            raise ScheduleError(f"window {raw!r} is empty")
        windows.append(Window(_days(m["days"]), start, end))
    return windows


def is_available(windows: list[Window], now: datetime) -> bool:
    if not windows:
        return True
    minute = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (today - 1) % 7
    for w in windows:
        if w.start < w.end:
            if today in w.days and w.start <= minute < w.end:
                return True
        else:  # crosses midnight
            if today in w.days and minute >= w.start:
                return True
            if yesterday in w.days and minute < w.end:
                return True
    return False


def next_change(windows: list[Window], now: datetime) -> datetime | None:
    """When availability next flips (minute resolution, within a week). None for an always-on schedule."""
    if not windows:
        return None
    current = is_available(windows, now)
    probe = now.replace(second=0, microsecond=0)
    for _ in range(7 * 24 * 60):
        probe += timedelta(minutes=1)
        if is_available(windows, probe) != current:
            return probe
    return None


__all__ = ["ScheduleError", "Window", "is_available", "next_change", "parse", "time"]
