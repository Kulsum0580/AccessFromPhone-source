"""HTTP server for the phone page. Every /api call needs a paired phone's token (or, with accounts off, the shared token)."""
from __future__ import annotations

import asyncio
import getpass
import mimetypes
import platform
import re
import secrets
import time
from contextlib import asynccontextmanager
from importlib import metadata
from pathlib import Path

from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .accounts import AccountError, AccountStore, Device, DeviceLimit, Locked
from .config import Settings
from . import sysinfo
from .jobs import FileChanged, FileTooBig, JobManager, JobNotFound, JobStateError
from .unlock import UnlockError
from . import pcwatch
from .push import Message, Notifier
from .planner import AnthropicPlanner, DemoPlanner, OllamaPlanner, Planner, build_planner
from .policy import OutsideAllowed, PathDenied, ReadOnlyPath

_WEB = Path(__file__).parent / "web"
_PAGE = _WEB / "index.html"
_CONVERSATION = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

mimetypes.add_type("application/manifest+json", ".webmanifest")


def quiet_disconnects(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Windows prints a long traceback each time a phone drops its connection (the screen locks, the app closes).

    That is normal and harmless, so those few errors are ignored. Anything else is reported as usual.
    """
    if isinstance(context.get("exception"), (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return
    loop.default_exception_handler(context)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    asyncio.get_running_loop().set_exception_handler(quiet_disconnects)
    sysinfo.DEFAULT.start()  # so the network speed is already known when the phone first asks
    stop_watching = pcwatch.start(app.state.notifier)  # tells the phone before this PC sleeps, shuts down or runs out of battery
    yield
    app.state.notifier.notify_pc("pc_closing", wait=True)  # the app is stopping on purpose: say so while there is still a network
    stop_watching()
    app.state.manager.flush()  # the last few seconds of every request are written before the PC stops


class _Assets(StaticFiles):
    """The page's own files. They change when the app is updated, so the browser must re-check them."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def load_or_create_token(token_file: Path) -> str:
    if token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    token_file.write_text(token, encoding="utf-8")
    return token


class AccessIn(BaseModel):
    decision: Literal["always", "once", "deny"]


class PathIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


class GrantIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    change: bool = False  # also allow editing files in the folder


class FileIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    text: str = Field(max_length=1_200_000)
    base_sha: str | None = Field(default=None, max_length=64)  # the file as the editor opened it; None = save over whatever is there
    conversation: str | None = Field(default=None, max_length=40)


class ApproveIn(BaseModel):
    pin: str | None = Field(default=None, max_length=64)  # the unlock PIN, only for a request to unlock this PC; never stored or logged


class ClaimIn(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=60)
    previous: str = Field(default="", max_length=200)  # this phone's old token, if it still has one: it then replaces its own entry


class DeviceNameIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class DeviceRemoveIn(BaseModel):
    username: str = Field("", max_length=120)
    password: str = Field(min_length=1, max_length=256)


class PushSubIn(BaseModel):
    kind: Literal["web", "fcm"]
    endpoint: str = Field(default="", max_length=1000)  # web: the browser's push address
    keys: dict[str, str] = Field(default_factory=dict)  # web: p256dh and auth
    token: str = Field(default="", max_length=4096)  # fcm: the app's token


class PushOffIn(BaseModel):
    kind: Literal["web", "fcm"] | None = None


class PromptIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    conversation: str | None = Field(default=None, max_length=40)
    file: str | None = Field(default=None, max_length=1000)  # the file the phone was showing: what "it" means


def _folder_of(path) -> str:
    return str(path if path.is_dir() else path.parent)


def _version() -> str:
    try:
        return metadata.version("handoff")
    except metadata.PackageNotFoundError:  # the installed app has no package metadata: the installer stamped the version instead
        from . import _build

        return _build.VERSION


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no user name on some service accounts
        return "You"


def create_app(settings: Settings, planner: Planner | None = None) -> FastAPI:
    token = load_or_create_token(settings.server.token_file)
    if planner is None:
        planner, note = build_planner(settings.llm)
    else:
        note = "AI model: custom planner"
    manager = JobManager(settings, planner)

    app = FastAPI(title="AccessFromPhone", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)
    accounts = AccountStore(manager.db, settings.accounts.pairing_minutes, settings.accounts.max_devices, legacy_file=settings.accounts.file, mode=settings.accounts.sign_in, forget_after_days=settings.accounts.forget_after_days) if settings.accounts.enabled else None
    app.state.token = token
    app.state.manager = manager
    app.state.planner_note = note
    app.state.accounts = accounts
    notifier = Notifier(settings.push, manager.db)
    manager.on_event = notifier.on_job_event  # a request that needs you, or is over, becomes a notification
    manager.on_pc_event = notifier.notify_pc  # the phone asked this PC to sleep or shut down: every phone hears it first
    app.state.notifier = notifier

    def require_token(request: Request) -> None:
        supplied = request.headers.get("x-token", "")
        if accounts is not None:
            device = accounts.authenticate(supplied, request.client.host if request.client else "")
            if device is None:
                raise HTTPException(status_code=401, detail="missing or wrong access token")
            request.state.device = device
            return
        if not supplied or not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="missing or wrong access token")

    @app.get("/pair/info")
    def pair_info() -> dict:
        """What the sign-in screen may know before anyone is signed in. Not the PC's name or anything else about it:
        that is shown only after a phone has paired."""
        return {"accounts": accounts is not None, "ready": accounts is None or accounts.owner_exists}

    @app.post("/pair/claim")
    def pair_claim(body: ClaimIn, request: Request) -> dict:
        """Trade a one-time pairing code (from the QR code on the PC) for this phone's own token."""
        if accounts is None:
            raise HTTPException(status_code=404, detail="pairing is off on this PC")
        ip = request.client.host if request.client else ""
        try:
            device, device_token = accounts.pair(body.code, body.name, ip, body.previous)
        except Locked as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        except DeviceLimit as exc:
            manager.note("pair_refused_limit", ip=ip)
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except AccountError as exc:
            manager.note("pair_failed", ip=ip)
            raise HTTPException(status_code=400, detail=str(exc)) from None
        manager.note("device_paired", device=device.name, device_id=device.id, ip=ip)
        return {"token": device_token, "device": device.public(), "pc": platform.node()}

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    def job_or_error(action, job_id: str) -> dict:
        try:
            return action(job_id).to_dict()
        except JobNotFound:
            raise HTTPException(status_code=404, detail="no such job") from None
        except JobStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @api.post("/jobs")
    def create_job(body: PromptIn) -> dict:
        if body.conversation is not None and not _CONVERSATION.match(body.conversation):
            raise HTTPException(status_code=422, detail="conversation must be letters, digits, - or _")
        return manager.submit(body.prompt, body.conversation, body.file).to_dict()

    @api.get("/jobs")
    def list_jobs() -> list[dict]:
        return [j.to_dict() for j in manager.list()]

    @api.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return job_or_error(manager.get, job_id)

    @api.post("/jobs/{job_id}/approve")
    def approve(job_id: str, body: ApproveIn | None = None) -> dict:
        try:
            return manager.approve(job_id, body.pin if body else None).to_dict()
        except UnlockError as exc:  # a missing or wrong unlock PIN: the request stays waiting, and the card says why
            raise HTTPException(status_code=422 if exc.code == "pin_required" else 403, detail={"code": exc.code, "message": str(exc), **exc.extra}) from None
        except JobNotFound:
            raise HTTPException(status_code=404, detail="no such job") from None
        except JobStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @api.post("/jobs/{job_id}/reject")
    def reject(job_id: str) -> dict:
        return job_or_error(manager.reject, job_id)

    @api.post("/jobs/{job_id}/undo")
    def undo(job_id: str) -> dict:
        return job_or_error(manager.undo, job_id)

    @api.post("/jobs/{job_id}/access")
    def access(job_id: str, body: AccessIn) -> dict:
        """Your answer to "may I open this folder?"."""
        return job_or_error(lambda jid: manager.decide_access(jid, body.decision), job_id)

    @api.post("/access/revoke")
    def revoke(body: PathIn) -> dict:
        return {"granted": manager.revoke_access(body.path), "granted_details": manager.granted_details()}

    @api.post("/jobs/{job_id}/stop")
    def stop(job_id: str) -> dict:
        return job_or_error(manager.stop, job_id)

    @api.get("/audit")
    def audit() -> list[dict]:
        return manager.audit_events()

    @api.post("/device/rename")
    def device_rename(body: DeviceNameIn, request: Request) -> dict:
        if accounts is None:
            raise HTTPException(status_code=404, detail="no accounts")
        device = accounts.rename(request.state.device.id, body.name)
        manager.note("device_renamed", device=device.name, device_id=device.id)
        return device.public()

    @api.delete("/device")
    def device_sign_out(request: Request) -> dict:
        """This phone signs itself out: its token stops working for good."""
        if accounts is not None:
            device: Device = request.state.device
            accounts.remove(device.id)
            manager.note("device_signed_out", device=device.name, device_id=device.id)
        return {"ok": True}

    def owner_ok(body: DeviceRemoveIn, request: Request) -> bool:
        """The PC owner's password (or Windows sign-in) typed on a phone. Too many wrong tries wait, like at the PC."""
        ip = request.client.host if request.client else ""
        try:
            return accounts.windows_sign_in(body.username, body.password) if accounts.mode == "windows" else accounts.verify_owner(body.password, "owner:" + ip)
        except Locked as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None

    def owner_refusal() -> str:
        return "That user name or Windows password is not right." if accounts.mode == "windows" else "That password is not right."

    @api.post("/owner/check")
    def owner_check(body: DeviceRemoveIn, request: Request) -> dict:
        """Used to reset a forgotten app PIN: the phone proves the PC owner's password instead of signing out and losing its chats."""
        if accounts is None:
            raise HTTPException(status_code=404, detail="no accounts")
        if not owner_ok(body, request):
            manager.note("owner_check_refused", by=request.state.device.name)
            raise HTTPException(status_code=403, detail=owner_refusal())
        manager.note("app_pin_reset", by=request.state.device.name)
        return {"ok": True}

    @api.get("/devices")
    def devices_list(request: Request) -> dict:
        """Who is connected, so a full PC can be sorted out from the phone (removing one still needs the PC owner's password)."""
        if accounts is None:
            raise HTTPException(status_code=404, detail="no accounts")
        me = request.state.device.id
        return {"limit": settings.accounts.max_devices, "mode": accounts.mode, "owner": accounts.owner_name,
                "devices": [{**d, "current": d["id"] == me} for d in accounts.devices()]}

    @api.post("/devices/{device_id}/remove")
    def device_remove(device_id: str, body: DeviceRemoveIn, request: Request) -> dict:
        """Take another phone off this PC. Any paired phone can ask, but only the PC owner's password lets it happen."""
        if accounts is None:
            raise HTTPException(status_code=404, detail="no accounts")
        me: Device = request.state.device
        if device_id == me.id:
            raise HTTPException(status_code=400, detail="That is this phone. Use Sign out instead.")
        if not owner_ok(body, request):
            manager.note("device_remove_refused", by=me.name, device_id=device_id)
            raise HTTPException(status_code=403, detail=owner_refusal())
        try:
            gone = accounts.remove(device_id)
        except AccountError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        manager.note("device_removed_from_phone", device=gone.name, device_id=gone.id, by=me.name)
        return {"ok": True}

    @api.get("/ping")
    def ping() -> dict:
        """The phone's heartbeat: cheap, and it needs the phone's token, so a phone this PC removed finds out here (401).
        `v` lets a phone notice the PC was updated while it was away."""
        return {"ok": True, "v": _version()}

    unlock_seen: dict = {"at": 0.0, "value": {}}

    def unlock_summary() -> dict:
        """Whether unlocking is set up and whether the PC is locked, for the phone's Home screen. Asked of the helper at most every few seconds."""
        if time.monotonic() - unlock_seen["at"] < 4:
            return unlock_seen["value"]
        info = manager.unlocker.status()
        unlock_seen.update(at=time.monotonic(), value={k: info.get(k) for k in ("running", "configured", "enabled", "attention", "locked")})
        return unlock_seen["value"]

    @api.get("/status")
    def status() -> dict:
        """How this PC is doing right now: battery, network speed, processor, memory, disk, and whether it is locked."""
        return {**sysinfo.current(), "unlock": unlock_summary()}

    @api.get("/info")
    def info(request: Request) -> dict:
        """What this PC is set up to do. Read-only: settings are changed in config.yaml, never from the phone."""
        if isinstance(planner, AnthropicPlanner):
            ai, model = "hosted", settings.llm.hosted_model
        elif isinstance(planner, OllamaPlanner):
            ai, model = "local", settings.llm.model
        elif isinstance(planner, DemoPlanner):
            ai, model = "none", ""
        else:
            ai, model = "custom", ""
        agent = settings.agent
        return {
            "app": "AccessFromPhone",
            "version": _version(),
            "pc": platform.node(),
            "user": _user(),
            "accounts": accounts is not None,
            "device": request.state.device.public() if accounts is not None else None,
            "owner": accounts.owner_name if accounts is not None else "",
            "ai": {"kind": ai, "model": model, "note": note},
            "commands_enabled": settings.commands.enabled,
            "command_timeout_seconds": settings.commands.timeout_seconds,
            "folders": {
                "writable": [str(f) for f in agent.allowed_folders],
                "read_only": [str(f) for f in agent.read_only_folders],
                "granted": manager.granted_folders(),
                "granted_details": manager.granted_details(),
            },
            "max_edit_kb": agent.max_edit_kb,
            "max_view_kb": agent.max_view_kb,
            "allow_edit_grants": agent.allow_edit_grants,
            "ask_for_access": agent.ask_for_access,
            "approval": {
                "required_for": list(settings.approval.require_for),
                "timeout_minutes": settings.approval.timeout_minutes,
            },
            "max_download_mb": agent.max_download_mb,
            "power_actions": list(settings.power.remote_actions),  # what the Home screen may offer (lock, sleep, ...)
            "memory_turns": settings.llm.memory_turns,
            "https": settings.server.https,
        }

    @api.get("/file")
    def open_for_editing(path: str) -> dict:
        """A file's text and whether it can be changed, for the phone's editor."""
        try:
            return manager.open_file(path)
        except OutsideAllowed as exc:
            raise HTTPException(status_code=403, detail={"code": "needs_access", "folder": _folder_of(exc.path), "message": str(exc)}) from None
        except PathDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @api.get("/file/raw")
    def picture_or_pdf(path: str):
        """A picture or PDF for the viewer. Reading only, and only these types."""
        try:
            real, mime = manager.raw_file(path)
        except OutsideAllowed as exc:
            raise HTTPException(status_code=403, detail={"code": "needs_access", "folder": _folder_of(exc.path), "message": str(exc)}) from None
        except PathDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except FileTooBig as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from None
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return FileResponse(real, media_type=mime, headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    def _browse_errors(exc: Exception) -> HTTPException:
        if isinstance(exc, OutsideAllowed):
            return HTTPException(status_code=403, detail={"code": "needs_access", "folder": _folder_of(exc.path), "message": str(exc)})
        if isinstance(exc, PathDenied):
            return HTTPException(status_code=403, detail=str(exc))
        if isinstance(exc, FileTooBig):
            return HTTPException(status_code=413, detail=str(exc))
        if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, PermissionError):
            return HTTPException(status_code=403, detail="Windows doesn't let this app open that folder.")
        raise exc

    @api.get("/browse")
    def browse_folder(path: str = "", q: str = "", sort: str = "name", order: str = "asc", hidden: bool = False, offset: int = 0, limit: int = 200) -> dict:
        """One folder's contents for the file browser; with no path, the places it may start from."""
        try:
            return manager.browse(path, q=q[:100], sort=sort, order="desc" if order == "desc" else "asc", hidden=hidden, offset=offset, limit=limit)
        except (PathDenied, FileNotFoundError, NotADirectoryError, PermissionError) as exc:
            raise _browse_errors(exc) from None

    @api.post("/browse/stream")
    def browse_stream(path: str) -> dict:
        """A short-lived link for playing a video or audio file."""
        try:
            return manager.stream_link(path)
        except (PathDenied, FileNotFoundError, PermissionError) as exc:
            raise _browse_errors(exc) from None

    @api.post("/browse/offer")
    def browse_offer(path: str) -> dict:
        """Tapping Download in the browser makes that one file fetchable through /api/files."""
        try:
            return manager.offer_file(path)
        except (PathDenied, FileTooBig, FileNotFoundError, PermissionError) as exc:
            raise _browse_errors(exc) from None

    @app.get("/dl/{key}")
    def download_stream(key: str):
        """The file behind a download link, as an attachment. Ranges work, so the phone can fetch a huge file piece by piece."""
        try:
            real = manager.downloadable(key)
        except PathDenied:
            raise HTTPException(status_code=404, detail="This link has run out.") from None
        return FileResponse(real, filename=real.name, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.get("/stream/{key}")
    def stream(key: str):
        """Video or audio for the player. No header can be sent from a player, so the unguessable link is the key. Ranges work, so it seeks."""
        try:
            real, mime = manager.stream_file(key)
        except (PathDenied, FileNotFoundError):
            raise HTTPException(status_code=404, detail="This link has run out.") from None
        return FileResponse(real, media_type=mime, headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @api.get("/images")
    def pictures_in_folder(path: str = "") -> dict:
        """The pictures directly inside a folder, newest first, for the gallery."""
        try:
            return manager.list_images(path)
        except OutsideAllowed as exc:
            raise HTTPException(status_code=403, detail={"code": "needs_access", "folder": _folder_of(exc.path), "message": str(exc)}) from None
        except PathDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @api.get("/thumb")
    def picture_thumbnail(path: str, size: int = 256) -> Response:
        """A small copy of one picture, for the gallery. Made once, then kept."""
        try:
            data, mime = manager.thumb(path, size)
        except OutsideAllowed as exc:
            raise HTTPException(status_code=403, detail={"code": "needs_access", "folder": _folder_of(exc.path), "message": str(exc)}) from None
        except PathDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except FileTooBig as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from None
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except Exception as exc:  # a damaged picture, or no Pillow: the gallery shows a plain tile instead
            raise HTTPException(status_code=415, detail="No thumbnail for this picture.") from exc
        return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

    @api.put("/image")
    async def save_picture(request: Request, path: str, base_sha: str | None = None, unique: bool = False, conversation: str | None = None, note: str = "") -> dict:
        """A picture the user edited on the phone, sent as the file's own bytes. Their tap on Save is the approval; it can be undone."""
        if conversation is not None and not _CONVERSATION.match(conversation):
            raise HTTPException(status_code=422, detail="conversation must be letters, digits, - or _")
        limit = settings.agent.max_image_mb * 1024 * 1024
        if int(request.headers.get("content-length") or 0) > limit + 4096:
            raise HTTPException(status_code=413, detail=f"That picture is over the {settings.agent.max_image_mb} MB the editor saves.")
        data = await request.body()
        try:
            return await run_in_threadpool(manager.save_image, path, data, base_sha, conversation, unique, note)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except FileChanged as exc:
            raise HTTPException(status_code=409, detail={"code": "changed", "message": str(exc)}) from None
        except (ReadOnlyPath, OutsideAllowed) as exc:
            folder = _folder_of(exc.path) if isinstance(exc, OutsideAllowed) else str(Path(path).resolve().parent)
            raise HTTPException(status_code=403, detail={"code": "needs_change_access", "folder": folder, "message": str(exc)}) from None
        except PathDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @api.put("/file")
    def save_from_editor(body: FileIn) -> dict:
        """The user's own edits. Their tap on Save is the approval."""
        if body.conversation is not None and not _CONVERSATION.match(body.conversation):
            raise HTTPException(status_code=422, detail="conversation must be letters, digits, - or _")
        try:
            return manager.save_file(body.path, body.text, body.base_sha, body.conversation)
        except FileChanged as exc:
            raise HTTPException(status_code=409, detail={"code": "changed", "message": str(exc)}) from None
        except (ReadOnlyPath, OutsideAllowed) as exc:
            folder = _folder_of(exc.path) if isinstance(exc, OutsideAllowed) else str(Path(body.path).resolve().parent)
            raise HTTPException(status_code=403, detail={"code": "needs_change_access", "folder": folder, "message": str(exc)}) from None
        except PathDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except FileTooBig as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from None

    @api.post("/access/grant")
    def grant(body: GrantIn) -> dict:
        """Allow a folder from the editor: reading it, and with `change`, editing files in it. Kept until removed."""
        try:
            return {"granted": manager.grant_folder(body.path, body.change)}
        except PathDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @api.post("/files/link")
    def download_link(path: str) -> dict:
        """A streaming link for an offered file, so a file of any size reaches the phone without being held in memory."""
        try:
            return manager.download_link(path)
        except PathDenied:
            raise HTTPException(status_code=403, detail="that file is not available for download") from None
        except FileTooBig as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="no such file") from None

    @api.get("/files")
    def download(path: str):
        try:
            real = manager.file_for_download(path)
        except PathDenied:
            raise HTTPException(status_code=403, detail="that file is not available for download") from None
        except FileTooBig as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from None
        if not real.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(real, filename=real.name)

    # -- notifications ---------------------------------------------------------
    # Push belongs to a paired phone, so it needs accounts: with them off (testing only) there is nobody to address.

    def push_device(request: Request) -> Device:
        device = getattr(request.state, "device", None)
        if device is None or not notifier.enabled:
            raise HTTPException(status_code=404, detail="notifications are not set up on this PC")
        return device

    @api.get("/push")
    def push_info(request: Request) -> dict:
        device = getattr(request.state, "device", None)
        on = notifier.enabled and device is not None
        return {"enabled": on, "web": notifier.web.public_key if on and notifier.web else None, "fcm": bool(on and notifier.fcm),
                "subscribed": notifier.kinds(device.id) if on else []}

    @api.post("/push/subscribe")
    def push_subscribe(body: PushSubIn, request: Request) -> dict:
        device = push_device(request)
        try:
            if body.kind == "web":
                notifier.subscribe_web(device.id, body.endpoint, body.keys.get("p256dh", ""), body.keys.get("auth", ""))
            else:
                notifier.subscribe_fcm(device.id, body.token)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        manager.note("push_on", device=device.name, kind=body.kind)
        return {"ok": True, "subscribed": notifier.kinds(device.id)}

    @api.post("/push/unsubscribe")
    def push_unsubscribe(body: PushOffIn, request: Request) -> dict:
        device = push_device(request)
        notifier.unsubscribe(device.id, body.kind)
        manager.note("push_off", device=device.name, kind=body.kind or "all")
        return {"ok": True, "subscribed": notifier.kinds(device.id)}

    @api.post("/push/test")
    def push_test(request: Request) -> dict:
        device = push_device(request)
        return notifier.send(Message("Notifications are on", "This is a test from your PC.", "", "test"), device.id).public()

    app.include_router(api)

    @app.get("/sw.js")
    def service_worker() -> Response:
        """The service worker (it shows notifications and keeps the page's shell for offline). It must be served from the root to cover the whole page."""
        script = (_WEB / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", _version())
        return Response(script, media_type="text/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/healthz")
    def health() -> dict:
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    app.mount("/static", _Assets(directory=_WEB), name="static")
    return app
