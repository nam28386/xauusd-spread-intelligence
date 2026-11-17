"""Synthetic multi-source checks; no platform SDK or live account is used."""

import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_mt5 import FakeMT5

import xbsis.adapters.mt5 as mt5_module
from xbsis.adapters.mt5 import MT5Adapter, MT5Error, SourceIdentity, make_engine
from xbsis.models import AccountEnvironment, QualityFlag
from xbsis.mt5_cli import add_commands, run
from xbsis.storage import ObservationStore


@pytest.fixture(autouse=True)
def reset_fake_worker_binding(monkeypatch):
    # Each test models a new process; production worker bindings persist until exit.
    monkeypatch.setattr(mt5_module, "_SESSION_BOUND_TERMINAL", None)
    monkeypatch.setattr(mt5_module, "_SESSION_BOUND_IDENTITY", None)


def identity(source="exness.real.01", broker="exness", server="exness-real-a"):
    return SourceIdentity(source_id=source, broker_id=broker, server_id=server)


def options(**updates):
    defaults = dict(
        command="mt5-capture",
        terminal_path=Path("/synthetic/terminal64.exe"),
        source_id="exness.real.01",
        broker_id="exness",
        server_alias="exness-real-a",
        symbol="XAUUSD.mock",
        confirm_usd_per_oz=True,
        confirm_real=True,
        confirm_demo=False,
        account_type="STANDARD",
        run_name="synthetic-run",
        duration=0.11,
        interval_ms=50,
    )
    return argparse.Namespace(**(defaults | updates))


@pytest.mark.parametrize("flag,mode", [("confirm_real", 2), ("confirm_demo", 0)])
def test_real_and_demo_confirmed_capture(monkeypatch, tmp_path, capsys, flag, mode):
    fake = FakeMT5()
    fake.account = SimpleNamespace(trade_mode=mode)
    monkeypatch.setattr(
        "xbsis.mt5_cli.connect_local",
        lambda path, *, identity: MT5Adapter(fake, path, identity=identity),
    )
    monkeypatch.setattr("xbsis.mt5_cli._new_output", lambda _: tmp_path)
    args = options(confirm_real=flag == "confirm_real", confirm_demo=flag == "confirm_demo")
    run(args)
    result = json.loads(capsys.readouterr().out)
    assert result["account_environment"] == ("REAL" if mode == 2 else "DEMO")
    assert result["account_type_user_label"] == "STANDARD"
    with ObservationStore(tmp_path / "observations.duckdb") as store:
        first = store.records()[0]
    raw = first.quote.raw
    assert (raw.source_id, raw.broker_id, raw.server_id) == (
        "exness.real.01",
        "exness",
        "exness-real-a",
    )
    assert raw.account_environment.value == result["account_environment"]
    assert raw.source_time_ms is not None and raw.received_time_ns > 0
    assert raw.flags == 6 and str(first.spread.spread_points) == "25"
    assert fake.stopped == 1


@pytest.mark.parametrize(
    "mode,real,demo", [(0, True, False), (2, False, True), (1, True, False), (1, False, True)]
)
def test_mismatch_or_unknown_refused_before_capture(monkeypatch, tmp_path, mode, real, demo):
    fake = FakeMT5()
    fake.account = SimpleNamespace(trade_mode=mode)
    monkeypatch.setattr(
        "xbsis.mt5_cli.connect_local",
        lambda path, *, identity: MT5Adapter(fake, path, identity=identity),
    )
    monkeypatch.setattr("xbsis.mt5_cli._new_output", lambda _: pytest.fail("no output allowed"))
    with pytest.raises(MT5Error, match="actual environment differs or is UNKNOWN"):
        run(options(confirm_real=real, confirm_demo=demo))
    assert fake.stopped == 1
    assert list(tmp_path.iterdir()) == []


