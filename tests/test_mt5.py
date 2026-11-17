import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from xbsis.adapters.mt5 import (
    MT5Adapter,
    MT5Error,
    SourceIdentity,
    connect_local,
    make_engine,
    quote_status,
)
from xbsis.models import AccountEnvironment, QualityFlag
from xbsis.mt5_cli import _new_output, capture, run
from xbsis.storage import ObservationStore


class FakeAccount:
    trade_mode = 2

    def __repr__(self):
        raise AssertionError("private account object was formatted")

    @property
    def login(self):
        raise AssertionError("private account identifier was read")


class FakeMT5:
    ACCOUNT_TRADE_MODE_REAL = 2
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self):
        self.stopped = 0
        self.initialized = []
        self.connected = True
        self.init_ok = True
        self.account = FakeAccount()
        self.names = ["XAUUSD.mock"]
        self.tick = SimpleNamespace(
            bid=2000.1, ask=2000.35, time_msc=time.time_ns() // 1_000_000, flags=6
        )

    def initialize(self, **kwargs):
        self.initialized.append(kwargs)
        return self.init_ok

    def shutdown(self):
        self.stopped += 1

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected, path="/synthetic")

    def account_info(self):
        return self.account

    def symbols_get(self):
        return [SimpleNamespace(name=name) for name in self.names]

    def symbol_info(self, symbol):
        if symbol not in self.names:
            return None
        return SimpleNamespace(
            point=0.01,
            trade_tick_size=0.01,
            digits=2,
            trade_contract_size=100.0,
            currency_profit="USD",
        )

    def symbol_info_tick(self, symbol):
        assert symbol in self.names
        return self.tick


def open_fake(fake):
    return MT5Adapter(
        fake,
        Path("/synthetic/terminal64.exe"),
        identity=SourceIdentity(
            source_id="synthetic-source", broker_id="synthetic-broker", server_id="synthetic-server"
        ),
    )


def test_fake_initialization_metadata_quote_and_shutdown():
    fake = FakeMT5()
    with open_fake(fake) as adapter:
        assert adapter.environment == AccountEnvironment.REAL
        assert adapter.select_symbol(None) == "XAUUSD.mock"
        metadata = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
        raw = adapter.quote("XAUUSD.mock")
        obs = make_engine(raw.symbol_raw).process(raw, metadata, processing_time_ns=time.time_ns())
        assert str(obs.spread.spread_usd_per_oz) == "0.25"
        assert raw.bid == "2000.1" and raw.ask == "2000.35"
        assert raw.source_time_ms == fake.tick.time_msc
        assert raw.received_time_ns >= raw.source_time_ms * 1_000_000
        assert raw.flags == 6
        assert quote_status(obs) == "VALID"
        assert fake.initialized == [
            {"path": str(Path("/synthetic/terminal64.exe")), "timeout": 5000}
        ]
    assert fake.stopped == 1


@pytest.mark.parametrize("failure", ["initialize", "disconnected", "wrong_path", "no_account"])
def test_failures_shutdown_and_do_not_expose_sdk_details(failure):
    fake = FakeMT5()
    if failure == "initialize":
        fake.init_ok = False
    elif failure == "disconnected":
        fake.connected = False
    elif failure == "wrong_path":
        fake.terminal_info = lambda: SimpleNamespace(connected=True, path="/wrong")
    else:
        fake.account = None
    with pytest.raises(MT5Error):
        with open_fake(fake):
            pytest.fail("failed terminal should not enter")
    assert fake.stopped == 1


def test_exception_still_shuts_down():
    fake = FakeMT5()
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with open_fake(fake):
            raise RuntimeError("synthetic failure")
    assert fake.stopped == 1


def test_account_environment_uses_only_trade_mode():
    fake = FakeMT5()
    fake.account = SimpleNamespace(trade_mode=0)
    with open_fake(fake) as adapter:
        assert adapter.environment == AccountEnvironment.DEMO
    fake.account = SimpleNamespace(trade_mode=1)
    with open_fake(fake) as adapter:
        assert adapter.environment == AccountEnvironment.UNKNOWN


