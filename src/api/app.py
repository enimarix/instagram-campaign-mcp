"""
FastAPI app: thin routes onto service functions (GOAL.md §4).

Build it with `create_app()`; `ig-campaign serve` runs it on uvicorn.
Without an Instagram token the app still starts ("setup mode"): /api/health
says so and Graph-backed routes answer 503 instagram_not_configured.
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

ClientFactory = Callable[[InstagramMCPSettings], InstagramClient]

try:
    VERSION = version("instagram-campaign-mcp")
except PackageNotFoundError:  # running from a plain source checkout
    VERSION = "unknown"


def create_app(
    settings: Optional[InstagramMCPSettings] = None,
    client_factory: ClientFactory = InstagramClient,
) -> FastAPI:
    settings = settings or get_settings()

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
