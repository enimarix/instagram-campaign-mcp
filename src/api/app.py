"""
FastAPI app: thin routes onto service functions (GOAL.md §4).

Build it with `create_app()`; `ig-campaign serve` runs it on uvicorn.
Without an Instagram token the app still starts ("setup mode"): /api/health
says so and Graph-backed routes answer 503 instagram_not_configured.
With UI_PASSWORD set, /api/* needs a session cookie from POST /api/login (see auth.py).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .. import campaign
from ..config import InstagramMCPSettings, get_settings
from ..instagram_client import InstagramAPIError, InstagramClient
from .auth import COOKIE, Auth, Locked, origin_ok

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
) -> FastAPI:
    settings = settings or get_settings()
    auth = auth or Auth(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.client = client_factory(settings) if settings.instagram_configured else None
        try:
            yield
        finally:
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

    @app.middleware("http")
    async def guard(request: Request, call_next):
        token = request.cookies.get(COOKIE)
        if not origin_ok(request.method, str(request.url), request.headers, token is not None):
            return JSONResponse(status_code=403, content={"error": "bad_origin"})
        path = request.url.path
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

    return app
