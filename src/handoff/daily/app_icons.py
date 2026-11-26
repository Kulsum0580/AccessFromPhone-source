from __future__ import annotations

import base64
import json
import subprocess
import sys
import threading
import time
from pathlib import PureWindowsPath

import psutil


def extract_icons(paths: dict[str, str]) -> dict[str, str]:
    if not paths or sys.platform != "win32":
        return {}
    import ctypes

    local = {name: path for name, path in paths.items()
             if PureWindowsPath(path).is_absolute() and not path.startswith("\\\\")
             and PureWindowsPath(path).suffix.lower() == ".exe"
             and ctypes.windll.kernel32.GetDriveTypeW(PureWindowsPath(path).anchor) == 3}
    if not local:
        return {}
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName System.Drawing
$paths = [Console]::In.ReadToEnd() | ConvertFrom-Json
$result = @{}
foreach ($entry in $paths.PSObject.Properties) {
    $icon = $null; $bitmap = $null; $stream = $null
    try {
        $icon = [System.Drawing.Icon]::ExtractAssociatedIcon([string]$entry.Value)
        if ($null -ne $icon) {
            $bitmap = $icon.ToBitmap()
            $stream = New-Object System.IO.MemoryStream
            $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
            $result[$entry.Name] = [Convert]::ToBase64String($stream.ToArray())
        }
    } catch {} finally {
        if ($stream) { $stream.Dispose() }
        if ($bitmap) { $bitmap.Dispose() }
        if ($icon) { $icon.Dispose() }
    }
}
ConvertTo-Json -InputObject $result -Compress
"""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            input=json.dumps(local), capture_output=True, text=True, encoding="utf-8", timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW, check=True,
        )
        result = json.loads(completed.stdout)
        return {name: "data:image/png;base64," + value for name, value in result.items()
                if name in local and isinstance(value, str) and len(value) <= 100_000
                and base64.b64decode(value, validate=True).startswith(b"\x89PNG\r\n\x1a\n")}
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return {}


class ApplicationIcons:
    def __init__(self):
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def for_names(self, names: set[str]) -> dict[str, str]:
        if not names:
            return {}
        with self._lock:
            now = time.monotonic()
            self._cache = {name: value for name, value in self._cache.items() if value[0] > now}
            missing = {name.casefold() for name in names if name.casefold() not in self._cache}
            paths = {}
            if missing:
                for process in psutil.process_iter(["name"]):
                    name = (process.info.get("name") or "").casefold()
                    if name not in missing or name in paths:
                        continue
                    try:
                        paths[name] = process.exe()
                    except (psutil.Error, OSError):
                        pass
                found = extract_icons(paths)
                for name in missing:
                    self._cache[name] = (now + (3600 if found.get(name) else 60), found.get(name, ""))
                while len(self._cache) > 256:
                    self._cache.pop(next(iter(self._cache)))
            return {name: self._cache[name.casefold()][1] for name in names
                    if name.casefold() in self._cache and self._cache[name.casefold()][1]}