def test_symbol_discovery_ambiguity_and_wrong_symbol():
    fake = FakeMT5()
    fake.names = ["EURUSD", "XAUUSD.a", "GOLD.b"]
    with open_fake(fake) as adapter:
        assert adapter.candidates() == ("GOLD.b", "XAUUSD.a")
        with pytest.raises(MT5Error, match="Ambiguous"):
            adapter.select_symbol(None)
        with pytest.raises(MT5Error, match="not a discovered"):
            adapter.select_symbol("EURUSD")
        assert adapter.select_symbol("XAUUSD.a") == "XAUUSD.a"


def test_unknown_unit_does_not_invent_usd_spread():
    fake = FakeMT5()
    with open_fake(fake) as adapter:
        meta = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=False)
        raw = adapter.quote("XAUUSD.mock")
        obs = make_engine(raw.symbol_raw).process(raw, meta, processing_time_ns=time.time_ns())
        assert obs.spread.spread_usd_per_oz is None
        assert meta.quote_currency == "UNKNOWN"
        assert str(obs.spread.spread_points) == "25"
        assert QualityFlag.UNKNOWN_PRICE_UNIT in obs.spread.data_quality_flags


@pytest.mark.parametrize(
    "bid,ask,age,status",
    [
        (0.0, 2000.3, 0, "INVALID_OR_MISSING"),
        (2000.4, 2000.3, 0, "INVALID_OR_MISSING"),
        (2000.1, 2000.3, 10_000, "STALE"),
        (2000.1, 2000.3, -10_000, "CLOCK_SKEW"),
    ],
)
def test_zero_crossed_stale_and_future(bid, ask, age, status):
    fake = FakeMT5()
    fake.tick = SimpleNamespace(
        bid=bid, ask=ask, time_msc=time.time_ns() // 1_000_000 - age, flags=0
    )
    with open_fake(fake) as adapter:
        meta = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
        raw = adapter.quote("XAUUSD.mock")
        obs = make_engine(raw.symbol_raw).process(raw, meta, processing_time_ns=time.time_ns())
        assert quote_status(obs) == status


def test_missing_tick_is_not_forward_filled():
    fake = FakeMT5()
    fake.tick = None
    with open_fake(fake) as adapter:
        raw = adapter.quote("XAUUSD.mock")
        assert raw.bid is None and raw.ask is None and raw.source_time_ms is None
        obs = make_engine(raw.symbol_raw).process(raw, None, processing_time_ns=time.time_ns())
        assert quote_status(obs) == "INVALID_OR_MISSING"


def test_repeated_quote_snapshot_is_not_a_new_event():
    fake = FakeMT5()
    with open_fake(fake) as adapter:
        meta = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
        engine = make_engine("XAUUSD.mock")
        first = adapter.quote("XAUUSD.mock")
        engine.process(first, meta, processing_time_ns=time.time_ns())
        again = adapter.quote("XAUUSD.mock")
        obs = engine.process(again, meta, processing_time_ns=time.time_ns())
        assert QualityFlag.DUPLICATE in obs.spread.data_quality_flags


def test_local_connect_rejects_linux_before_sdk_import():
    if sys.platform == "win32":
        pytest.skip("Linux isolation check")
    with pytest.raises(MT5Error, match="Windows"):
        connect_local(Path("/not-used"))
    assert "MetaTrader5" not in sys.modules


def test_capture_preserves_duplicates_and_outputs_only_sanitized_summary(tmp_path):
    fake = FakeMT5()
    with open_fake(fake) as adapter:
        metadata = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
        summary = capture(
            adapter, "XAUUSD.mock", metadata, duration=0.11, interval_ms=50, output=tmp_path
        )
    assert summary["status"] == "NO_NEW_QUOTES"
    assert summary["snapshots"] >= 2
    assert summary["duplicate_snapshots"] == summary["snapshots"] - 1
    assert summary["observed_changes"] == 0
    text = (tmp_path / "summary.json").read_text()
    assert "2000" not in text and "XAUUSD" not in text and "/synthetic" not in text
    assert json.loads(text) == summary
    with ObservationStore(tmp_path / "observations.duckdb") as store:
        records = store.records()
    assert len(records) == summary["snapshots"]
    assert records[1].quote.raw.source_time_ms == records[0].quote.raw.source_time_ms
    assert QualityFlag.DUPLICATE in records[1].spread.data_quality_flags