def test_confirmation_flags_and_identity_are_required_and_exclusive():
    parser = argparse.ArgumentParser()
    add_commands(parser.add_subparsers(dest="command", required=True))
    base = [
        "mt5-capture",
        "--terminal-path",
        "/synthetic/terminal64.exe",
        "--symbol",
        "XAUUSD",
        "--source-id",
        "exness.real.01",
        "--broker-id",
        "exness",
        "--server-alias",
        "exness-real-a",
        "--run-name",
        "sample",
    ]
    for flags in ([], ["--confirm-real", "--confirm-demo"]):
        with pytest.raises(SystemExit):
            parser.parse_args(base + flags)
    for flag in ("--source-id", "--broker-id", "--server-alias"):
        index = base.index(flag)
        with pytest.raises(SystemExit):
            parser.parse_args(base[:index] + base[index + 2 :] + ["--confirm-real"])
    assert parser.parse_args(base + ["--confirm-demo"]).confirm_demo


@pytest.mark.parametrize("bad", ["", "contains space", "12345678", "abc/def", "x" * 129])
def test_alias_contract_rejects_bad_values_before_connection(monkeypatch, bad):
    def should_not_connect(*args, **kwargs):
        pytest.fail("Invalid alias must not connect")

    monkeypatch.setattr("xbsis.mt5_cli.connect_local", should_not_connect)
    with pytest.raises(MT5Error, match="Invalid source"):
        run(options(source_id=bad))
    with pytest.raises(ValidationError):
        identity(source=bad)


def test_no_two_sessions_or_thread_sharing_and_no_terminal_switch(monkeypatch):
    monkeypatch.setattr(mt5_module, "_SESSION_BOUND_TERMINAL", None)
    a, b = FakeMT5(), FakeMT5()
    with MT5Adapter(a, Path("/synthetic/terminal64.exe"), identity=identity()) as adapter:
        with pytest.raises(MT5Error, match="one MT5 session"):
            with MT5Adapter(b, Path("/synthetic/terminal64.exe"), identity=identity()):
                pass
        result = []

        def attempt():
            try:
                adapter.quote("XAUUSD.mock")
            except MT5Error as exc:
                result.append(str(exc))

        worker = threading.Thread(target=attempt)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert result == ["MT5 session must be used only by its owning worker thread."]
    with pytest.raises(MT5Error, match="cannot switch"):
        with MT5Adapter(b, Path("/different/terminal64.exe"), identity=identity()):
            pass
    assert b.initialized == []
    with pytest.raises(MT5Error, match="cannot switch source identities"):
        with MT5Adapter(
            b,
            Path("/synthetic/terminal64.exe"),
            identity=identity(source="other.source", broker="other", server="other-server"),
        ):
            pass
    assert b.initialized == []


def test_mode_change_is_rejected_before_a_new_quote():
    fake = FakeMT5()
    with MT5Adapter(fake, Path("/synthetic/terminal64.exe"), identity=identity()) as adapter:
        adapter.quote("XAUUSD.mock")
        fake.account = SimpleNamespace(trade_mode=0)
        with pytest.raises(MT5Error, match="changed"):
            adapter.quote("XAUUSD.mock")


def test_point_sizes_and_metadata_versions_are_source_specific(monkeypatch):
    fake = FakeMT5()
    with MT5Adapter(fake, Path("/synthetic/terminal64.exe"), identity=identity()) as adapter:
        a = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
        original_info = fake.symbol_info

        def other_info(symbol):
            result = original_info(symbol)
            result.point = 0.1
            return result

        monkeypatch.setattr(fake, "symbol_info", other_info)
        b = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
        raw = adapter.quote("XAUUSD.mock")
        import time

        a_result = make_engine(raw.symbol_raw).process(raw, a, processing_time_ns=time.time_ns())
        b_result = make_engine(raw.symbol_raw).process(raw, b, processing_time_ns=time.time_ns())
    assert str(a_result.spread.spread_points) == "25"
    assert str(b_result.spread.spread_points) == "2.5"
    assert a.metadata_version != b.metadata_version
    assert a_result.quote.raw.source_id == "exness.real.01"
    assert QualityFlag.DUPLICATE not in a_result.spread.data_quality_flags
    assert QualityFlag.DUPLICATE not in b_result.spread.data_quality_flags


def test_mode_recheck_does_not_read_account_identifier():
    class SafeAccount:
        trade_mode = 2

        @property
        def login(self):
            pytest.fail("account identifier must never be read")

    fake = FakeMT5()
    fake.account = SafeAccount()
    with MT5Adapter(fake, Path("/synthetic/terminal64.exe"), identity=identity()) as adapter:
        adapter.quote("XAUUSD.mock")


