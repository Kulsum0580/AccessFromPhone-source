"""The PC's own page: set up the owner, sign in, show the pairing QR code, manage phones.

It is a separate little app on 127.0.0.1 (never the network address), so a phone, or anyone else on the Wi-Fi,
cannot even reach it. It also refuses requests whose Host is not this PC, which stops a web page from tricking
the browser into talking to it.
"""
from __future__ import annotations

import platform
import secrets
import time
from pathlib import Path

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .accounts import AccountError, AccountStore, Locked
from . import sysinfo
from .config import Settings
from .connect import qr_svg
from .connectivity import Anywhere, lan_base, mac_address
from .jobs import JobManager
from .unlock import UnlockError

_PAGE = Path(__file__).parent / "web" / "admin.html"
COOKIE = "afp_admin"


class SetupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    username: str = Field(default="", max_length=200)  # Windows sign-in: the Windows user name
    password: str = Field(min_length=1, max_length=200)


class ResetIn(BaseModel):
    recovery_code: str = Field(min_length=1, max_length=80)
    new_password: str = Field(min_length=1, max_length=200)


class PasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class PairIn(BaseModel):
    via: Literal["lan", "anywhere"] = "lan"  # which address the QR code holds


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


_ACTIVITY = {
    "approved": ("Approved a request", "ok"), "rejected": ("Rejected a request", "warn"), "done": ("A request finished", "ok"),
    "unlocked": ("Unlocked this PC from a phone", "ok"), "unlock_off": ("Switched unlocking off", "warn"), "unlock_on": ("Switched unlocking on", "ok"),
    "unlock_removed": ("Removed the saved sign-in", "warn"), "unlock_resumed": ("Started unlocking again", "ok"), "unlock_setup_opened": ("Opened the unlock setup", "ok"),
    "admin_login": ("Signed in to this page", "ok"), "admin_login_failed": ("A wrong password was tried on this page", "bad"),
    "pair_failed": ("A phone tried a wrong code", "warn"), "expired": ("A request ran out of time", "warn"), "undone": ("Undid a change", "ok"),
}


def _describe(event: dict) -> dict | None:
    """One audit entry as a line for the overview, or None for the ones that would only be noise."""
    kind = event.get("event", "")
    text, tone = _ACTIVITY.get(kind, (None, "ok"))
    if kind == "submitted":
        text = "Asked: " + " ".join(str(event.get("prompt", "")).split())[:70]
    elif kind == "failed":
        text, tone = "A request failed", "bad"
    elif kind == "unlock_failed":
        text, tone = "Unlock didn't work (" + str(event.get("reason", "?")).replace("_", " ") + ")", "bad"
    elif kind == "device_paired":
        text = "Paired " + str(event.get("device", "a phone"))
    elif kind in ("browsed_folder", "streamed", "opened_in_viewer", "opened_in_editor", "download", "opened_gallery"):
        verb = {"browsed_folder": "Browsed", "streamed": "Played", "download": "Downloaded"}.get(kind, "Opened")
        text = f"{verb} {Path(str(event.get('path', ''))).name or str(event.get('path', ''))}"
    elif kind == "power":
        text = "Power: " + str(event.get("kind", "")).replace("_", " ")
    if not text:
        return None
    return {"time": event.get("time", ""), "text": text, "tone": tone}


