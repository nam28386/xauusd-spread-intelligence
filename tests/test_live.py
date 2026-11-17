"""Live mock, API security, IPC and lifecycle tests; never connect an MT5 terminal."""

import json
import queue
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from xbsis.adapters.mock import MockBrokerAdapter
from xbsis.live_api import create_live_app
from xbsis.live_cli import mock_sources, run_live
from xbsis.live_config import LiveSources, load_local_sources
from xbsis.live_hub import MAX_HISTORY, LiveHub
from xbsis.live_workers import publish
from xbsis.models import RawQuote
from xbsis.pipeline import SpreadEngine
from xbsis.storage import ObservationStore


def sample_config():
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "examples/live_sources.synthetic.json").read_text())


def observation(source, *, bid="2000.10000", ask="2000.35000", received=None):
    mock = MockBrokerAdapter()
    base = next(mock.quotes()).model_dump()
    raw = RawQuote.model_validate(
        base
        | {
            "source_id": source["source_id"],
            "broker_id": source["broker_id"],
            "server_id": source["server_alias"],
            "symbol_raw": source["symbol"],
            "account_environment": source["expected_account_environment"],
            "bid": bid,
            "ask": ask,
            "received_time_ns": received or base["received_time_ns"],
        }
    )
    engine = SpreadEngine(mapping=mock.mapping, mapping_version=mock.mapping_version)
    return engine.process(raw, mock.metadata, processing_time_ns=raw.received_time_ns)


@pytest.fixture
def cwd_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / ".gitignore").write_text("/data/\n")
    return tmp_path


def test_strict_configuration_and_duplicate_guards(cwd_project):
    config = sample_config()
    assert len(LiveSources.model_validate(config).sources) == 2
    source = config["sources"][0]
    for change in [
        {"password": "forbidden"},
        {"expected_account_environment": "UNKNOWN"},
        {"confirm_usd_per_oz": False},
        {"confirm_usd_per_oz": 1},
        {"confirm_usd_per_oz": "true"},
        {"terminal_path": "relative/terminal64.exe"},
        {"terminal_path": r"\\remote\folder\terminal64.exe"},
        {"terminal_path": "//remote/folder/terminal64.exe"},
        {"terminal_path": r"\rooted\terminal64.exe"},
        {"poll_interval_ms": 1},
        {"source_id": "12345678"},
        {"symbol": "invalid symbol"},
    ]:
        with pytest.raises(ValidationError):
            LiveSources.model_validate({"sources": [source | change]})
    with pytest.raises(ValidationError):
        LiveSources.model_validate({"sources": [source, source | {"source_id": "different"}]})
    with pytest.raises(ValidationError):
        LiveSources.model_validate(
            {"sources": [source, config["sources"][1] | {"source_id": source["source_id"].upper()}]}
        )
    directory = cwd_project / "data" / "config"
    directory.mkdir(parents=True)
    path = directory / "live_sources.local.json"
    path.write_text(json.dumps(config))
    assert len(load_local_sources(path).sources) == 2
    with pytest.raises(ValueError, match="ignored"):
        load_local_sources(cwd_project / "not-ignored.json")
    path.write_text('{"password": "never print this"}')
    with pytest.raises(ValueError) as error:
        load_local_sources(path)
    assert "never print" not in str(error.value)


def test_cli_loopback_and_mt5_confirmation(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))
    args = SimpleNamespace(
        mode="mock", port=8765, duration=2, sources_file=None, confirm_live_readonly=False
    )
    run_live(args)
    assert calls[0][1] == {
        "host": "127.0.0.1",
        "port": 8765,
        "workers": 1,
        "reload": False,
        "access_log": False,
    }
    args.mode = "mt5"
    with monkeypatch.context() as patch:
        patch.setattr("xbsis.live_cli.sys.platform", "linux")
        with pytest.raises(ValueError, match="Windows"):
            run_live(args)
    with monkeypatch.context() as patch:
        patch.setattr("xbsis.live_cli.sys.platform", "win32")
        with pytest.raises(ValueError, match="--confirm-live-readonly"):
            run_live(args)
    args.mode = "mock"
    args.sources_file = Path("/not-used")
    with pytest.raises(ValueError, match="Mock mode"):
        run_live(args)
    args.sources_file = None
    args.duration = 301
    with pytest.raises(ValueError, match="duration"):
        run_live(args)