def test_windows_mutex_closes_on_conflict_and_release(monkeypatch):
    import ctypes

    class Call:
        def __init__(self, fn):
            self.fn = fn

        def __call__(self, *args):
            return self.fn(*args)

    closed = []
    names = []
    kernel = SimpleNamespace(
        CreateMutexW=Call(lambda _, initial, name: names.append(name) or 123),
        CloseHandle=Call(lambda handle: closed.append(handle) or True),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    release = mt5_module._terminal_guard(Path("/synthetic/a/terminal64.exe"))
    release()
    assert closed == [123] and names[0].startswith("Local\\XBSIS_MT5_")
    assert "/synthetic" not in names[0]
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 183)
    with pytest.raises(MT5Error, match="already in use"):
        mt5_module._terminal_guard(Path("/synthetic/a/terminal64.exe"))
    assert closed == [123, 123]


WORKER = r"""
import json, sys, time
from pathlib import Path
from types import SimpleNamespace
from xbsis.adapters.mt5 import MT5Adapter, SourceIdentity
from xbsis.mt5_cli import capture

name, other, mode, root = sys.argv[1:]
root=Path(root)
terminal=Path('/synthetic') / name / 'terminal64.exe'
class SDK:
    ACCOUNT_TRADE_MODE_REAL=2
    ACCOUNT_TRADE_MODE_DEMO=0
    def initialize(self, **kwargs): return True
    def shutdown(self): pass
    def terminal_info(self): return SimpleNamespace(connected=True, path=str(terminal.parent))
    def account_info(self): return SimpleNamespace(trade_mode=int(mode))
    def symbol_info(self, symbol):
        return SimpleNamespace(point=0.01 if name=='one' else 0.1, trade_tick_size=0.01,
                               digits=2, trade_contract_size=100.0, currency_profit='USD')
    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=2000.1, ask=2000.35, time_msc=1700000000000, flags=6)
source=SourceIdentity(source_id=name+'.source', broker_id=name+'.broker', server_id=name+'.server')
with MT5Adapter(SDK(), terminal, identity=source) as adapter:
    meta=adapter.metadata('XAUUSD.mock', confirm_usd_per_oz=True)
    (root / (name+'.ready')).touch()
    deadline=time.monotonic()+10
    while not (root / (other+'.ready')).exists():
        if time.monotonic()>deadline: raise RuntimeError('worker rendezvous failed')
        time.sleep(0.01)
    result=capture(adapter, 'XAUUSD.mock', meta, duration=0.12, interval_ms=50, output=root/name)
    print(json.dumps(result))
"""


