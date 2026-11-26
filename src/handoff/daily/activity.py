"""Opt-in application usage metadata. Never reads window titles or input contents."""
from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta
from typing import Callable

from ..db import Database
from .app_icons import ApplicationIcons

RETENTION_DAYS = 7
IDLE_SECONDS = 60
MAX_SAMPLE_GAP = 15


@dataclass(frozen=True)
class Sample:
    foreground: str
    apps: tuple[str, ...]
    idle_seconds: float
    locked: bool = False


def windows_sample() -> Sample:
    import ctypes
    from ctypes import wintypes

    import psutil

    if sys.platform != "win32":
        raise OSError("Activity tracking requires Windows")
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.OpenInputDesktop.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.CloseDesktop.argtypes = (wintypes.HANDLE,)
    desktop = user.OpenInputDesktop(0, False, 1)
    if not desktop:
        return Sample("", (), 0, locked=True)
    user.CloseDesktop(desktop)
    foreground = user.GetForegroundWindow()
    if not foreground:
        return Sample("", (), 0, locked=True)

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user.GetLastInputInfo.argtypes = (ctypes.POINTER(LastInput),)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    kernel.GetTickCount64.restype = ctypes.c_ulonglong
    last_input = LastInput()
    last_input.cbSize = ctypes.sizeof(last_input)
    if not user.GetLastInputInfo(ctypes.byref(last_input)):
        raise ctypes.WinError(ctypes.get_last_error())
    idle = ((kernel.GetTickCount64() - last_input.dwTime) & 0xFFFFFFFF) / 1000
    names: dict[int, str] = {}

    def app_name(window) -> str:
        process_id = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        if process_id.value not in names:
            try:
                names[process_id.value] = psutil.Process(process_id.value).name()
            except (psutil.Error, OSError):
                names[process_id.value] = ""
        return names[process_id.value]

    apps: set[str] = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(window, context):
        if user.IsWindowVisible(window):
            name = app_name(window)
            if name:
                apps.add(name)
        return True

    user.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    if not user.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    active = app_name(foreground)
    if active:
        apps.add(active)
    return Sample(active, tuple(sorted(apps)), idle)


