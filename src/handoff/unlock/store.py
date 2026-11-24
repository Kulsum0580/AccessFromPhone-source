"""What the unlock helper remembers: the secret it types at the lock screen, and the PIN that has to be given first.

The secret is Windows' own sign-in for this PC: either the Windows Hello PIN (which only works on this one machine, so it is the safer
choice) or the account password. It is stored encrypted for this machine (Windows DPAPI) in a file only the system and administrators
can read. The unlock PIN is never stored, only a salted scrypt hash of it. Wrong PINs are counted here, in the helper, so nothing that
bypasses the app can guess faster than the limit.

`protect` / `unprotect` are passed in, so the rules can be tested without Windows.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .errors import Disabled, Locked, NeedsAttention, NotSetUp, WrongPin

KINDS = ("pin", "password")
MAX_FAILURES = 3          # wrong unlock PINs in a row before it pauses
LOCKOUT_SECONDS = 600     # how long it pauses
ATTENTION_AFTER = 2       # times the typed sign-in did not unlock the PC, before it stops trying until the owner has looked
PIN_MIN, PIN_MAX = 6, 32


def _hash(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


class UnlockStore:
    def __init__(self, path: Path, protect: Callable[[bytes], bytes], unprotect: Callable[[bytes], bytes],
                 now: Callable[[], float] = time.time, max_failures: int = MAX_FAILURES, lockout_seconds: int = LOCKOUT_SECONDS):
        self.path = Path(path)
        self._protect, self._unprotect = protect, unprotect
        self._now = now
        self._max_failures, self._lockout = max_failures, lockout_seconds
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ the file
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and data.get("v") == 1 else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".unlock-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(temp, self.path)  # whole file or nothing: a crash never leaves half of it
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    # ------------------------------------------------------------------ setting it up (done at the PC, by an administrator)
    def configure(self, kind: str, secret: str, pin: str) -> None:
        if kind not in KINDS:
            raise ValueError("The sign-in must be a PIN or a password.")
        if not secret or len(secret) > 128:
            raise ValueError("The Windows sign-in can't be empty.")
        if not (PIN_MIN <= len(pin) <= PIN_MAX):
            raise ValueError(f"The unlock PIN needs {PIN_MIN} to {PIN_MAX} characters.")
        if pin == secret:
            raise ValueError("The unlock PIN must be different from the Windows sign-in: it protects it.")
        salt = secrets.token_bytes(16)
        with self._lock:
            self._save({
                "v": 1, "kind": kind, "enabled": True,
                "secret": base64.b64encode(self._protect(secret.encode("utf-8"))).decode("ascii"),
                "salt": base64.b64encode(salt).decode("ascii"), "pin": base64.b64encode(_hash(pin, salt)).decode("ascii"),
                "fails": 0, "locked_until": 0, "unlocked_failures": 0, "attention": False, "updated": int(self._now()),
            })

    def forget(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    # ------------------------------------------------------------------ what the helper may tell the app
    def configured(self) -> bool:
        d = self._load()
        return bool(d.get("secret") and d.get("pin"))

    def status(self) -> dict:
        with self._lock:
            d = self._load()
            if not (d.get("secret") and d.get("pin")):
                return {"configured": False, "enabled": False, "kind": "", "attention": False, "locked_for": 0, "tries_left": self._max_failures}
            left = max(0, int(d.get("locked_until", 0) - self._now()))
            return {"configured": True, "enabled": bool(d.get("enabled")), "kind": d.get("kind", ""), "attention": bool(d.get("attention")),
                    "locked_for": left, "tries_left": max(0, self._max_failures - int(d.get("fails", 0)))}

    def set_enabled(self, on: bool) -> None:
        with self._lock:
            d = self._load()
            if d:
                d["enabled"] = bool(on)
                self._save(d)

    def clear_attention(self) -> None:
        with self._lock:
            d = self._load()
            if d:
                d["attention"], d["unlocked_failures"] = False, 0
                self._save(d)

    # ------------------------------------------------------------------ using it
    def verify_pin(self, pin: str) -> None:
        """Returns if the PIN is right. Otherwise raises why not, and counts the wrong guess."""
        with self._lock:
            d = self._load()
            if not (d.get("secret") and d.get("pin")):
                raise NotSetUp("Unlocking isn't set up on this PC yet.")
            if not d.get("enabled"):
                raise Disabled("Unlocking from the phone is switched off on this PC.")
            if d.get("attention"):
                raise NeedsAttention("The last tries to unlock didn't work, so it has stopped. Check the saved sign-in is still right, then open this PC's own page and tap Start trying again under Unlock.")
            now = self._now()
            if d.get("locked_until", 0) > now:
                raise Locked(int(d["locked_until"] - now))
            ok = isinstance(pin, str) and PIN_MIN <= len(pin) <= PIN_MAX and secrets.compare_digest(
                _hash(pin, base64.b64decode(d["salt"])), base64.b64decode(d["pin"]))
            if ok:
                if d.get("fails"):
                    d["fails"] = 0
                    self._save(d)
                return
            d["fails"] = int(d.get("fails", 0)) + 1
            if d["fails"] >= self._max_failures:
                d["fails"], d["locked_until"] = 0, now + self._lockout
                self._save(d)
                raise Locked(self._lockout)
            self._save(d)
            raise WrongPin(self._max_failures - d["fails"])

    def reveal(self) -> tuple[str, str]:
        """(kind, secret) to type. Only the helper calls this, after the PIN was checked."""
        with self._lock:
            d = self._load()
            if not d.get("secret"):
                raise NotSetUp("Unlocking isn't set up on this PC yet.")
            return d["kind"], self._unprotect(base64.b64decode(d["secret"])).decode("utf-8")

    def note_result(self, unlocked: bool) -> None:
        """Typing the sign-in either unlocked the PC or it did not. Twice in a row not: it stops, so a wrong saved sign-in can't lock the account."""
        with self._lock:
            d = self._load()
            if not d:
                return
            if unlocked:
                d["unlocked_failures"] = 0
            else:
                d["unlocked_failures"] = int(d.get("unlocked_failures", 0)) + 1
                if d["unlocked_failures"] >= ATTENTION_AFTER:
                    d["attention"] = True
            self._save(d)
