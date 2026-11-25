from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from handoff.daily.activity import Activity, Sample, windows_sample
from handoff.daily.app_icons import ApplicationIcons
from handoff.db import Database


@pytest.fixture
def activity(tmp_path):
    now = [datetime(2026, 11, 25, 10).timestamp()]
    sample = [Sample("notepad.exe", ("notepad.exe",), 0)]
    calls = []

    def observe():
        calls.append(True)
        return sample[0]

    tracker = Activity(Database(tmp_path / "activity.db"), observe, clock=lambda: now[0])
    return tracker, now, sample, calls


def test_application_icons_only_resolve_requested_apps_and_cache(monkeypatch):
    from handoff.daily import app_icons

    wanted = SimpleNamespace(info={"name": "Code.exe"}, exe=Mock(return_value="C:\\Apps\\Code.exe"))
    other = SimpleNamespace(info={"name": "private.exe"}, exe=Mock())
    monkeypatch.setattr(app_icons.psutil, "process_iter", lambda attrs: [wanted, other])
    extract = Mock(return_value={"code.exe": "data:image/png;base64,fixture"})
    monkeypatch.setattr(app_icons, "extract_icons", extract)
    icons = ApplicationIcons()
    assert icons.for_names({"Code.exe", "missing.exe"}) == {"Code.exe": "data:image/png;base64,fixture"}
    assert icons.for_names({"CODE.EXE"}) == {"CODE.EXE": "data:image/png;base64,fixture"}
    extract.assert_called_once_with({"code.exe": "C:\\Apps\\Code.exe"})
    other.exe.assert_not_called()
    icons.clear()
    icons.for_names({"Code.exe"})
    assert extract.call_count == 2


def test_windows_can_extract_this_python_executables_icon():
    import base64
    import io
    import sys

    from PIL import Image
    from handoff.daily.app_icons import extract_icons

    if sys.platform != "win32":
        pytest.skip("Windows executable icons")
    result = extract_icons({"python.exe": sys.executable})
    image = Image.open(io.BytesIO(base64.b64decode(result["python.exe"].split(",", 1)[1])))
    assert image.format == "PNG" and image.width > 0 and image.height > 0


def test_icons_reject_network_paths_and_timeout_safely(monkeypatch):
    import subprocess
    import sys
    from handoff.daily import app_icons

    if sys.platform != "win32":
        pytest.skip("Windows executable icons")
    run = Mock(side_effect=subprocess.TimeoutExpired("powershell.exe", 10))
    monkeypatch.setattr(app_icons.subprocess, "run", run)
    assert app_icons.extract_icons({"remote.exe": "\\\\server\\share\\remote.exe"}) == {}
    run.assert_not_called()
    assert app_icons.extract_icons({"python.exe": sys.executable}) == {}
    run.assert_called_once()


def test_disabled_and_paused_do_not_observe(activity):
    tracker, now, sample, calls = activity
    tracker.tick()
    assert calls == []
    tracker.configure(enabled=True, paused=True)
    tracker.tick()
    assert calls == []
    assert tracker.report()["timeline"] == []


def test_global_pause_hides_current_sample_and_skips_observation(activity):
    tracker, now, sample, calls = activity
    paused = [False]
    tracker.suspended = lambda: paused[0]
    tracker.configure(enabled=True)
    tracker.tick()
    paused[0] = True
    assert not tracker.status()["recording"]
    assert tracker.status()["suspended"]
    assert tracker.status()["open_apps"] == []
    now[0] += 5
    tracker.tick()
    assert len(calls) == 1
    paused[0] = False
    now[0] += 5
    tracker.tick()
    assert tracker.report()["observed_seconds"] == 0


def test_collector_failure_does_not_stop_other_daily_tools():
    from handoff.daily import Daily

    calls = []

    def failure():
        raise OSError("Database temporarily unavailable")

    daily = object.__new__(Daily)
    daily.activity = SimpleNamespace(tick=failure)
    daily.scheduler = SimpleNamespace(tick=lambda: calls.append("scheduler"))
    daily.watchers = SimpleNamespace(tick=lambda: calls.append("watchers"))
    daily.mirror = SimpleNamespace(poll=lambda: calls.append("mirror"))
    daily.cfg = SimpleNamespace(notifications=True)
    daily.tick()
    assert calls == ["scheduler", "watchers", "mirror"]


def test_idle_threshold_splits_interval_and_lock_does_not_close_apps(activity):
    tracker, now, sample, calls = activity
    tracker.configure(enabled=True)
    sample[0] = Sample("notepad.exe", ("notepad.exe",), 58)
    tracker.tick()
    now[0] += 5
    sample[0] = Sample("notepad.exe", ("notepad.exe",), 63)
    tracker.tick()
    assert tracker.report()["totals"]["active"] == 2
    assert tracker.report()["totals"]["idle"] == 3
    now[0] += 5
    sample[0] = Sample("", (), 0, locked=True)
    tracker.tick()
    now[0] += 5
    tracker.tick()
    assert tracker.report()["totals"]["locked"] == 5
    assert [event["kind"] for event in tracker.report()["events"]] == ["observed"]