def test_output_directory_is_ignored_and_unique(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / ".gitignore").write_text("/data/\n")
    assert _new_output("run-1") == tmp_path / "data" / "mt5" / "run-1"
    with pytest.raises(MT5Error, match="already exists"):
        _new_output("run-1")
    with pytest.raises(MT5Error, match="Run name"):
        _new_output("../escape")


def test_demo_capture_refused_before_creating_output(tmp_path, monkeypatch):
    fake = FakeMT5()
    fake.account = SimpleNamespace(trade_mode=0)
    monkeypatch.setattr("xbsis.mt5_cli.connect_local", lambda _, **kwargs: open_fake(fake))
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(
        command="mt5-capture",
        terminal_path=Path("/synthetic/terminal64.exe"),
        symbol="XAUUSD.mock",
        confirm_usd_per_oz=True,
        confirm_real=True,
        confirm_demo=False,
        source_id="synthetic-source",
        broker_id="synthetic-broker",
        server_alias="synthetic-server",
        account_type="UNKNOWN",
        run_name="run",
        duration=1.0,
        interval_ms=250,
    )
    with pytest.raises(MT5Error, match="verified REAL"):
        run(args)
    assert fake.stopped == 1
    assert list(tmp_path.iterdir()) == []


def test_sdk_error_text_is_suppressed():
    fake = FakeMT5()

    def broken(**kwargs):
        raise RuntimeError("sensitive SDK details")

    fake.initialize = broken
    with pytest.raises(MT5Error, match="initialization or terminal check") as exc:
        with open_fake(fake):
            pass
    assert "sensitive" not in str(exc.value)
    assert fake.stopped == 1


def test_symbol_flags_are_not_invented_when_sdk_value_is_invalid():
    fake = FakeMT5()
    fake.tick.flags = None
    with open_fake(fake) as adapter:
        with pytest.raises(MT5Error, match="flags"):
            adapter.quote("XAUUSD.mock")
    assert fake.stopped == 1


class SimulatedClock:
    def __init__(self):
        self.elapsed = 0.0
        self.epoch_ns = 1_700_000_000_000_000_000

    def monotonic(self):
        return self.elapsed

    def time_ns(self):
        return self.epoch_ns + int(self.elapsed * 1_000_000_000)

    def sleep(self, delay):
        self.elapsed += delay