def create_admin_app(settings: Settings, accounts: AccountStore, manager: JobManager, anywhere: Anywhere | None = None) -> FastAPI:
    app = FastAPI(title="AccessFromPhone (this PC)", docs_url=None, redoc_url=None, openapi_url=None)
    sessions: dict[str, float] = {}
    lifetime = settings.accounts.session_minutes * 60
    port = settings.accounts.admin_port
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    pc = platform.node()

    @app.middleware("http")
    async def only_this_pc(request: Request, call_next):
        if request.headers.get("host", "") not in allowed_hosts:
            return Response("Open this page from the PC it runs on.", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def who(request: Request) -> str:
        return request.client.host if request.client else "?"

    def signed_in(request: Request) -> bool:
        key = request.cookies.get(COOKIE, "")
        expiry = sessions.get(key, 0.0)
        if expiry <= time.monotonic():
            sessions.pop(key, None)
            return False
        sessions[key] = time.monotonic() + lifetime  # staying busy keeps you signed in
        return True

    def need_session(request: Request) -> None:
        if not signed_in(request):
            raise HTTPException(status_code=401, detail="Sign in first.")
        if request.method not in ("GET", "HEAD") and request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="Not from this page.")

    def start_session(response: Response) -> None:
        key = secrets.token_urlsafe(32)
        sessions[key] = time.monotonic() + lifetime
        response.set_cookie(COOKIE, key, httponly=True, samesite="strict", max_age=lifetime, path="/")

    def fail(exc: Exception) -> HTTPException:
        if isinstance(exc, Locked):
            return HTTPException(status_code=429, detail=str(exc))
        return HTTPException(status_code=400, detail=str(exc))

    def need_header(request: Request) -> None:
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="Not from this page.")

    @app.get("/", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        return HTMLResponse(_PAGE.read_text(encoding="utf-8"))

    @app.get("/admin/state")
    def state(request: Request) -> dict:
        windows = accounts.mode == "windows"
        return {"pc": pc, "mode": accounts.mode, "windows_user": accounts.windows_user() if windows else "",
                "setup_needed": (not windows) and not accounts.owner_exists, "signed_in": signed_in(request),
                "owner": accounts.owner_name, "https": settings.server.https}

    @app.post("/admin/setup", dependencies=[Depends(need_header)])
    def setup(body: SetupIn, request: Request, response: Response) -> dict:
        try:
            recovery = accounts.setup_owner(body.name, body.password)
        except AccountError as exc:
            raise fail(exc) from None
        manager.note("owner_setup", who=body.name)
        start_session(response)
        return {"recovery_code": recovery}

    @app.post("/admin/login", dependencies=[Depends(need_header)])
    def login(body: LoginIn, request: Request, response: Response) -> dict:
        try:
            if accounts.mode == "windows":
                ok = accounts.windows_sign_in(body.username, body.password)
            else:
                ok = accounts.verify_owner(body.password, who(request))
        except Locked as exc:
            raise fail(exc) from None
        if not ok:
            manager.note("admin_login_failed")
            raise HTTPException(status_code=401, detail="That user name or Windows password is not right." if accounts.mode == "windows" else "That password is not right.")
        manager.note("admin_login")
        start_session(response)
        return {"ok": True}

    @app.post("/admin/logout", dependencies=[Depends(need_header)])
    def logout(request: Request, response: Response) -> dict:
        sessions.pop(request.cookies.get(COOKIE, ""), None)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.post("/admin/reset", dependencies=[Depends(need_header)])
    def reset(body: ResetIn, request: Request, response: Response) -> dict:
        try:
            recovery = accounts.reset_password(body.recovery_code, body.new_password, who(request))
        except AccountError as exc:
            raise fail(exc) from None
        manager.note("password_reset")
        start_session(response)
        return {"recovery_code": recovery}

    @app.post("/admin/password", dependencies=[Depends(need_session)])
    def password(body: PasswordIn) -> dict:
        try:
            accounts.change_password(body.old_password, body.new_password)
        except AccountError as exc:
            raise fail(exc) from None
        manager.note("password_changed")
        return {"ok": True}

    @app.post("/admin/pairing", dependencies=[Depends(need_session)])
    def pairing(body: PairIn | None = None) -> dict:
        via = body.via if body else "lan"
        if via == "anywhere":
            if anywhere is None or not anywhere.url:
                raise HTTPException(status_code=409, detail="Anywhere access isn't on yet. Turn it on first.")
            base = anywhere.url
        else:
            base = lan_base(settings.server, settings.connectivity)
        code, seconds = accounts.new_pairing_code()
        link = f"{base}/?pair={code}"
        return {"code": code, "link": link, "svg": qr_svg(link), "expires_in": seconds, "via": via}

    @app.get("/admin/status", dependencies=[Depends(need_session)])
    def pc_status() -> dict:
        """How this PC is doing right now (processor, memory, disk, battery), for the overview."""
        return sysinfo.current()

    @app.get("/admin/activity", dependencies=[Depends(need_session)])
    def activity() -> list[dict]:
        """The latest things that happened, in plain words, newest first."""
        items: list[dict] = []
        for event in reversed(manager.audit_events(500)):
            item = _describe(event)
            if item:
                items.append(item)
            if len(items) >= 40:
                break
        return items

    @app.get("/admin/unlock", dependencies=[Depends(need_session)])
    def unlock_status() -> dict:
        """Whether unlocking this PC from a phone is set up and on. Setting it up is done at the PC, by an administrator, not from this page."""
        info = manager.unlocker.status()
        return {k: info.get(k) for k in ("running", "configured", "enabled", "kind", "attention", "locked_for", "locked")}

    @app.post("/admin/unlock/disable", dependencies=[Depends(need_session)])
    def unlock_disable() -> dict:
        try:
            manager.unlocker.disable()
        except UnlockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        manager.note("unlock_off")
        return {"ok": True}

    @app.post("/admin/unlock/setup", dependencies=[Depends(need_session)])
    def unlock_setup() -> dict:
        """Opens the setup window with administrator rights (Windows asks first). The sign-in is typed in that window on the PC, never on this page."""
        info = manager.unlocker.status()
        if info.get("running") and info.get("configured"):
            raise HTTPException(status_code=409, detail="Unlocking is already set up on this PC.")
        from .unlock import setup as unlock_setup_module

        if not unlock_setup_module.relaunch_elevated(["gui"], windowed=True):
            raise HTTPException(status_code=409, detail="Windows didn't give administrator rights (the prompt was declined or blocked), so the setup window didn't open.")
        manager.note("unlock_setup_opened")
        return {"ok": True}

    @app.post("/admin/unlock/enable", dependencies=[Depends(need_session)])
    def unlock_enable() -> dict:
        try:
            manager.unlocker.enable()
        except UnlockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        manager.note("unlock_on")
        return {"ok": True}

    @app.post("/admin/unlock/resume", dependencies=[Depends(need_session)])
    def unlock_resume() -> dict:
        try:
            manager.unlocker.resume()
        except UnlockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        manager.note("unlock_resumed")
        return {"ok": True}

    @app.post("/admin/unlock/forget", dependencies=[Depends(need_session)])
    def unlock_forget() -> dict:
        try:
            manager.unlocker.forget()
        except UnlockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        manager.note("unlock_removed")
        return {"ok": True}

    @app.get("/admin/connection", dependencies=[Depends(need_session)])
    def connection() -> dict:
        mac, reliable = mac_address()
        base = lan_base(settings.server, settings.connectivity)
        return {
            "lan": {"url": base, "https": settings.server.https, "by_name": settings.connectivity.lan_address == "name"},
            "anywhere": anywhere.status() if anywhere else {"enabled": False, "installed": False, "ready": False, "active": False, "url": "", "steps": [], "error": ""},
            "wake": {"mac": mac, "reliable": reliable},
            "power": {"keep_awake": settings.power.keep_awake},
        }

    @app.post("/admin/connection/anywhere", dependencies=[Depends(need_session)])
    def turn_on_anywhere() -> dict:
        if anywhere is None:
            raise HTTPException(status_code=409, detail="Anywhere access is switched off in config.yaml.")
        manager.note("anywhere_checked")
        return anywhere.enable()

    @app.get("/admin/devices", dependencies=[Depends(need_session)])
    def devices() -> list[dict]:
        return accounts.devices()

    def device_action(device_id: str, act, event: str) -> dict:
        try:
            device = act(device_id)
        except AccountError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        manager.note(event, device=device.name, device_id=device.id)
        return device.public()

    @app.post("/admin/devices/{device_id}/rename", dependencies=[Depends(need_session)])
    def rename(device_id: str, body: NameIn) -> dict:
        try:
            device = accounts.rename(device_id, body.name)
        except AccountError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        manager.note("device_renamed", device=device.name, device_id=device.id)
        return device.public()

    @app.post("/admin/devices/{device_id}/block", dependencies=[Depends(need_session)])
    def block(device_id: str) -> dict:
        return device_action(device_id, lambda i: accounts.set_blocked(i, True), "device_blocked")

    @app.post("/admin/devices/{device_id}/unblock", dependencies=[Depends(need_session)])
    def unblock(device_id: str) -> dict:
        return device_action(device_id, lambda i: accounts.set_blocked(i, False), "device_unblocked")

    @app.delete("/admin/devices/{device_id}", dependencies=[Depends(need_session)])
    def remove(device_id: str) -> dict:
        return device_action(device_id, accounts.remove, "device_removed")

    return app