def test_queue_overflow_is_counted_and_next_point_creates_gap():
    hub = LiveHub("mock", mock_sources()[:1], 30)
    try:
        source = mock_sources()[0]
        entry = hub.entries[source["source_id"]]
        entry["state"].value = 2
        first = observation(source)
        hub.accept(source["source_id"], first)
        small = queue.Queue(maxsize=1)
        publish(small, entry["dropped"], {"value": 1})
        publish(small, entry["dropped"], {"value": 2})
        assert entry["dropped"].value == 1
        second = observation(source, bid="2000.2", ask="2000.45")
        hub.accept(source["source_id"], second)
        points = hub.history(source["source_id"], 60)
        assert [point["spread"] for point in points] == ["0.25000", None, "0.25"]
        assert hub.snapshot()["sources"][0]["queue_dropped"] == 1
    finally:
        hub.close()


def test_quality_staleness_missing_and_worker_crash():
    hub = LiveHub("mock", mock_sources(), 30)
    try:
        a, b = mock_sources()
        ea, eb = hub.entries[a["source_id"]], hub.entries[b["source_id"]]
        ea["state"].value = eb["state"].value = 2
        first = observation(a)
        hub.accept(a["source_id"], first)
        hub.accept(b["source_id"], observation(b))
        assert hub.snapshot()["sources"][0]["status"] == "MOCK"
        invalid = observation(a, ask=None)
        hub.accept(a["source_id"], invalid)
        item = hub.snapshot()["sources"][0]
        assert item["status"] == "INVALID" and item["latest"]["quote"]["raw"]["ask"] is None
        assert item["last_valid"]["quote"]["raw"]["ask"] == "2000.35000"
        assert hub.history(a["source_id"], 60)[-1]["spread"] is None
        assert hub.snapshot()["sources"][1]["status"] == "MOCK"
        ea["last_seen"] = time.monotonic() - 6
        assert hub.snapshot()["sources"][0]["status"] == "STALE"
        ea["state"].value = 4
        assert hub.snapshot()["sources"][0]["status"] == "ERROR"
        ea["state"].value = 5
        assert hub.snapshot()["sources"][0]["status"] == "DISCONNECTED"
        ea["state"].value = 3
        assert hub.snapshot()["sources"][0]["status"] == "STOPPED"
        assert len(ea["history"]) <= MAX_HISTORY
    finally:
        hub.close()


def test_mock_http_websocket_reconnect_and_worker_cleanup(cwd_project):
    hub = LiveHub("mock", mock_sources(), 8)
    app = create_live_app("mock", mock_sources(), 8, 8765, hub=hub)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            snap = client.get("/live/latest").json()
            if all(s["sequence"] >= 2 for s in snap["sources"]):
                break
            time.sleep(0.05)
        else:
            pytest.fail("spawned mock workers produced no observations")
        assert snap["mode"] == "MOCK" and len(snap["sources"]) == 2
        assert [s["expected_account_environment"] for s in snap["sources"]] == ["REAL", "DEMO"]
        assert [s["latest"]["quote"]["raw"]["source_id"] for s in snap["sources"]] == [
            "synthetic-1",
            "synthetic-2",
        ]
        assert all(
            isinstance(s["latest"]["quote"]["raw"]["received_time_ns"], str)
            for s in snap["sources"]
        )
        redirect = client.get("/", follow_redirects=False)
        assert redirect.status_code == 307 and redirect.headers["location"] == "/live/"
        assert client.get("/live/").status_code == 200
        assert "script-src 'self'" in client.get("/live/").headers["content-security-policy"]
        health = client.get("/live/health").json()
        assert health["mode"] == "MOCK" and health["scope"] == "api_only"
        assert len(client.get("/live/sources").json()) == 2
        assert (
            client.get(
                "/live/history", params={"source_id": "synthetic-1", "seconds": 301}
            ).status_code
            == 422
        )
        assert client.get("/live/history", params={"source_id": "unknown"}).status_code == 404
        assert client.get("/live/history", params={"source_id": "synthetic-1"}).json()["points"]
        assert client.post("/live/latest").status_code == 405
        assert (
            client.get("/live/latest", headers={"origin": "https://unrelated.example"}).status_code
            == 403
        )
        assert client.get("/live/latest", headers={"host": "unrelated.example"}).status_code == 400
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://127.0.0.1:8765/live/ws", headers={"origin": "https://unrelated.example"}
            ):
                pass
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://127.0.0.1:8765/live/ws"):
                pass
        for _ in range(2):
            with client.websocket_connect(
                "ws://127.0.0.1:8765/live/ws", headers={"origin": "http://127.0.0.1:8765"}
            ) as ws:
                event = ws.receive_json()
                assert event["mode"] == "MOCK" and len(event["sources"]) == 2
                assert "display_coalesced" in event
    assert all(worker.exitcode is not None for worker in hub.workers)
    for source in mock_sources():
        run_name = next(
            s["output_run"] for s in snap["sources"] if s["source_id"] == source["source_id"]
        )
        with ObservationStore(
            cwd_project / "data" / "mt5" / run_name / "observations.duckdb"
        ) as store:
            assert len(store.records()) >= 2
        summary_path = cwd_project / "data" / "mt5" / run_name / "summary.json"
        assert json.loads(summary_path.read_text())["mode"] == "MOCK"