class SimulatedPollingAdapter:
    environment = AccountEnvironment.REAL

    def __init__(self, clock, stale=False):
        self.clock = clock
        self.stale = stale

    def quote(self, symbol):
        from xbsis.adapters.windows_contract import TickSnapshot, WindowsSourceConfig, map_snapshot

        now_ns = self.clock.time_ns()
        # A single distinct change after the initial snapshot; no claim of tick completeness.
        source_ms = (self.clock.epoch_ns // 1_000_000) + (250 if self.clock.elapsed >= 0.25 else 0)
        if self.stale:
            source_ms -= 10_000
        snapshot = TickSnapshot(bid="2000.1", ask="2000.35", source_time_ms=source_ms, flags=6)
        config = WindowsSourceConfig(
            source_id="local-mt5",
            broker_id="local-broker",
            server_id="local-server",
            account_environment=AccountEnvironment.REAL,
            symbol_raw=symbol,
        )
        return map_snapshot(config, snapshot, received_time_ns=now_ns)


def test_capture_counts_only_observed_fresh_changes(tmp_path):
    fake = FakeMT5()
    with open_fake(fake) as adapter:
        metadata = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
    clock = SimulatedClock()
    summary = capture(
        SimulatedPollingAdapter(clock),
        "XAUUSD.mock",
        metadata,
        duration=1.0,
        interval_ms=250,
        output=tmp_path,
        clock=clock,
    )
    assert summary["status"] == "OK"
    assert summary["snapshots"] == 4
    assert summary["observed_changes"] == 1
    assert summary["duplicate_snapshots"] == 2
    with ObservationStore(tmp_path / "observations.duckdb") as store:
        records = store.records()
    assert records[1].quote.raw.source_time_ms == 1_700_000_000_250
    assert records[1].quote.raw.received_time_ns == 1_700_000_000_250_000_000
    assert records[1].processing_time_ns == records[1].quote.raw.received_time_ns


def test_capture_closed_market_is_stale(tmp_path):
    fake = FakeMT5()
    with open_fake(fake) as adapter:
        metadata = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
    clock = SimulatedClock()
    summary = capture(
        SimulatedPollingAdapter(clock, stale=True),
        "XAUUSD.mock",
        metadata,
        duration=0.5,
        interval_ms=250,
        output=tmp_path,
        clock=clock,
    )
    assert summary["status"] == "STALE"
    assert summary["fresh_snapshots"] == 0
    assert summary["stale_snapshots"] == 2


@pytest.mark.parametrize("duration,interval", [(121, 250), (0, 250), (float("nan"), 250), (1, 49)])
def test_invalid_capture_bounds_do_not_connect(duration, interval, monkeypatch):
    def unexpected(_):
        raise AssertionError("invalid configuration must not connect")

    monkeypatch.setattr("xbsis.mt5_cli.connect_local", unexpected)
    args = argparse.Namespace(
        command="mt5-capture",
        terminal_path=Path("/unused"),
        duration=duration,
        interval_ms=interval,
    )
    with pytest.raises(MT5Error):
        run(args)


def test_sdk_unknown_exception_is_suppressed_by_cli(monkeypatch, capsys):
    from xbsis.__main__ import main

    def broken(_, **kwargs):
        raise RuntimeError("sensitive information from SDK")

    monkeypatch.setattr("xbsis.mt5_cli.connect_local", broken)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xbsis",
            "mt5-doctor",
            "--terminal-path",
            "/unused",
            "--source-id",
            "synthetic-source",
            "--broker-id",
            "synthetic-broker",
            "--server-alias",
            "synthetic-server",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "sensitive" not in capsys.readouterr().err


def test_running_terminal_preflight_rejects_unmatched_process(tmp_path, monkeypatch):
    from xbsis.adapters.mt5 import _check_running_terminal

    terminal = tmp_path / "terminal64.exe"
    terminal.touch()
    monkeypatch.setattr(
        "xbsis.adapters.mt5.subprocess.run",
        lambda *a, **kw: SimpleNamespace(stdout="/different/terminal64.exe\n"),
    )
    with pytest.raises(MT5Error, match="not running"):
        _check_running_terminal(terminal)
    monkeypatch.setattr(
        "xbsis.adapters.mt5.subprocess.run",
        lambda *a, **kw: SimpleNamespace(stdout=str(terminal) + "\n"),
    )
    assert _check_running_terminal(terminal) == terminal


def test_capture_rejects_data_symlink_to_unignored_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / ".gitignore").write_text("/data/\n")
    target = tmp_path / "unignored"
    target.mkdir()
    try:
        (tmp_path / "data").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Windows does not permit creating directory symlinks")
    with pytest.raises(MT5Error, match="ignored data directory"):
        _new_output("run-1")
    assert list(target.iterdir()) == []


def test_doctor_reports_status_without_account_values_or_prices(monkeypatch, capsys):
    fake = FakeMT5()
    monkeypatch.setattr("xbsis.mt5_cli.connect_local", lambda _, **kwargs: open_fake(fake))
    args = argparse.Namespace(
        command="mt5-doctor",
        source_id="synthetic-source",
        broker_id="synthetic-broker",
        server_alias="synthetic-server",
        terminal_path=Path("/synthetic/terminal64.exe"),
        symbol="XAUUSD.mock",
        confirm_usd_per_oz=True,
    )
    run(args)
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "READ_ONLY"
    assert result["account_environment"] == "REAL"
    assert result["symbol"] == "XAUUSD.mock"
    assert result["quote_status"] == "VALID"
    assert result["quality_flags"] == []
    assert result["usd_per_oz_confirmed"] is True
    assert result["broker_identity_verified"] is False
    assert result["instrument"]["point_size"] == "0.01"
    assert result["instrument"]["tick_size"] == "0.01"
    assert result["instrument"]["contract_size"] == "100.0"
    assert fake.stopped == 1


def test_capture_enforces_duration_bound_even_without_cli(tmp_path):
    with pytest.raises(MT5Error, match="Duration"):
        capture(None, "XAUUSD.mock", None, duration=121, interval_ms=250, output=tmp_path)
    assert list(tmp_path.iterdir()) == []
