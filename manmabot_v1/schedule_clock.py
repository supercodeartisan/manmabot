"""When an enabled schedule should log in, warn, and hand over.

Window mode runs from start_time through end_time on the selected weekdays.
Duration mode runs from start_time for duration_minutes. A randomize value
shifts only the end, once per window, by a whole number of minutes in
[-N, +N]. The clock does not touch the game.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable

from manmabot_v1.schedule import ScheduleTask

NOTICE_LEAD = timedelta(minutes=5)
Rng = Callable[[int, int], int]


@dataclass(frozen=True)
class NominalWindow:
    task_id: str
    start: datetime
    end: datetime
    key: str


@dataclass(frozen=True)
class ScheduleDecision:
    """idle: keep the current run. notify: warn once, do not stop.

    begin: log in this task. handover: log out, then log in task_id
    (or wait, when task_id is None).
    """

    kind: str
    task_id: str | None = None
    switch_at: datetime | None = None


def _clock(value: str) -> time:
    parts: list[int] = []
    for piece in str(value or "").strip().split(":"):
        if piece == "":
            continue
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    hour, minute, second = parts[:3]
    return time(hour % 24, min(59, max(0, minute)), min(59, max(0, second)))


def window_bounds(task: ScheduleTask, day: date) -> tuple[datetime, datetime] | None:
    start = datetime.combine(day, _clock(task.start_time))
    if task.time_mode == "duration":
        minutes = max(1, int(task.duration_minutes or 1))
        end = start + timedelta(minutes=minutes)
    else:
        end = datetime.combine(day, _clock(task.end_time))
        if end <= start:
            end += timedelta(days=1)
    if end <= start:
        return None
    return start, end


def nominal_windows(tasks: Iterable[ScheduleTask], moment: datetime) -> list[NominalWindow]:
    """Windows that can cover *moment*, including ones that started overnight."""
    days = [moment.date() + timedelta(days=offset) for offset in range(-8, 2)]
    found: list[NominalWindow] = []
    for task in tasks:
        if not task.enabled or not task.account_id:
            continue
        weekdays = {int(day) for day in task.weekdays if 0 <= int(day) <= 6}
        for day in days:
            if day.weekday() not in weekdays:
                continue
            bounds = window_bounds(task, day)
            if bounds is None:
                continue
            start, end = bounds
            found.append(
                NominalWindow(
                    task_id=task.id,
                    start=start,
                    end=end,
                    key=f"{task.id}|{start.isoformat()}",
                )
            )
    return found


def _covering(
    windows: list[NominalWindow], moment: datetime, skip: set[str]
) -> NominalWindow | None:
    """First listed window that contains *moment*. List order is the priority."""
    for window in windows:
        if window.key in skip:
            continue
        if window.start <= moment < window.end:
            return window
    return None


class ScheduleSession:
    """Armed by Start and disarmed by Stop. Polling is idempotent."""

    def __init__(self) -> None:
        self.armed = False
        self.active_id: str | None = None
        self.nominal_key: str | None = None
        self.switch_at: datetime | None = None
        self.notified = False
        self.switching = False
        self.finished: set[str] = set()
        self.offsets: dict[str, int] = {}

    def arm(self) -> None:
        self.armed = True
        self.active_id = None
        self.nominal_key = None
        self.switch_at = None
        self.notified = False
        self.switching = False

    def disarm(self) -> None:
        self.armed = False
        self.active_id = None
        self.nominal_key = None
        self.switch_at = None
        self.notified = False
        self.switching = False

    def skip_current(self) -> None:
        if self.nominal_key:
            self.finished.add(self.nominal_key)
        self.active_id = None
        self.nominal_key = None
        self.switch_at = None
        self.notified = False

    def next_task_id(self, tasks: Iterable[ScheduleTask]) -> str | None:
        """Account that should take over at switch_at, if one is scheduled."""
        if self.switch_at is None:
            return None
        windows = [
            window
            for window in nominal_windows(tasks, self.switch_at)
            if window.key != self.nominal_key
        ]
        current = _covering(windows, self.switch_at, set())
        if current is not None:
            return current.task_id
        upcoming = [window for window in windows if window.start >= self.switch_at]
        if not upcoming:
            return None
        return min(upcoming, key=lambda window: (window.start, window.task_id)).task_id

    def _offset(self, key: str, minutes: int, rng: Rng) -> int:
        if minutes <= 0:
            return 0
        if key not in self.offsets:
            span = int(minutes)
            self.offsets[key] = int(rng(-span, span))
        return int(self.offsets[key])

    def _switch_at(self, window: NominalWindow, minutes: int, rng: Rng) -> datetime:
        switch = window.end + timedelta(minutes=self._offset(window.key, minutes, rng))
        earliest = window.start + timedelta(seconds=1)
        if switch < earliest:
            return earliest
        return switch

    def tick(
        self,
        now: datetime,
        tasks: Iterable[ScheduleTask],
        *,
        randomize_minutes: int = 0,
        rng: Rng | None = None,
    ) -> ScheduleDecision:
        if not self.armed or self.switching:
            return ScheduleDecision("idle")
        roll = rng or random.randint
        minutes = max(0, int(randomize_minutes or 0))
        task_list = list(tasks)
        windows = nominal_windows(task_list, now)
        by_key = {window.key: window for window in windows}

        if self.active_id and self.nominal_key:
            alive = next((task for task in task_list if task.id == self.active_id), None)
            window = by_key.get(self.nominal_key)
            playable = (
                alive is not None
                and alive.enabled
                and bool(alive.account_id)
                and window is not None
            )
            if playable and window is not None:
                self.switch_at = self._switch_at(window, minutes, roll)
                if now < self.switch_at:
                    if now < self.switch_at - NOTICE_LEAD:
                        self.notified = False
                        return ScheduleDecision("idle", self.active_id, self.switch_at)
                    if not self.notified:
                        self.notified = True
                        return ScheduleDecision("notify", self.active_id, self.switch_at)
                    return ScheduleDecision("idle", self.active_id, self.switch_at)
            if self.nominal_key:
                self.finished.add(self.nominal_key)
            self.active_id = None
            self.nominal_key = None
            self.switch_at = None
            self.notified = False
            return self._enter(now, windows, minutes, roll, kind="handover")
        return self._enter(now, windows, minutes, roll, kind="begin")

    def _enter(
        self,
        now: datetime,
        windows: list[NominalWindow],
        minutes: int,
        rng: Rng,
        *,
        kind: str,
    ) -> ScheduleDecision:
        skipped = set(self.finished)
        for _ in range(len(windows) + 1):
            window = _covering(windows, now, skipped)
            if window is None:
                break
            switch_at = self._switch_at(window, minutes, rng)
            if switch_at <= now:
                skipped.add(window.key)
                self.finished.add(window.key)
                continue
            self.active_id = window.task_id
            self.nominal_key = window.key
            self.switch_at = switch_at
            self.notified = False
            return ScheduleDecision(kind, window.task_id, switch_at)
        if kind == "handover":
            return ScheduleDecision("handover", None, None)
        return ScheduleDecision("idle")