def test_simulated_worker_crash_is_error_not_live():
    hub = LiveHub("mock", mock_sources()[:1], 30)
    try:
        source = mock_sources()[0]
        entry = hub.entries[source["source_id"]]
        entry["state"].value = 2
        hub.accept(source["source_id"], observation(source))
        hub.workers = [SimpleNamespace(exitcode=9)]
        assert hub.snapshot()["sources"][0]["status"] == "ERROR"
        assert hub.history(source["source_id"], 60)[-1]["spread"] is None
    finally:
        hub.workers = []
        hub.close()


def test_fake_mt5_worker_stores_when_queue_full(cwd_project, monkeypatch):
    import multiprocessing
    import threading

    from test_mt5 import FakeMT5

    import xbsis.adapters.mt5 as mt5_module
    from xbsis.adapters.mt5 import MT5Adapter
    from xbsis.live_workers import mt5_worker

    monkeypatch.setattr(mt5_module, "_SESSION_BOUND_TERMINAL", None)
    monkeypatch.setattr(mt5_module, "_SESSION_BOUND_IDENTITY", None)
    fake = FakeMT5()
    monkeypatch.setattr(
        mt5_module,
        "connect_local",
        lambda path, *, identity: MT5Adapter(fake, path, identity=identity),
    )
    source = sample_config()["sources"][0] | {
        "terminal_path": "/synthetic/terminal64.exe",
        "symbol": "XAUUSD.mock",
        "poll_interval_ms": 50,
    }
    q = queue.Queue(maxsize=1)
    ctx = multiprocessing.get_context("spawn")
    dropped = ctx.Value("L", 0)
    state = ctx.Value("i", 0)
    mt5_worker(0, source, q, dropped, state, threading.Event(), 0.2, "testfake")
    assert state.value == 3 and dropped.value >= 1
    message = q.get_nowait()
    assert message["source_id"] == "synthetic-source-one"
    with ObservationStore(cwd_project / "data/mt5/live-testfake-0/observations.duckdb") as store:
        records = store.records()
    assert len(records) >= 2
    summary = json.loads((cwd_project / "data/mt5/live-testfake-0/summary.json").read_text())
    assert summary["queue_dropped_display"] == dropped.value
    assert records[0].quote.raw.source_id == "synthetic-source-one"
    assert records[0].quote.raw.broker_id == "synthetic-broker-one"
    assert records[0].quote.raw.account_environment.value == "REAL"
    assert fake.stopped == 1


def test_incorrect_mode_never_starts_recording(cwd_project, monkeypatch):
    import multiprocessing
    import threading

    from test_mt5 import FakeMT5

    import xbsis.adapters.mt5 as mt5_module
    from xbsis.adapters.mt5 import MT5Adapter
    from xbsis.live_workers import mt5_worker

    monkeypatch.setattr(mt5_module, "_SESSION_BOUND_TERMINAL", None)
    monkeypatch.setattr(mt5_module, "_SESSION_BOUND_IDENTITY", None)
    fake = FakeMT5()
    fake.account = SimpleNamespace(trade_mode=0)
    monkeypatch.setattr(
        mt5_module,
        "connect_local",
        lambda path, *, identity: MT5Adapter(fake, path, identity=identity),
    )
    source = sample_config()["sources"][0] | {"terminal_path": "/synthetic/terminal64.exe"}
    ctx = multiprocessing.get_context("spawn")
    state = ctx.Value("i", 0)
    mt5_worker(0, source, queue.Queue(), ctx.Value("L", 0), state, threading.Event(), 0.1, "bad")
    assert state.value == 4 and fake.stopped == 1
    assert not (cwd_project / "data").exists()


def test_request_rate_limit_is_bounded():
    class Dummy:
        clients = 0

        def start(self):
            pass

        def close(self):
            pass

        def snapshot(self):
            return {"mode": "MOCK", "sources": [], "rejected_events": 0}

    app = create_live_app("mock", [], 10, 8765, hub=Dummy())
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert all(client.get("/live/health").status_code == 200 for _ in range(120))
        assert client.get("/live/health").status_code == 429