def test_usage_events_and_idle_are_separate(activity):
    tracker, now, sample, calls = activity
    tracker.configure(enabled=True)
    tracker.tick()
    now[0] += 5
    sample[0] = Sample("EXCEL.EXE", ("notepad.exe", "EXCEL.EXE"), 0)
    tracker.tick()
    now[0] += 5
    sample[0] = Sample("EXCEL.EXE", ("EXCEL.EXE",), 65)
    tracker.tick()
    now[0] += 5
    tracker.tick()
    report = tracker.report()
    assert report["totals"]["active"] == 10
    assert report["totals"]["idle"] == 5
    assert report["open_apps"] == ["EXCEL.EXE"]
    assert report["current"]["state"] == "idle"
    assert report["current"]["app"] == "EXCEL.EXE"
    assert [(event["kind"], event["app"]) for event in report["events"]] == [
        ("observed", "notepad.exe"), ("opened", "EXCEL.EXE"), ("closed", "notepad.exe")]


def test_sleep_pause_and_failed_samples_are_not_filled_in(activity):
    tracker, now, sample, calls = activity
    tracker.configure(enabled=True)
    tracker.tick()
    now[0] += 3600
    tracker.tick()
    assert tracker.report()["observed_seconds"] == 0
    tracker.configure(enabled=True, paused=True)
    now[0] += 100
    tracker.configure(enabled=True)
    tracker.tick()
    assert tracker.report()["observed_seconds"] == 0
    tracker.sample = lambda: (_ for _ in ()).throw(OSError())
    now[0] += 5
    tracker.tick()
    assert tracker.report()["error"]
    assert tracker.report()["open_apps"] == []


def test_exclusions_retention_and_delete(activity):
    tracker, now, sample, calls = activity
    tracker.configure(enabled=True, excluded=["NOTEPAD.EXE"])
    tracker.tick()
    now[0] += 5
    tracker.tick()
    report = tracker.report()
    assert report["totals"]["excluded"] == 5
    assert report["events"] == [] and report["applications"] == []
    assert "notepad.exe" not in str(report["timeline"])
    now[0] += 8 * 86400
    tracker.prune()
    assert tracker.db.rows("SELECT * FROM activity_spans") == []
    tracker.clear()
    assert tracker.report()["timeline"] == []


def test_midnight_is_clipped_and_settings_survive_restart(activity):
    tracker, now, sample, calls = activity
    tracker.configure(enabled=True)
    now[0] = datetime(2026, 11, 25, 23, 59, 55).timestamp()
    tracker.tick()
    now[0] += 10
    tracker.tick()
    assert tracker.report()["totals"]["active"] == 5
    assert tracker.report(datetime(2026, 11, 25).date())["totals"]["active"] == 5
    restarted = Activity(tracker.db, tracker.sample, clock=tracker.clock)
    assert restarted.enabled and restarted.status()["open_apps"] == []
    with pytest.raises(ValueError):
        restarted.report(datetime.fromtimestamp(now[0]).date() + timedelta(days=1))


def test_windows_sampler_reads_only_process_names_and_last_input_time(monkeypatch):
    import ctypes
    import psutil
    import sys

    user, kernel = Mock(), Mock()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kwargs: user if name == "user32" else kernel, raising=False)
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    user.OpenInputDesktop.return_value = 1
    user.GetForegroundWindow.return_value = 100
    user.IsWindowVisible.side_effect = lambda window: window != 102
    user.GetWindowThreadProcessId.side_effect = lambda window, pointer: setattr(pointer._obj, "value", window - 99)

    def last_input(pointer):
        pointer._obj.dwTime = 1000
        return True

    def enumerate_windows(callback, context):
        for window in (100, 101, 102):
            callback(window, context)
        return True

    user.GetLastInputInfo.side_effect = last_input
    user.EnumWindows.side_effect = enumerate_windows
    kernel.GetTickCount64.return_value = 46000
    process = Mock(side_effect=lambda pid: SimpleNamespace(name=lambda: {1: "notepad.exe", 2: "EXCEL.EXE"}[pid]))
    monkeypatch.setattr(psutil, "Process", process)
    assert windows_sample() == Sample("notepad.exe", ("EXCEL.EXE", "notepad.exe"), 45)
    assert process.call_count == 2
    user.GetWindowTextW.assert_not_called()
    user.OpenInputDesktop.return_value = 0
    assert windows_sample() == Sample("", (), 0, locked=True)
    assert process.call_count == 2