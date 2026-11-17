"""Hand-audited synthetic observations; no real market data."""

from decimal import Decimal, localcontext

import pytest

from xbsis.adapters.mock import MockBrokerAdapter
from xbsis.analytics import compare, summarize
from xbsis.models import RawQuote
from xbsis.pipeline import SpreadEngine
from xbsis.sessions import SessionRecorder, list_sessions, page, read_manifest

BASE = 1_700_000_000_000_000_000


def obs(seconds, ask, *, source="synthetic-source", env="UNKNOWN"):
    adapter = MockBrokerAdapter()
    template = next(adapter.quotes()).model_dump()
    ns = BASE + int(Decimal(str(seconds)) * 1_000_000_000)
    raw = RawQuote.model_validate(
        template
        | {
            "source_id": source,
            "account_environment": env,
            "bid": "2000.00",
            "ask": ask,
            "source_time_ms": ns // 1_000_000,
            "received_time_ns": ns,
        }
    )
    engine = SpreadEngine(mapping=adapter.mapping, mapping_version=adapter.mapping_version)
    return engine.process(raw, adapter.metadata, processing_time_ns=ns)


def test_golden_snapshot_percentiles_weighted_duration_and_widening():
    records = [obs(0, "2000.10"), obs(1, "2000.40"), obs(4, "2000.20"), obs(6, "2000.10")]
    result = summarize(
        records,
        start_ns=BASE,
        end_ns=BASE + 6_000_000_000,
        freshness_ns=5_000_000_000,
        widening_threshold=Decimal("0.20"),
    )
    assert result["snapshots"] == 4 and result["valid_snapshots"] == 4
    assert Decimal(result["mean"]) == Decimal("0.2")
    assert Decimal(result["median"]) == Decimal("0.15")
    assert Decimal(result["p95"]) == Decimal("0.37")
    assert Decimal(result["p99"]) == Decimal("0.394")
    with localcontext() as ctx:
        ctx.prec = 80
        assert Decimal(result["time_weighted_mean"]) == Decimal(17) / Decimal(60)
    assert Decimal(result["valid_coverage"]) == 1
    assert result["widening_count"] == 1
    event = result["widening_events"][0]
    assert event["widening_duration_ns"] == "5000000000"
    assert event["recovery_duration_ns"] == "2000000000" and event["recovered"]


def test_freshness_truncates_coverage_and_censors_widening():
    records = [obs(0, "2000.10"), obs(1, "2000.40"), obs(4, "2000.20"), obs(6, "2000.10")]
    result = summarize(
        records,
        start_ns=BASE,
        end_ns=BASE + 6_000_000_000,
        freshness_ns=2_000_000_000,
        widening_threshold=Decimal("0.20"),
    )
    assert result["valid_duration_ns"] == "5000000000"
    with localcontext() as ctx:
        ctx.prec = 80
        assert Decimal(result["valid_coverage"]) == Decimal(5) / Decimal(6)
    assert result["widening_count"] == 2
    assert result["widening_events"][0]["recovered"] is False
    assert result["widening_events"][0]["recovery_duration_ns"] is None


def test_missing_observation_terminates_forward_validity():
    records = [obs(0, "2000.10"), obs(1, None), obs(3, "2000.40"), obs(4, "2000.10")]
    result = summarize(
        records,
        start_ns=BASE,
        end_ns=BASE + 4_000_000_000,
        freshness_ns=5_000_000_000,
        widening_threshold=Decimal("0.20"),
    )
    assert result["valid_duration_ns"] == "2000000000"
    assert result["invalid_snapshots"] == 1
    assert Decimal(result["time_weighted_mean"]) == Decimal("0.25")


def test_backward_asof_does_not_use_future_and_invalid_blocks_fill():
    left = [
        obs(1.5, "2000.30", source="source-left", env="REAL"),
        obs(2.5, "2000.30", source="source-left", env="REAL"),
        obs(4, "2000.30", source="source-left", env="REAL"),
    ]
    right = [
        obs(1, "2000.20", source="source-right", env="DEMO"),
        obs(2, None, source="source-right", env="DEMO"),
        obs(3, "2000.15", source="source-right", env="DEMO"),
    ]
    result = compare(left, right, tolerance_ns=1_000_000_000)
    assert result["evaluations"] == 3 and result["matched"] == 2 and result["unmatched"] == 1
    assert [row["spread_difference"] for row in result["rows"]] == ["0.10", "0.15"]
    assert all(
        int(row["matched_receive_ns"]) <= int(row["evaluation_ns"]) for row in result["rows"]
    )
    assert result["method_version"] == "receive-asof-v1"