def test_no_public_bind_option():
    import argparse

    from xbsis.live_cli import add_live_command

    parser = argparse.ArgumentParser()
    add_live_command(parser.add_subparsers(dest="command", required=True))
    with pytest.raises(SystemExit):
        parser.parse_args(["live-serve", "--host", "0.0.0.0"])  # noqa: S104 -- rejected input


def test_missing_then_same_quote_does_not_invent_change():
    source = mock_sources()[0]
    hub = LiveHub("mock", [source], 30)
    try:
        entry = hub.entries[source["source_id"]]
        entry["state"].value = 2
        hub.accept(source["source_id"], observation(source))
        hub.accept(source["source_id"], observation(source, ask=None))
        hub.accept(source["source_id"], observation(source))
        assert hub.snapshot()["sources"][0]["observed_changes"] == 0
        assert [p["spread"] for p in hub.history(source["source_id"], 60)] == [
            "0.25000",
            None,
            "0.25000",
        ]
    finally:
        hub.close()


def test_single_mock_source_starts_and_stops(cwd_project):
    sources = mock_sources()[:1]
    hub = LiveHub("mock", sources, 5)
    with TestClient(
        create_live_app("mock", sources, 5, 8765, hub=hub), base_url="http://127.0.0.1:8765"
    ) as client:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = client.get("/live/latest").json()
            if data["sources"][0]["sequence"]:
                break
            time.sleep(0.05)
        else:
            pytest.fail("single mock worker did not emit")
        assert len(data["sources"]) == 1
        assert data["sources"][0]["status"] == "MOCK"
    assert len(hub.workers) == 1 and hub.workers[0].exitcode is not None


def test_real_mode_rejects_mock_observation_before_live_status():
    source = mock_sources()[0]
    hub = LiveHub("mt5", [source], 30)
    try:
        entry = hub.entries[source["source_id"]]
        entry["state"].value = 2
        assert hub.snapshot()["sources"][0]["status"] == "CONNECTING"
        replacement = queue.Queue()
        hub.queue.close()
        hub.queue = replacement
        replacement.put(
            {
                "kind": "observation",
                "source_id": source["source_id"],
                "observation": observation(source).model_dump(mode="json"),
            }
        )
        hub.drain()
        assert hub.rejected_events == 1
        assert hub.snapshot()["sources"][0]["status"] == "CONNECTING"
    finally:
        # queue.Queue is used here solely to make the rejected message deterministic.
        hub.stop_event.set()


def test_history_has_fixed_bound():
    source = mock_sources()[0]
    hub = LiveHub("mock", [source], 30)
    try:
        obs = observation(source)
        for _ in range(MAX_HISTORY + 31):
            hub.accept(source["source_id"], obs)
        assert len(hub.history(source["source_id"], 60)) == MAX_HISTORY
    finally:
        hub.close()


def test_mock_prefix_is_deterministic_across_spawned_runs(cwd_project):
    sequences = []
    source = mock_sources()[0]
    for _ in range(2):
        hub = LiveHub("mock", [source], 5)
        with TestClient(
            create_live_app("mock", [source], 5, 8765, hub=hub), base_url="http://127.0.0.1:8765"
        ) as client:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                data = client.get("/live/latest").json()
                if data["sources"][0]["sequence"] >= 4:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("mock worker did not produce deterministic prefix")
            run_name = data["sources"][0]["output_run"]
        with ObservationStore(
            cwd_project / "data" / "mt5" / run_name / "observations.duckdb"
        ) as store:
            sequences.append([record.model_dump_json() for record in store.records()[:4]])
    assert sequences[0] == sequences[1]


def test_local_clock_reversal_never_marks_real_mode_live(monkeypatch):
    source = mock_sources()[0]
    hub = LiveHub("mt5", [source], 30)
    try:
        entry = hub.entries[source["source_id"]]
        entry["state"].value = 2
        obs = observation(source)
        hub.accept(source["source_id"], obs)
        monkeypatch.setattr(
            "xbsis.live_hub.time.time_ns", lambda: obs.quote.raw.received_time_ns - 1
        )
        assert hub.snapshot()["sources"][0]["status"] == "INVALID"
    finally:
        hub.close()


def test_default_http_port_accepts_canonical_local_origin():
    class Dummy:
        clients = 0

        def start(self):
            pass

        def close(self):
            pass

        def snapshot(self):
            return {"mode": "MOCK", "sources": [], "rejected_events": 0}

    app = create_live_app("mock", [], 10, 80, hub=Dummy())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/live/health", headers={"origin": "http://127.0.0.1"}).status_code == 200
        with client.websocket_connect(
            "ws://127.0.0.1/live/ws", headers={"origin": "http://127.0.0.1"}
        ) as ws:
            assert ws.receive_json()["mode"] == "MOCK"