class Activity:
    def __init__(self, db: Database, sample: Callable[[], Sample], *, clock: Callable[[], float] = time.time,
                 supported: bool = True, suspended: Callable[[], bool] | None = None):
        self.db, self.sample, self.clock, self.supported = db, sample, clock, supported
        self.suspended = suspended or (lambda: False)
        self.icons = ApplicationIcons()
        self._lock = threading.RLock()
        self._last: tuple[float, Sample] | None = None
        self._since: float | None = None
        self._span_id: int | None = None
        self._error = ""
        saved = json.loads(db.meta("activity_settings") or "{}")
        self.enabled = saved.get("enabled", False) is True
        self.paused = saved.get("paused", False) is True
        self.excluded = set(saved.get("excluded", []))
        self.prune()

    def configure(self, *, enabled: bool, paused: bool = False, excluded: list[str] | None = None) -> dict:
        with self._lock:
            self.enabled, self.paused = enabled, paused
            if excluded is not None:
                self.excluded = {name.strip().casefold() for name in excluded if name.strip()}
            self.db.set_meta("activity_settings", json.dumps({"enabled": enabled, "paused": paused, "excluded": sorted(self.excluded)}))
            self.reset()
            return self.status()

    def reset(self) -> None:
        with self._lock:
            self._last, self._since, self._span_id = None, None, None

    def prune(self) -> None:
        cutoff = self.clock() - RETENTION_DAYS * 86400
        self.db.run("DELETE FROM activity_spans WHERE ended <= ?", (cutoff,))
        self.db.run("UPDATE activity_spans SET started=? WHERE started < ?", (cutoff, cutoff))
        self.db.run("DELETE FROM activity_events WHERE time < ?", (cutoff,))

    def clear(self) -> None:
        with self._lock:
            self.db.run("DELETE FROM activity_spans")
            self.db.run("DELETE FROM activity_events")
            self.icons.clear()
            self.reset()

    def _state(self, sample: Sample) -> tuple[str, str]:
        if sample.locked:
            return "locked", ""
        if sample.foreground.casefold() in self.excluded:
            return "excluded", ""
        if sample.idle_seconds >= IDLE_SECONDS:
            return "idle", ""
        return ("active", sample.foreground) if sample.foreground else ("unavailable", "")

    def status(self) -> dict:
        with self._lock:
            suspended = self.suspended()
            recording = self.supported and self.enabled and not self.paused and not suspended
            fresh = recording and self._last is not None and 0 <= self.clock() - self._last[0] <= MAX_SAMPLE_GAP
            current = self._last[1] if fresh and self._last else None
            state, app = self._state(current) if current else ("unavailable", "")
            if state == "idle" and current:
                app = current.foreground
            return {
                "supported": self.supported, "enabled": self.enabled, "paused": self.paused,
                "recording": recording, "suspended": suspended,
                "excluded": sorted(self.excluded), "retention_days": RETENTION_DAYS, "idle_after_seconds": IDLE_SECONDS,
                "current": {"state": state, "app": app, "since": self._since if current else None,
                            "observed_at": self._last[0] if current and self._last else None},
                "open_apps": sorted(current.apps, key=str.casefold) if current else [], "error": self._error,
            }

    def _span(self, start: float, end: float, state: str, app: str) -> None:
        previous = self.db.one("SELECT * FROM activity_spans WHERE id=?", (self._span_id,)) if self._span_id else None
        if previous and previous["ended"] == start and previous["state"] == state and previous["app"] == app:
            self.db.run("UPDATE activity_spans SET ended=? WHERE id=?", (end, self._span_id))
        else:
            self.db.run("INSERT INTO activity_spans (started,ended,state,app) VALUES (?,?,?,?)", (start, end, state, app))
            self._span_id = self.db.one("SELECT MAX(id) AS id FROM activity_spans")["id"]

    def tick(self) -> None:
        with self._lock:
            self.prune()
            if not self.enabled or self.paused or not self.supported or self.suspended():
                self.reset()
                return
            try:
                raw = self.sample()
            except Exception:
                self._error = "Activity could not be read. This interval is not counted."
                self.reset()
                return
            now = self.clock()
            filtered = tuple(sorted({name for name in raw.apps if name.casefold() not in self.excluded}))
            current = Sample(raw.foreground, filtered, raw.idle_seconds, raw.locked)
            self._error = ""
            previous = self._last
            contiguous = previous is not None and 0 < now - previous[0] <= MAX_SAMPLE_GAP
            if not contiguous:
                self._span_id = None
                self._since = now
                for name in current.apps:
                    self.db.run("INSERT INTO activity_events (time,kind,app) VALUES (?,?,?)", (now, "observed", name))
            else:
                started, before = previous
                state, app = self._state(before)
                idle_at = now - current.idle_seconds + IDLE_SECONDS
                if state == "active" and current.idle_seconds >= IDLE_SECONDS and started < idle_at < now:
                    self._span(started, idle_at, state, app)
                    self._span(idle_at, now, "idle", "")
                else:
                    self._span(started, now, state, app)
                if self._state(before) != self._state(current):
                    self._since = now
                if not before.locked and not current.locked:
                    for kind, names in (("opened", set(current.apps) - set(before.apps)), ("closed", set(before.apps) - set(current.apps))):
                        for name in sorted(names):
                            self.db.run("INSERT INTO activity_events (time,kind,app) VALUES (?,?,?)", (now, kind, name))
            self._last = (now, current)

    def report(self, selected: date | None = None) -> dict:
        with self._lock:
            self.prune()
            today = datetime.fromtimestamp(self.clock()).date()
            selected = selected or today
            if selected > today or selected < today - timedelta(days=RETENTION_DAYS):
                raise ValueError("Choose a date within the last seven days.")
            start = datetime.combine(selected, day_time.min).timestamp()
            end = min(datetime.combine(selected + timedelta(days=1), day_time.min).timestamp(), self.clock())
            spans = []
            totals = {key: 0.0 for key in ("active", "idle", "locked", "excluded", "unavailable")}
            apps: dict[str, float] = {}
            for row in self.db.rows("SELECT * FROM activity_spans WHERE ended > ? AND started < ? ORDER BY started,id", (start, end)):
                began, ended = max(start, row["started"]), min(end, row["ended"])
                seconds = max(0, ended - began)
                totals[row["state"]] += seconds
                if row["state"] == "active":
                    apps[row["app"]] = apps.get(row["app"], 0) + seconds
                spans.append({"start": began, "end": ended, "state": row["state"], "app": row["app"], "seconds": seconds})
            events = [dict(row) for row in self.db.rows("SELECT time,kind,app FROM activity_events WHERE time >= ? AND time < ? ORDER BY time,id", (start, end))]
            observed = sum(totals.values())
            return {**self.status(), "date": selected.isoformat(), "pc_today": today.isoformat(),
                    "day_start": start, "day_end": end, "totals": totals, "observed_seconds": observed,
                    "untracked_seconds": max(0, end - start - observed),
                    "applications": [{"name": name, "seconds": seconds} for name, seconds in sorted(apps.items(), key=lambda item: (-item[1], item[0]))],
                    "timeline": spans, "events": events}