def test_comparison_clock_reversal_does_not_reuse_old_quotes():
    left = [obs(t, "2000.30", source="left") for t in (2, 3, 2.5, 4)]
    right = [obs(t, "2000.20", source="right") for t in (1, 3, 3.5, 3.25)]
    result = compare(left, right, tolerance_ns=5_000_000_000)
    assert result["matched"] == 2
    assert result["unmatched"] == 2
    assert [int(row["evaluation_ns"]) for row in result["rows"]] == [
        BASE + 2_000_000_000,
        BASE + 3_000_000_000,
    ]


def test_session_listing_returns_most_recent_with_bounded_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "mt5"
    for name in ("first", "second", "third"):
        directory = root / name
        directory.mkdir(parents=True)
        with SessionRecorder(directory):
            pass
    assert [item["session_id"] for item in list_sessions(limit=2)] == ["third", "second"]


def test_sealed_segments_are_readable_while_active_and_session_finalizes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data" / "mt5" / "synthetic-run"
    directory.mkdir(parents=True)
    with SessionRecorder(directory, segment_rows=2) as writer:
        writer.append(obs(0, "2000.10"))
        with pytest.raises(FileNotFoundError):
            page("synthetic-run", 0, 0, 10)
        writer.append(obs(1, "2000.20"))
        writer.append(obs(2, "2000.30"))
        assert len(page("synthetic-run", 0, 0, 10)) == 2
        assert read_manifest("synthetic-run")["state"] == "INCOMPLETE"
        with pytest.raises(FileNotFoundError):
            page("synthetic-run", 1, 0, 10)
    manifest = read_manifest("synthetic-run")
    assert manifest["state"] == "COMPLETE" and len(manifest["segments"]) == 2
    assert manifest["total_observations"] == 3
    assert page("synthetic-run", 0, 1, 10)[0]["ordinal"] == 2
    assert len(page("synthetic-run", 1, 0, 10)) == 1
    with pytest.raises(ValueError):
        page("../unsafe", 0, 0, 10)


def test_exception_preserves_sealed_data_and_marks_interrupted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data" / "mt5" / "interrupted-run"
    directory.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        with SessionRecorder(directory, segment_rows=2) as writer:
            writer.append(obs(0, "2000.10"))
            writer.append(obs(1, "2000.20"))
            raise RuntimeError("synthetic interruption")
    assert read_manifest("interrupted-run")["state"] == "INTERRUPTED"
    assert len(page("interrupted-run", 0, 0, 10)) == 2


def test_segment_limit_stops_without_destroying_sealed_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data" / "mt5" / "quota-run"
    directory.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="storage limit"):
        with SessionRecorder(directory, segment_rows=2, max_segments=1) as writer:
            writer.append(obs(0, "2000.10"))
            writer.append(obs(1, "2000.20"))
            writer.append(obs(2, "2000.30"))
    assert read_manifest("quota-run")["state"] == "INTERRUPTED"
    assert len(page("quota-run", 0, 0, 10)) == 2


def test_modified_sealed_segment_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data" / "mt5" / "tamper-run"
    directory.mkdir(parents=True)
    with SessionRecorder(directory, segment_rows=2) as writer:
        writer.append(obs(0, "2000.10"))
    with (directory / "observations.duckdb").open("ab") as stream:
        stream.write(b"synthetic corruption")
    with pytest.raises(ValueError, match="integrity"):
        page("tamper-run", 0, 0, 10)


