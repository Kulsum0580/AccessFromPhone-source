"""Policy engine: the last check before any action touches the PC.

Folders come in these kinds:
- writable (`allowed_folders`): can be read, searched and, with approval, changed.
- read-only (`read_only_folders`): can be read and searched, never changed, whatever anyone taps.
- granted: folders the user allowed from the phone when asked. They can always be read; the user may also allow
  changing files there (to edit by hand). Both can be taken back.
- protected: never available, whatever else is configured or granted (this app's own secrets, SSH keys, ...).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import Action, ApprovalConfig
from .paths import is_inside


class PolicyError(Exception):
    """Base class for policy refusals."""


class PathDenied(PolicyError):
    """The path is not available."""


class OutsideAllowed(PathDenied):
    """The path is outside every allowed folder. The user may be asked to allow it."""

    def __init__(self, path: Path):
        super().__init__(f"{path} is outside the allowed folders")
        self.path = path


class ReadOnlyPath(PathDenied):
    """The path is in a read-only folder, so it cannot be changed."""


class ProtectedPath(PathDenied):
    """The path holds credentials or this app's own data. It is never available, and nobody can allow it."""

    def __init__(self, path: Path):
        super().__init__(
            f"{path} is a protected location (keys, credentials or this app's own data), "
            "so it can't be opened from the phone"
        )
        self.path = path


class ApprovalRequired(PolicyError):
    """The action needs the user's approval before it can run."""

    def __init__(self, action: Action, path: Path):
        super().__init__(f"{action.value} on {path} needs approval")
        self.action = action
        self.path = path


# Moving and copying are asked about like any other write.
_APPROVAL_AS = {Action.MOVE: Action.WRITE, Action.COPY: Action.WRITE}


def _is_root(path: Path) -> bool:
    return path == path.parent


@dataclass
class _Grant:
    owner: str | None  # the job it was allowed for, or None when it is kept
    can_change: bool  # the user also allowed changing files here (to edit them by hand)


class PolicyEngine:
    def __init__(
        self,
        allowed_folders: list[Path],
        approval: ApprovalConfig,
        read_only_folders: Iterable[Path] = (),
        protected_folders: Iterable[Path] = (),
    ):
        self._writable = [Path(f).resolve() for f in allowed_folders]
        self._read_only = [Path(f).resolve() for f in read_only_folders]
        # a drive root in this list would block everything, so it is ignored
        self._protected = [p for p in (Path(f).resolve() for f in protected_folders) if not _is_root(p)]
        self._require = {Action(a) for a in approval.require_for}
        self._granted: dict[Path, _Grant] = {}  # changed from request threads, so guarded
        self._lock = threading.Lock()

    # -- what is allowed ------------------------------------------------------

    def is_protected(self, path: str | Path) -> bool:
        real = Path(path).resolve()
        return any(is_inside(real, folder) for folder in self._protected)

    def _pinned_read_only(self, real: Path) -> bool:
        """In a folder that config.yaml marks read-only: nobody can allow changes there from the phone."""
        return any(is_inside(real, folder) for folder in self._read_only)

    def resolve(self, path: str | Path, *, for_write: bool = False) -> Path:
        """Return the real absolute path, or raise PathDenied.

        Resolving first means `..` segments and symlinks cannot escape the
        allowed folders. With `for_write`, only writable folders qualify.
        """
        real = Path(path).resolve()
        if self.is_protected(real):
            raise ProtectedPath(real)
        if any(is_inside(real, folder) for folder in self._writable):
            return real
        with self._lock:
            granted = list(self._granted.items())
        if for_write and not self._pinned_read_only(real) and any(g.can_change and is_inside(real, f) for f, g in granted):
            return real  # the user allowed changing files in this folder
        in_read_only = self._pinned_read_only(real) or any(is_inside(real, f) for f, _ in granted)
        if in_read_only and not for_write:
            return real
        if in_read_only:
            raise ReadOnlyPath(f"{real} is in a read-only folder, so it cannot be changed")
        raise OutsideAllowed(real)

    def can_change(self, path: str | Path) -> bool:
        """Could this path be changed right now (a writable folder, or one the user allowed changes in)?"""
        try:
            self.resolve(path, for_write=True)
            return True
        except PathDenied:
            return False

    def can_grant(self, folder: str | Path, *, change: bool = False) -> str | None:
        """None if the user may be asked to allow this folder, otherwise why not."""
        real = Path(folder).resolve()
        if self.is_protected(real):
            return f"{real} is a protected location, so it can't be opened from the phone."
        if _is_root(real):
            return f"{real} is a whole drive. Name a specific folder instead."
        if not real.is_dir():
            return f"I can't find the folder {real}. Check the path."
        if change and self._pinned_read_only(real):
            return f"config.yaml marks {real} as read-only, so it can't be changed from the phone. Change that on the PC first."
        return None

    # -- access the user grants while the app runs -----------------------------

    def grant(self, folder: str | Path, job_id: str | None = None, *, change: bool = False) -> Path:
        """Allow reading `folder` (and with `change`, editing files in it).

        With a job id the access ends when that job does; without, it is kept. A one-off never downgrades access
        that is already kept, and allowing changes is never lost by a later read-only grant.
        """
        real = Path(folder).resolve()
        with self._lock:
            current = self._granted.get(real)
            kept = job_id is None or (current is not None and current.owner is None)
            self._granted[real] = _Grant(None if kept else job_id, change or bool(current and current.can_change))
        return real

    def revoke(self, folder: str | Path) -> bool:
        real = Path(folder).resolve()
        with self._lock:
            return self._granted.pop(real, None) is not None

    def revoke_job(self, job_id: str) -> None:
        with self._lock:
            for folder in [f for f, g in self._granted.items() if g.owner == job_id]:
                del self._granted[folder]

    def granted(self) -> list[Path]:
        """The folders the user allowed and kept (not the one-off ones)."""
        with self._lock:
            return sorted(f for f, g in self._granted.items() if g.owner is None)

    def visible_roots(self) -> list[tuple[Path, str]]:
        """Where browsing may start: the allowed folders, the read-only ones, and the folders the user allowed and kept."""
        found: dict[Path, str] = {}
        for folder in self._writable:
            found.setdefault(folder, "writable")
        for folder in self._read_only:
            found.setdefault(folder, "read_only")
        for folder, can_change in self.granted_details():
            found.setdefault(folder, "granted_change" if can_change else "granted")
        return list(found.items())

    def granted_details(self) -> list[tuple[Path, bool]]:
        """Kept folders with whether changes are allowed there too."""
        with self._lock:
            return sorted((f, g.can_change) for f, g in self._granted.items() if g.owner is None)

    # -- approvals -------------------------------------------------------------

    def needs_approval(self, action: Action) -> bool:
        action = _APPROVAL_AS.get(action, action)
        return action in self._require

    def authorize(self, action: Action, path: str | Path, approved: bool) -> Path:
        real = self.resolve(path, for_write=action.changes_files)
        if self.needs_approval(action) and not approved:
            raise ApprovalRequired(action, real)
        return real