def test_two_processes_capture_concurrently_into_isolated_stores(tmp_path):
    # Rendezvous occurs inside both active fake SDK contexts, proving overlapping workers.
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
    processes = []
    try:
        for name, other, mode in [("one", "two", "2"), ("two", "one", "0")]:
            cmd = [sys.executable, "-c", WORKER, name, other, mode, str(tmp_path)]
            processes.append(
                subprocess.Popen(  # noqa: S603 -- fixed Python worker and synthetic arguments
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
            )
        results = []
        for child in processes:
            out, err = child.communicate(timeout=20)
            assert child.returncode == 0, err
            results.append(json.loads(out))
        assert [r["account_environment"] for r in results] == ["REAL", "DEMO"]
        all_records = []
        for name in ("one", "two"):
            with ObservationStore(tmp_path / name / "observations.duckdb") as store:
                all_records.append(store.records())
        first, second = (records[0] for records in all_records)
        assert first.quote.raw.source_id == "one.source"
        assert first.quote.raw.broker_id == "one.broker"
        assert first.quote.raw.server_id == "one.server"
        assert second.quote.raw.source_id == "two.source"
        assert second.quote.raw.broker_id == "two.broker"
        assert second.quote.raw.server_id == "two.server"
        assert first.quote.raw.account_environment == AccountEnvironment.REAL
        assert second.quote.raw.account_environment == AccountEnvironment.DEMO
        assert first.quote.raw.source_time_ms == second.quote.raw.source_time_ms == 1700000000000
        assert first.quote.raw.received_time_ns and second.quote.raw.received_time_ns
        assert first.metadata.metadata_version != second.metadata.metadata_version
        assert str(first.spread.spread_points) == "25"
        assert str(second.spread.spread_points) == "2.5"
        assert QualityFlag.STALE in first.spread.data_quality_flags
        assert QualityFlag.STALE in second.spread.data_quality_flags
        assert QualityFlag.DUPLICATE not in first.spread.data_quality_flags
        assert QualityFlag.DUPLICATE not in second.spread.data_quality_flags
    finally:
        for child in processes:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


@pytest.mark.parametrize(
    "command,source,broker,server,confirmation",
    [
        ("mt5-doctor", "exness.real.01", "exness", "exness-real-a", []),
        (
            "mt5-capture",
            "exness.real.01",
            "exness",
            "exness-real-a",
            ["--confirm-real", "--run-name", "exness-001"],
        ),
        ("mt5-doctor", "pepperstone.demo.01", "pepperstone", "pepperstone-demo-a", []),
        (
            "mt5-capture",
            "pepperstone.demo.01",
            "pepperstone",
            "pepperstone-demo-a",
            ["--confirm-demo", "--run-name", "pepperstone-001"],
        ),
    ],
)
def test_documented_argument_syntax(command, source, broker, server, confirmation):
    parser = argparse.ArgumentParser()
    add_commands(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(
        [
            command,
            "--terminal-path",
            "/synthetic/terminal64.exe",
            "--symbol",
            "XAUUSD.mock",
            "--source-id",
            source,
            "--broker-id",
            broker,
            "--server-alias",
            server,
            "--confirm-usd-per-oz",
            *confirmation,
        ]
    )
    assert args.source_id == source and args.broker_id == broker and args.server_alias == server
    assert args.symbol == "XAUUSD.mock" and args.confirm_usd_per_oz


def test_unconfirmed_unit_or_non_usd_profit_cannot_invent_usd_values(monkeypatch):
    fake = FakeMT5()
    with MT5Adapter(fake, Path("/synthetic/terminal64.exe"), identity=identity()) as adapter:
        unconfirmed = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=False)
        info = fake.symbol_info

        def non_usd(symbol):
            value = info(symbol)
            value.currency_profit = "EUR"
            return value

        monkeypatch.setattr(fake, "symbol_info", non_usd)
        mismatch = adapter.metadata("XAUUSD.mock", confirm_usd_per_oz=True)
    for metadata in (unconfirmed, mismatch):
        assert metadata.quote_currency == "UNKNOWN"
        assert metadata.price_unit == "UNKNOWN"


@pytest.mark.parametrize("failure", ["disconnected", "different_terminal"])
def test_recheck_terminal_before_each_snapshot(failure):
    fake = FakeMT5()
    with MT5Adapter(fake, Path("/synthetic/terminal64.exe"), identity=identity()) as adapter:
        adapter.quote("XAUUSD.mock")
        if failure == "disconnected":
            fake.connected = False
        else:
            fake.terminal_info = lambda: SimpleNamespace(connected=True, path="/other")

        def forbidden_quote(_):
            pytest.fail("must not read quotes from a disconnected or changed terminal")

        fake.symbol_info_tick = forbidden_quote
        with pytest.raises(MT5Error):
            adapter.quote("XAUUSD.mock")


def test_terminal_guard_released_after_initialization_failure():
    fake = FakeMT5()
    fake.init_ok = False
    events = []

    def guard(_):
        events.append("acquire")
        return lambda: events.append("release")

    with pytest.raises(MT5Error, match="initialization failed"):
        with MT5Adapter(
            fake, Path("/synthetic/terminal64.exe"), identity=identity(), terminal_guard=guard
        ):
            pass
    assert events == ["acquire", "release"]
    assert fake.stopped == 1
    fake.init_ok = True
    with MT5Adapter(
        fake, Path("/synthetic/terminal64.exe"), identity=identity(), terminal_guard=guard
    ):
        pass
    assert events == ["acquire", "release", "acquire", "release"]


def test_rejected_guard_does_not_touch_sdk():
    fake = FakeMT5()

    def guard(_):
        raise MT5Error("installation already in use")

    with pytest.raises(MT5Error, match="already in use"):
        with MT5Adapter(
            fake, Path("/synthetic/terminal64.exe"), identity=identity(), terminal_guard=guard
        ):
            pass
    assert fake.initialized == []
    assert fake.stopped == 0
