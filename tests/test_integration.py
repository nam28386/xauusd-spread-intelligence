import json
import subprocess
import sys
from decimal import Decimal

import duckdb
import pytest
from fastapi.testclient import TestClient

from xbsis.adapters.mock import MockBrokerAdapter
from xbsis.api import create_app
from xbsis.models import Observation, QualityFlag
from xbsis.storage import ObservationStore


def test_replay_golden_rows_and_determinism():
    adapter = MockBrokerAdapter()
    first = adapter.replay()
    assert first == adapter.replay() == MockBrokerAdapter().replay()
    assert len(first) == 9
    assert [r.spread.spread_usd_per_oz for r in first] == [
        Decimal("0.25000"),
        Decimal("0.25000"),
        None,
        None,
        None,
        Decimal("0.10000"),
        Decimal("0.02000"),
        Decimal("0.00000"),
        None,
    ]
    assert [set(r.spread.data_quality_flags) for r in first] == [
        set(),
        {QualityFlag.DUPLICATE},
        {QualityFlag.CROSSED},
        {QualityFlag.MISSING_BID},
        {QualityFlag.INVALID_BID},
        {QualityFlag.STALE},
        {QualityFlag.FUTURE_SOURCE_TIME},
        {QualityFlag.SOURCE_OUT_OF_ORDER},
        {QualityFlag.MISSING_ASK, QualityFlag.MISSING_SOURCE_TIME},
    ]
    assert first[5].quote.raw.source_time_ms < first[5].quote.raw.received_time_ns // 1_000_000


def test_storage_roundtrip_idempotence_and_parquet(tmp_path):
    records = MockBrokerAdapter().replay()
    database = tmp_path / "local.duckdb"
    destination = tmp_path / "local's copy.parquet"
    with ObservationStore(database) as store:
        ids = [store.append(r) for r in records]
        assert ids == [store.append(r) for r in records]
        assert len(store.records()) == len(records)
        assert store.records() == records
        store.export_parquet(destination)
        with pytest.raises(FileExistsError):
            store.export_parquet(destination)
    with ObservationStore(database) as store:
        assert store.records() == records
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT payload FROM read_parquet(?) ORDER BY ordinal", [str(destination)]
        ).fetchall()
    assert tuple(Observation.model_validate_json(row[0]) for row in rows) == records


def test_read_only_api_contract():
    with TestClient(create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "MOCK_REPLAY"
        assert health.json()["live_connectivity"] == "NOT_TESTED"
        response = client.get("/v1/quotes?limit=2")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 2
        assert rows[0]["spread"]["spread_usd_per_oz"] == "0.25000"
        assert rows[0]["quote"]["raw"]["received_time_ns"] == "1700000000010000123"
        assert rows[0]["quote"]["raw"]["ingestion_mode"] == "MOCK_REPLAY"
        assert client.get("/v1/metadata").json()["point_size"] == "0.01"
        assert client.get("/v1/quotes?limit=0").status_code == 422
        assert client.post("/v1/quotes", json={}).status_code == 405
        assert client.get("/health", headers={"host": "untrusted.example"}).status_code == 400
        schema = client.get("/openapi.json").json()
        assert all(set(methods) == {"get"} for methods in schema["paths"].values())


def test_cli_replay_repeats_identically_and_does_not_write_by_default(tmp_path):
    command = [sys.executable, "-m", "xbsis", "replay"]
    first = subprocess.run(  # noqa: S603 -- fixed interpreter/module, no shell or user input
        command, check=True, capture_output=True, text=True, cwd=tmp_path
    )
    second = subprocess.run(  # noqa: S603 -- same fixed command
        command, check=True, capture_output=True, text=True, cwd=tmp_path
    )
    assert first.stdout == second.stdout
    summary = json.loads(first.stdout)
    assert summary["records"] == 9
    assert summary["mode"] == "MOCK_REPLAY"
    assert list(tmp_path.iterdir()) == []


def test_fixture_corruption_detected_before_replay(tmp_path, monkeypatch):
    from importlib.resources import files

    import xbsis.adapters.mock as mock_module

    original = files("xbsis.fixtures")
    (tmp_path / "manifest.json").write_bytes(original.joinpath("manifest.json").read_bytes())
    (tmp_path / "quotes.json").write_bytes(original.joinpath("quotes.json").read_bytes() + b" ")
    monkeypatch.setattr(mock_module, "files", lambda _: tmp_path)
    with pytest.raises(ValueError, match="fixture hash mismatch"):
        mock_module.MockBrokerAdapter()
