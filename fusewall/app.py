"""Single-owner local API and static dashboard. No external upstream is enabled."""

import asyncio
import csv
import hmac
import io
import re
import secrets
import sqlite3
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, engine, reporting
from .models import Completion, KeyCreate, KeyPatch, LabRun, Login, Replay, Preview, Resolution, SettingsPatch
from .runtime import InstanceLock
from .store import Fault, RATES, RATE_VERSION, Store, digest

STATIC = Path(__file__).parent / "static"
COOKIE = "fusewall_owner"


def create_app(data_dir=None):
    store = Store(data_dir or Path.cwd() / ".fusewall")
    lock = InstanceLock(store.directory / "server.lock")
    auth_sessions = {}
    login_attempts = deque(maxlen=100)
    lab_busy = False

    @asynccontextmanager
    async def lifespan(app):
        lock.acquire()
        try:
            store.recover()
            yield
        finally:
            lock.release()

    app = FastAPI(title="Fusewall Local", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.exception_handler(Fault)
    async def domain_fault(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, "details": exc.details}}, status_code=exc.status,
                            headers={"Retry-After": "2"} if exc.status == 429 else {})

    @app.exception_handler(sqlite3.Error)
    async def storage_fault(request, exc):
        return JSONResponse({"error": {"code": "storage_unavailable", "message": "Budget authority is unavailable. New protected work is rejected."}}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not echo submitted prompts, credentials, or invalid input bodies.
        fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        return JSONResponse({"error": {"code": "invalid_request", "message": "Check the supported fields and bounds.", "fields": fields}}, status_code=422)

    @app.middleware("http")
    async def guards(request: Request, call_next):
        # Host validation protects loopback deployments against DNS rebinding.
        host = request.headers.get("host", "")
        try:
            hostname = urlsplit("http://" + host).hostname
        except ValueError:
            hostname = None
        if hostname not in ("localhost", "127.0.0.1", "::1", "testserver"):
            return JSONResponse({"error": {"code": "invalid_host", "message": "This installation only serves local hosts."}}, status_code=400)
        if request.method in ("POST", "PATCH", "DELETE", "PUT"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{host}":
                return JSONResponse({"error": {"code": "invalid_origin", "message": "Cross-origin writes are disabled."}}, status_code=403)
            if request.url.path.startswith("/api/") and request.headers.get("x-fusewall-request") != "dashboard":
                return JSONResponse({"error": {"code": "request_header_required", "message": "The dashboard request header is required."}}, status_code=403)
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 65_536):
                return JSONResponse({"error": {"code": "body_too_large", "message": "Request body limit is 64 KiB."}}, status_code=413)
            # Read a bounded body even when Content-Length is absent or incorrect.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65_536:
                    return JSONResponse({"error": {"code": "body_too_large", "message": "Request body limit is 64 KiB."}}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Fusewall-Mode"] = "simulation"
        return response

    def owner(request: Request):
        raw = request.cookies.get(COOKIE, "")
        expiry = auth_sessions.get(digest(raw), 0)
        if not raw or expiry <= time.time():
            raise Fault(401, "owner_required", "Unlock this local installation with its owner token.")

    def workload(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise Fault(401, "invalid_key", "Supply a Fusewall workload key as a Bearer token.")
        return store.authenticate(authorization[7:])

    @app.get("/health/live")
    def live():
        return {"status": "alive", "version": __version__, "mode": "simulation"}

    @app.get("/health/ready")
    def ready():
        store.read("SELECT 1")
        return {"status": "ready", "mode": "simulation"}

    @app.post("/api/login")
    async def login(body: Login, request: Request):
        # No await in this block: rate counters and session mutations stay on the event loop.
        now = time.time()
        while login_attempts and login_attempts[0] < now-60:
            login_attempts.popleft()
        if len(login_attempts) >= 10:
            raise Fault(429, "login_rate_limit", "Too many unlock attempts. Wait one minute.")
        login_attempts.append(now)
        if not hmac.compare_digest(digest(body.token), store.admin_hash):
            raise Fault(401, "invalid_owner_token", "Owner token did not match.")
        for value in list(auth_sessions):
            if auth_sessions[value] < now:
                auth_sessions.pop(value)
        if len(auth_sessions) >= 20:
            auth_sessions.pop(next(iter(auth_sessions)))
        raw = secrets.token_urlsafe(32)
        auth_sessions[digest(raw)] = now + 8*3600
        response = JSONResponse({"ok": True, "mode": "simulation"})
        response.set_cookie(COOKIE, raw, httponly=True, samesite="strict", max_age=8*3600, secure=request.url.scheme == "https")
        return response

    @app.post("/api/logout", dependencies=[Depends(owner)])
    async def logout(request: Request):
        auth_sessions.pop(digest(request.cookies.get(COOKIE, "")), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE)
        return response

    @app.get("/api/state", dependencies=[Depends(owner)])
    def state():
        return {"overview": store.overview(), "keys": store.list_keys(), "sessions": store.sessions(),
                "requests": store.request_list(), "events": store.read("SELECT * FROM events ORDER BY id DESC LIMIT 80"),
                "rates": RATES, "rate_version": RATE_VERSION, "version": __version__}

    @app.post("/api/keys", dependencies=[Depends(owner)])
    def create_key(body: KeyCreate):
        return store.create_key(body)

    @app.patch("/api/keys/{key_id}", dependencies=[Depends(owner)])
    def patch_key(key_id: str, body: KeyPatch):
        store.patch_key(key_id, body.active)
        return {"ok": True}

    @app.patch("/api/settings", dependencies=[Depends(owner)])
    def settings(body: SettingsPatch):
        store.update_settings(body.budget_micro, body.paused)
        return store.settings()

    @app.get("/api/requests", dependencies=[Depends(owner)])
    def requests(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=50_000),
                 status: str | None = None, key_id: str | None = Query(None, max_length=80), search: str = Query("", max_length=100)):
        return reporting.request_page(store, limit, offset, status, key_id, search)

    @app.get("/api/requests/{request_id}", dependencies=[Depends(owner)])
    def request_receipt(request_id: str):
        return reporting.receipt(store, request_id)

    @app.get("/api/insights", dependencies=[Depends(owner)])
    def insights():
        return reporting.insights(store)

    @app.post("/api/preview", dependencies=[Depends(owner)])
    def preview(body: Preview):
        return reporting.preview(store, body.key_id, body.session_id, body.completion.model_dump())

    @app.post("/api/replay", dependencies=[Depends(owner)])
    def replay(body: Replay):
        return store.replay(body.budget_micro, body.limit)

    @app.post("/api/integrity", dependencies=[Depends(owner)])
    def integrity():
        return store.integrity()

    @app.post("/api/backup", dependencies=[Depends(owner)])
    def backup():
        path = store.backup()
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.post("/api/requests/{request_id}/resolve", dependencies=[Depends(owner)])
    def resolve(request_id: str, body: Resolution):
        return store.resolve(request_id, body.actual_micro, body.reason)

    @app.get("/api/export", dependencies=[Depends(owner)])
    def export():
        rows = store.request_list(50_000)
        output = io.StringIO()
        columns = ["id", "created", "key_name", "client", "external_id", "model", "status", "reason", "reserved", "actual", "input_tokens", "output_tokens", "rate_version"]
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        # Prevent spreadsheet formula execution when opening user-created names.
        for row in rows:
            writer.writerow({k: ("'" + str(v) if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v) for k, v in row.items()})
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="fusewall-simulated-usage.csv"'})

    @app.get("/v1/models")
    def models(key_id=Depends(workload)):
        key = next(k for k in store.list_keys() if k["id"] == key_id)
        return {"object": "list", "data": [{"id": name, "object": "model", "owned_by": "fusewall-simulator"} for name in key["allowed_models"]]}

    @app.post("/v1/chat/completions")
    async def completion(body: Completion, request: Request, key_id=Depends(workload),
                         x_fusewall_session: str = Header(default="default"), idempotency_key: str | None = Header(default=None)):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", x_fusewall_session):
            raise Fault(400, "invalid_session", "Session ID must use 1–80 letters, digits, underscores or hyphens.")
        if idempotency_key and not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", idempotency_key):
            raise Fault(400, "invalid_idempotency_key", "Invalid idempotency key.")
        data = body.model_dump()
        if body.stream:
            ticket = await engine.reserve_ticket(store, key_id, x_fusewall_session, data, "normal", idempotency_key)
            try:
                await engine.database_call(store.dispatch, ticket["id"])
            except asyncio.CancelledError:
                await engine.database_call(store.finish, ticket["id"], 0, "canceled")
                raise
            return StreamingResponse(engine.stream(store, ticket, data, request.is_disconnected), media_type="text/event-stream",
                                     headers={"X-Fusewall-Request-ID": ticket["id"], "X-Accel-Buffering": "no"})
        return await engine.execute(store, key_id, x_fusewall_session, data, idempotency=idempotency_key)

    @app.post("/api/lab", dependencies=[Depends(owner)])
    async def lab(body: LabRun):
        nonlocal lab_busy
        if lab_busy:
            raise Fault(409, "lab_busy", "A laboratory run is already active. Wait for it to complete.")
        lab_busy = True
        try:
            return await engine.run_lab(store, body)
        finally:
            lab_busy = False

    @app.get("/api/schema", dependencies=[Depends(owner)])
    def schema():
        return app.openapi()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def dashboard():
        return FileResponse(STATIC / "index.html")

    return app
