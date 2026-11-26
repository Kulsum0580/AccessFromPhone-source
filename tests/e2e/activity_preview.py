"""Isolated browser fixture. Run directly, then use the printed local URLs.

All activity is synthetic. PC sign-in uses activity-preview-only. Stop with Ctrl+C.
"""
from __future__ import annotations

import socket
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from popup_e2e import make_settings
from handoff.daily.activity import Sample
from handoff.daily.app_icons import extract_icons
from handoff.runtime import start


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="afp-activity-preview-") as work:
        settings = make_settings(Path(work))
        settings.server.port = free_port()
        settings.accounts.admin_port = free_port()
        settings.daily.folder = Path(work) / "daily"
        settings.push.enabled = False
        running = start(settings, quiet=True)
        tracker = running.app.state.daily.activity
        tracker.sample = lambda: Sample("python.exe", ("python.exe", "EXCEL.EXE", "notepad.exe"), 90)
        preview_icons = extract_icons({"python.exe": sys.executable})
        tracker.icons.for_names = lambda names: {name: preview_icons[name] for name in names if name in preview_icons}
        accounts = running.app.state.accounts
        accounts.setup_owner("Activity preview", "activity-preview-only")
        current = time.time()
        today = datetime.fromtimestamp(current).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        beginning = max(today, current - 12600)
        for offset, seconds, state, app in ((0, 7200, "active", "python.exe"), (7200, 1800, "idle", ""), (9000, 2700, "active", "EXCEL.EXE"), (11700, 900, "active", "notepad.exe")):
            began, ended = beginning + offset, min(current, beginning + offset + seconds)
            if began < ended:
                tracker.db.run("INSERT INTO activity_spans (started,ended,state,app) VALUES (?,?,?,?)", (began, ended, state, app))
                if app:
                    tracker.db.run("INSERT INTO activity_events (time,kind,app) VALUES (?,?,?)", (began, "opened", app))
        tracker.tick()
        print(f"Phone preview: http://127.0.0.1:{settings.server.port}/", flush=True)
        print(f"PC preview: http://127.0.0.1:{settings.accounts.admin_port}/", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            running.stop()


if __name__ == "__main__":
    main()