def test_research_api_sealed_history_statistics_compare_and_export(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from xbsis.live_api import create_live_app

    class Dummy:
        clients = 0

        def start(self):
            pass

        def close(self):
            pass

        def snapshot(self):
            return {"mode": "MOCK", "sources": [], "rejected_events": 0}

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "mt5"
    left, right = root / "left-run", root / "right-run"
    left.mkdir(parents=True)
    right.mkdir()
    with SessionRecorder(left, segment_rows=2) as recorder:
        for row in [
            obs(0, "2000.10", source="left", env="REAL"),
            obs(1, "2000.40", source="left", env="REAL"),
            obs(4, "2000.20", source="left", env="REAL"),
            obs(6, "2000.10", source="left", env="REAL"),
        ]:
            recorder.append(row)
    with SessionRecorder(right, segment_rows=2) as recorder:
        for row in [
            obs(0, "2000.20", source="right", env="DEMO"),
            obs(2, "2000.25", source="right", env="DEMO"),
            obs(4, "2000.15", source="right", env="DEMO"),
            obs(6, "2000.20", source="right", env="DEMO"),
        ]:
            recorder.append(row)
    app = create_live_app("mock", [], 30, 8765, hub=Dummy())
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        sessions = client.get("/live/sessions").json()
        assert {s["session_id"] for s in sessions} == {"left-run", "right-run"}
        assert client.get("/live/sessions/left-run").json()["state"] == "COMPLETE"
        rows = client.get("/live/sessions/left-run/observations?segment=0&limit=1").json()
        assert len(rows["rows"]) == 1 and rows["next_after"] == 1
        stats = client.get("/live/sessions/left-run/statistics?threshold=0.20").json()
        assert stats["metrics"]["snapshots"] == 4
        assert stats["metrics"]["widening_count"] == 1
        assert stats["source"]["environment"] == "REAL"
        assert stats["metrics"]["instrument_metadata"][0]["price_unit"] == "USD_PER_TROY_OUNCE"
        compare_response = client.get(
            "/live/compare?left=left-run&right=right-run&tolerance_ms=1000"
        )
        assert compare_response.status_code == 200
        comparison = compare_response.json()
        assert comparison["left_source"]["environment"] == "REAL"
        assert comparison["right_source"]["environment"] == "DEMO"
        assert all(
            int(r["matched_receive_ns"]) <= int(r["evaluation_ns"])
            for r in comparison["result"]["rows"]
        )
        report = client.get("/live/sessions/left-run/report?threshold=0.20&download=true")
        assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
        assert report.json()["epistemic_status"] == "MEASUREMENT"
        assert "2000.10" not in report.text
        assert client.get("/live/sessions/left-run/statistics?threshold=NaN").status_code == 400
        assert client.get("/live/sessions/left-run/observations?segment=99").status_code == 404


def test_legacy_completed_session_is_read_without_modifying_it(tmp_path, monkeypatch):
    import json

    from xbsis.sessions import list_sessions
    from xbsis.storage import ObservationStore

    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data" / "mt5" / "legacy-run"
    directory.mkdir(parents=True)
    database = directory / "observations.duckdb"
    with ObservationStore(database) as writer:
        writer.append(obs(0, "2000.10"))
        with pytest.raises(FileNotFoundError):
            read_manifest("legacy-run")
    (directory / "summary.json").write_text(json.dumps({"mode": "READ_ONLY_POLLING"}))
    before = database.read_bytes()
    manifest = read_manifest("legacy-run")
    assert manifest["state"] == "LEGACY_COMPLETENESS_UNKNOWN"
    assert manifest["code_revision"] == "UNKNOWN"
    assert len(page("legacy-run", 0, 0, 10)) == 1
    assert list_sessions()[0]["session_id"] == "legacy-run"
    assert database.read_bytes() == before
    assert not (directory / "manifest.json").exists()


def test_page_time_window_is_bounded_and_does_not_forward_fill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data" / "mt5" / "window-run"
    directory.mkdir(parents=True)
    with SessionRecorder(directory, segment_rows=10) as writer:
        for second in (0, 1, 2):
            writer.append(obs(second, "2000.10"))
    rows = page("window-run", 0, 0, 10, BASE + 1_000_000_000, BASE + 2_000_000_000)
    assert [r["ordinal"] for r in rows] == [2, 3]
    with pytest.raises(ValueError, match="time window"):
        page("window-run", 0, 0, 10, BASE + 2, BASE + 1)


def test_forced_termination_is_explicit(tmp_path, monkeypatch):
    from xbsis.sessions import mark_forced_termination

    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data" / "mt5" / "forced-run"
    directory.mkdir(parents=True)
    with SessionRecorder(directory) as writer:
        writer.append(obs(0, "2000.10"))
    mark_forced_termination("forced-run")
    manifest = read_manifest("forced-run")
    assert manifest["state"] == "INTERRUPTED"
    assert manifest["termination_reason"] == "FORCED_TERMINATION"
    assert len(page("forced-run", 0, 0, 10)) == 1


def test_live_allows_eight_hours_but_capture_keeps_120_second_limit(monkeypatch):
    from types import SimpleNamespace

    from xbsis.adapters.mt5 import MT5Error
    from xbsis.live_cli import run_live
    from xbsis.mt5_cli import _validate_bounds

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append(kwargs))
    args = SimpleNamespace(
        mode="mock", port=8765, duration=28_800, sources_file=None, confirm_live_readonly=False
    )
    run_live(args)
    assert calls[0]["host"] == "127.0.0.1"
    args.duration = 28_801
    with pytest.raises(ValueError):
        run_live(args)
    with pytest.raises(MT5Error):
        _validate_bounds(121, 250)
