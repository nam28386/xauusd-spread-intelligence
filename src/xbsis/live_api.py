"""Loopback live hub: read-only routes and strict browser origin checks."""

import asyncio
import time
from collections import deque
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from xbsis.live_hub import LiveHub


def create_live_app(mode, sources, duration, port, *, hub=None):
    hub = hub or LiveHub(mode, sources, duration)
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    if port == 80:
        allowed_origins.update({"http://127.0.0.1", "http://localhost"})
    recent_requests = deque(maxlen=120)

    @asynccontextmanager
    async def lifespan(app):
        hub.start()
        try:
            yield
        finally:
            hub.close()

    app = FastAPI(
        title="XBSIS local live", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.hub = hub

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            return Response(status_code=403)
        now = time.monotonic()
        while recent_requests and now - recent_requests[0] > 10:
            recent_requests.popleft()
        if len(recent_requests) >= 120:
            return Response(status_code=429, headers={"Retry-After": "10"})
        recent_requests.append(now)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            f"connect-src 'self' ws://127.0.0.1:{port} ws://localhost:{port}; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/", include_in_schema=False)
    async def index():
        return RedirectResponse(url="/live/", status_code=307)

    @app.get("/live/", response_class=HTMLResponse)
    async def dashboard():
        return files("xbsis.live_assets").joinpath("index.html").read_text(encoding="utf-8")

    @app.get("/live/app.js")
    async def javascript():
        return Response(
            files("xbsis.live_assets").joinpath("app.js").read_bytes(),
            media_type="application/javascript",
        )

    @app.get("/live/style.css")
    async def styles():
        return Response(
            files("xbsis.live_assets").joinpath("style.css").read_bytes(), media_type="text/css"
        )

    @app.get("/live/health")
    async def health():
        snap = hub.snapshot()
        return {
            "status": "ok",
            "scope": "api_only",
            "mode": snap["mode"],
            "sources": len(snap["sources"]),
            "source_statuses": [s["status"] for s in snap["sources"]],
            "rejected_events": snap["rejected_events"],
        }

    @app.get("/live/sources")
    async def sources_route():
        return [
            {k: v for k, v in s.items() if k not in {"latest", "last_valid"}}
            for s in hub.snapshot()["sources"]
        ]

    @app.get("/live/latest")
    async def latest():
        return hub.snapshot()

    @app.get("/live/history")
    async def history(
        source_id: Annotated[str, Query(min_length=1, max_length=128)],
        seconds: Annotated[int, Query(ge=1, le=300)] = 120,
    ):
        result = hub.history(source_id, seconds)
        if result is None:
            raise HTTPException(status_code=404, detail="unknown source")
        return {"source_id": source_id, "points": result}

    @app.websocket("/live/ws")
    async def websocket(websocket: WebSocket):
        if websocket.headers.get("origin") not in allowed_origins or hub.clients >= 8:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        hub.clients += 1
        previous = {}
        coalesced = 0
        try:
            while True:
                snapshot = hub.snapshot()
                for source in snapshot["sources"]:
                    seq = source["sequence"]
                    if source["source_id"] in previous:
                        coalesced += max(0, seq - previous[source["source_id"]] - 1)
                    previous[source["source_id"]] = seq
                snapshot["display_coalesced"] = coalesced
                await websocket.send_json(snapshot)
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            hub.clients -= 1

    return app
