"""Folders the user allowed from the phone (kept between restarts), and the places nobody can allow."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .config import Settings
from .db import Database, open_database, retire

# Under the user's home folder. Credentials, keys and browser profiles: a stolen phone must not be able to read these.
_PROTECTED_IN_HOME = (
    ".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker", ".config/gcloud",
    "AppData/Roaming/Microsoft/Credentials", "AppData/Roaming/Microsoft/Protect",
    "AppData/Local/Microsoft/Credentials", "AppData/Local/Google/Chrome/User Data",
    "AppData/Local/Microsoft/Edge/User Data", "AppData/Roaming/Mozilla/Firefox",
    "AppData/Local/BraveSoftware", "NTUSER.DAT",
)


def protected_locations(settings: Settings) -> list[Path]:
    """Never available: this app's own data (the access token, the https key, the audit log), credentials, Windows."""
    own = [
        settings.server.token_file.parent, settings.logging.audit_file.parent, settings.storage.snapshots_dir.parent,
        settings.storage.results_dir.parent, settings.storage.grants_file.parent, settings.storage.database.parent, settings.server.tls_dir.parent,
    ]
    home = Path.home()
    places = [*own, *(home / part for part in _PROTECTED_IN_HOME), *settings.agent.protected_folders]
    if os.name == "nt":
        places.append(Path(os.environ.get("SystemRoot", r"C:\Windows")))
    unique: dict[Path, None] = {}
    for place in places:
        unique[Path(place).resolve()] = None
    return list(unique)


class GrantStore:
    """The folders the user chose to keep allowing, and whether they may be changed too. Kept in the database."""

    def __init__(self, source: Database | Path, legacy_file: Path | None = None):
        self._db, from_path = open_database(source)
        legacy = legacy_file or from_path
        if legacy is not None:
            self._import(legacy)

    def load(self) -> list[tuple[Path, bool]]:
        return [(Path(r["path"]), bool(r["change"])) for r in self._db.rows("SELECT path, change FROM grants ORDER BY path")]

    def save(self, folders: list[tuple[Path, bool]]) -> None:
        with self._db.transaction():
            self._db._conn.execute("DELETE FROM grants")
            self._db._conn.executemany("INSERT OR REPLACE INTO grants (path, change) VALUES (?, ?)", [(str(f), int(c)) for f, c in sorted(folders)])

    def _import(self, file: Path) -> None:
        """The older grants.json: plain paths meant read-only, newer entries say whether editing is allowed."""
        if not file.is_file():
            return
        found: list[tuple[str, int]] = []
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            for entry in data.get("folders", []):
                if isinstance(entry, str):
                    found.append((entry, 0))
                elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
                    found.append((entry["path"], int(bool(entry.get("change")))))
        except (OSError, ValueError, AttributeError):
            pass
        with self._db.transaction():
            self._db._conn.executemany("INSERT OR IGNORE INTO grants (path, change) VALUES (?, ?)", found)
        retire(file)
