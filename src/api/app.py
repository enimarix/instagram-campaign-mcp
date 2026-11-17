"""
FastAPI app: thin routes onto service functions (GOAL.md §4).

Build it with `create_app()`; `ig-campaign serve` runs it on uvicorn.
Without an Instagram token the app still starts ("setup mode"): /api/health
says so and Graph-backed routes answer 503 instagram_not_configured.
With UI_PASSWORD set, /api/* needs a session cookie from POST /api/login (see auth.py).
The built website (`web/dist`) is served at every other path, with an SPA fallback.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from .. import campaign
from ..config import InstagramMCPSettings, get_settings
from ..instagram_client import InstagramAPIError, InstagramClient
from ..store import CampaignStore
from . import assets, context, feedback, media, worker
from .auth import COOKIE, Auth, Locked, host_ok, origin_ok

# Reachable without a session even when UI_PASSWORD is set.
PUBLIC_PATHS = {"/api/health", "/api/login", "/api/logout", "/api/session"}

ClientFactory = Callable[[InstagramMCPSettings], InstagramClient]

try:
    VERSION = version("instagram-campaign-mcp")
except PackageNotFoundError:  # running from a plain source checkout
    VERSION = "unknown"


def create_app(
    settings: Optional[InstagramMCPSettings] = None,
    client_factory: ClientFactory = InstagramClient,
    auth: Optional[Auth] = None,
    store: Optional[CampaignStore] = None,
) -> FastAPI:
    """`store`: injected (tests; the caller closes it), else opened from settings.database_path."""
    settings = settings or get_settings()
    auth = auth or Auth(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or CampaignStore(settings.database_path)
        app.state.client = client_factory(settings) if settings.instagram_configured else None
        try:
            yield
        finally:
            if store is None:
                app.state.store.close()
            if app.state.client is not None:
                await app.state.client.close()

    app = FastAPI(title="Macrobody Growth Studio", version=VERSION, lifespan=lifespan)

    @app.exception_handler(InstagramAPIError)
    async def graph_error(request: Request, e: InstagramAPIError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"error": "instagram_api_error", "message": e.message,
                     "code": e.error_code, "subcode": e.error_subcode},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, e: RequestValidationError) -> JSONResponse:
        message = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}"
                            for err in e.errors())
        return JSONResponse(status_code=422, content={"error": "invalid", "message": message})

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not host_ok(request.url.hostname, auth.required):
            return JSONResponse(status_code=403, content={"error": "bad_host"})
        token = request.cookies.get(COOKIE)
        if not origin_ok(request.method, str(request.url), request.headers, token is not None):
            return JSONResponse(status_code=403, content={"error": "bad_origin"})
        path = request.scope["path"]  # the decoded path the router matches on
        if (auth.required and (path == "/api" or path.startswith("/api/"))
                and path not in PUBLIC_PATHS and not auth.valid(token)):
            return JSONResponse(status_code=401, content={"error": "login_required"})
        return await call_next(request)

    @app.post("/api/login")
    async def login(request: Request):
        try:
            password = (await request.json())["password"]
        except Exception:  # noqa: BLE001 - any malformed body; never echo it back
            password = None
        if not isinstance(password, str):
            return JSONResponse(status_code=400, content={"error": "password_required"})
        try:
            ok = auth.check_password(password)
        except Locked as e:
            return JSONResponse(status_code=429, content={"error": "locked",
                                                          "retry_after": e.retry_after},
                                headers={"Retry-After": str(e.retry_after)})
        if not ok:
            return JSONResponse(status_code=401, content={"error": "bad_password"})
        response = JSONResponse({"authenticated": True})
        response.set_cookie(COOKIE, auth.new_session(), max_age=int(auth.ttl), path="/",
                            httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        return response

    @app.post("/api/logout")
    async def logout(request: Request):
        auth.logout(request.cookies.get(COOKIE))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict",
                               secure=request.url.scheme == "https")
        return response

    @app.get("/api/session")
    async def session(request: Request) -> dict:
        return {"authenticated": auth.valid(request.cookies.get(COOKIE)),
                "password_required": auth.required}

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "instagram_configured": settings.instagram_configured,
                "version": VERSION}

    @app.get("/api/account")
    async def account(request: Request):
        client = request.app.state.client
        if client is None:
            return JSONResponse(status_code=503, content={"error": "instagram_not_configured"})
        return await campaign.account_status(client)

    app.state.media_root = settings.media_root
    app.state.settings = settings
    app.include_router(assets.router)
    app.include_router(media.router)
    app.include_router(feedback.router)
    app.include_router(context.router)
    app.include_router(worker.router)
    _serve_website(app, Path(settings.web_dist))  # catch-all: keep it last
    return app


NOT_BUILT = ("<!doctype html><title>Macrobody Growth Studio</title><p>Website not built: run "
             "<code>npm --prefix web ci &amp;&amp; npm --prefix web run build</code>, then restart."
             " The API under <code>/api</code> works meanwhile.")


def _serve_website(app: FastAPI, dist: Path) -> None:
    """Catch-all GET, registered last: real files from `dist`, else index.html (SPA routes).

    Public on purpose (the login page must load); /api/* stays behind the guard and unknown
    /api paths answer JSON 404. StaticFiles does the lookup, which refuses paths outside `dist`.
    """
    index = dist / "index.html"
    if not index.is_file():
        @app.get("/", include_in_schema=False)
        async def not_built() -> HTMLResponse:
            return HTMLResponse(NOT_BUILT)
        return

    static = StaticFiles(directory=dist)

    @app.get("/{path:path}", include_in_schema=False)
    async def website(path: str, request: Request):
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "not_found"})
        try:
            return await static.get_response(static.get_path(request.scope), request.scope)
        except HTTPException:  # not a file in dist: a client-side route
            return FileResponse(index)
