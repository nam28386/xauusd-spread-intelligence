"""Read-only synthetic API. No arbitrary ingestion, file, or SDK endpoints."""

from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from xbsis.adapters.mock import MockBrokerAdapter
from xbsis.models import InstrumentMetadata, Observation


def create_app() -> FastAPI:
    adapter = MockBrokerAdapter()
    records = adapter.replay()
    app = FastAPI(title="XBSIS — synthetic Phase 01", version="0.1.0")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "MOCK_REPLAY", "live_connectivity": "NOT_TESTED"}

    @app.get("/v1/quotes", response_model=list[Observation])
    def quotes(limit: Annotated[int, Query(ge=1, le=100)] = 100) -> list[Observation]:
        return list(records[:limit])

    @app.get("/v1/metadata", response_model=InstrumentMetadata)
    def metadata() -> InstrumentMetadata:
        return adapter.metadata

    return app
