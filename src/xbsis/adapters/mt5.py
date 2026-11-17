"""Explicit Windows-only MT5 observation; no account switching or trading APIs."""

import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from xbsis.adapters.windows_contract import TickSnapshot, WindowsSourceConfig, map_snapshot
from xbsis.models import AccountEnvironment, InstrumentMetadata, Observation, QualityFlag
from xbsis.pipeline import SpreadEngine


class MT5Error(RuntimeError):
    """Safe, prewritten error; never include SDK messages, account fields or paths."""


def _check_running_terminal(path: Path) -> Path:
    """Check exact executable with Windows CIM; never print process paths."""
    if not path.is_absolute() or path.name.lower() != "terminal64.exe":
        raise MT5Error("Provide an absolute path to terminal64.exe.")
    try:
        expected = path.resolve(strict=True)
    except OSError:
        raise MT5Error("Terminal executable is unavailable.") from None
    if not expected.is_file():
        raise MT5Error("Terminal executable is unavailable.")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        r"System32\WindowsPowerShell\v1.0\powershell.exe"
    )
    query = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        "Get-CimInstance Win32_Process -Filter \"Name = 'terminal64.exe'\" | "
        "ForEach-Object { if ($_.ExecutablePath) { $_.ExecutablePath } }"
    )
    try:
        result = subprocess.run(  # noqa: S603 -- fixed system executable and fixed script
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=True,
        )
        matches = any(
            os.path.normcase(os.path.realpath(line.strip())) == os.path.normcase(str(expected))
            for line in result.stdout.splitlines()
            if line.strip()
        )
    except (OSError, subprocess.SubprocessError):
        raise MT5Error("Cannot verify the running terminal process.") from None
    if not matches:
        raise MT5Error("The specified terminal process is not running or cannot be verified.")
    return expected


def connect_local(path: Path) -> "MT5Adapter":
    """Only CLI entry: reject non-Windows before importing optional SDK."""
    if sys.platform != "win32" or platform.machine().upper() != "AMD64":
        raise MT5Error("MT5 connectivity requires 64-bit Windows and Python 3.12.")
    if sys.version_info[:2] != (3, 12):
        raise MT5Error("MT5 connectivity requires Python 3.12.")
    terminal = _check_running_terminal(path)
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise MT5Error("Install the Windows mt5 optional dependency.") from None
    return MT5Adapter(mt5, terminal)


def _optional_positive(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return str(value)


class MT5Adapter:
    """Injected SDK object enables tests with fakes; CLI uses connect_local only."""

    def __init__(self, sdk: object, terminal: Path):
        self.sdk = sdk
        self.terminal = terminal
        self.environment = AccountEnvironment.UNKNOWN
        self._initialized = False

    def __enter__(self) -> "MT5Adapter":
        try:
            # No login, password, server, account, or portable switch is supplied.
            self._initialized = bool(self.sdk.initialize(path=str(self.terminal), timeout=5000))
            if not self._initialized:
                raise MT5Error("MT5 initialization failed; verify the already-running terminal.")
            terminal = self.sdk.terminal_info()
            if terminal is None or not terminal.connected:
                raise MT5Error("Terminal is disconnected.")
            # Prevent silently accepting another installation. No terminal data is retained.
            if not getattr(terminal, "path", None) or os.path.normcase(
                os.path.realpath(terminal.path)
            ) != os.path.normcase(os.path.realpath(self.terminal.parent)):
                raise MT5Error("Connected terminal path does not match the selected installation.")
            account = self.sdk.account_info()
            if account is None:
                raise MT5Error("No authenticated account is available in the terminal.")
            trade_mode = account.trade_mode
            del account
            if trade_mode == self.sdk.ACCOUNT_TRADE_MODE_REAL:
                self.environment = AccountEnvironment.REAL
            elif trade_mode == self.sdk.ACCOUNT_TRADE_MODE_DEMO:
                self.environment = AccountEnvironment.DEMO
            else:
                self.environment = AccountEnvironment.UNKNOWN
            return self
        except Exception as exc:
            try:
                self.sdk.shutdown()
            except Exception:  # noqa: S110 -- SDK exception details may contain private data
                pass
            self._initialized = False
            if isinstance(exc, MT5Error):
                raise
            raise MT5Error("MT5 initialization or terminal check failed.") from None

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._initialized:
            self._initialized = False
            try:
                self.sdk.shutdown()
            except Exception:
                if exc_type is None:
                    raise MT5Error("MT5 shutdown failed.") from None

    def candidates(self) -> tuple[str, ...]:
        symbols = self.sdk.symbols_get()
        if symbols is None:
            raise MT5Error("Symbol discovery failed.")
        return tuple(
            sorted(
                {
                    item.name
                    for item in symbols
                    if isinstance(item.name, str)
                    and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item.name)
                    and item.name.upper().startswith(("XAUUSD", "GOLD"))
                }
            )
        )

    def select_symbol(self, requested: str | None) -> str:
        candidates = self.candidates()
        if not candidates:
            raise MT5Error("No XAUUSD or GOLD symbol candidates found.")
        if requested is None:
            if len(candidates) != 1:
                # Names are printed only locally, never written to a sanitized report.
                raise MT5Error("Ambiguous symbol; select --symbol from: " + ", ".join(candidates))
            return candidates[0]
        if requested not in candidates:
            raise MT5Error("Selected symbol is not a discovered XAUUSD or GOLD candidate.")
        return requested

    def metadata(self, symbol: str, *, confirm_usd_per_oz: bool) -> InstrumentMetadata:
        info = self.sdk.symbol_info(symbol)
        if info is None:
            raise MT5Error("Selected symbol metadata is unavailable.")
        digits = getattr(info, "digits", None)
        if type(digits) is not int or not 0 <= digits <= 18:
            digits = None
        currency = "USD" if getattr(info, "currency_profit", None) == "USD" else "UNKNOWN"
        return InstrumentMetadata(
            point_size=_optional_positive(getattr(info, "point", None)),
            tick_size=_optional_positive(getattr(info, "trade_tick_size", None)),
            digits=digits,
            contract_size=_optional_positive(getattr(info, "trade_contract_size", None)),
            quote_currency=currency,
            price_unit="USD_PER_TROY_OUNCE"
            if confirm_usd_per_oz and currency == "USD"
            else "UNKNOWN",
            metadata_source="local-mt5-symbol-info",
            metadata_version="mt5-symbol-info-v1",
        )

    def quote(self, symbol: str):
        tick = self.sdk.symbol_info_tick(symbol)
        received_time_ns = time.time_ns()  # immediately after the local SDK read
        snapshot = None
        if tick is not None:
            source_ms = tick.time_msc if type(tick.time_msc) is int and tick.time_msc > 0 else None
            if type(tick.flags) is not int or tick.flags < 0:
                raise MT5Error("Tick flags are missing or invalid.")
            flags = tick.flags
            snapshot = TickSnapshot(
                bid=str(tick.bid) if tick.bid is not None else None,
                ask=str(tick.ask) if tick.ask is not None else None,
                source_time_ms=source_ms,
                flags=flags,
            )
        config = WindowsSourceConfig(
            source_id="local-mt5",
            broker_id="local-broker",
            server_id="local-server",
            account_environment=self.environment,
            symbol_raw=symbol,
        )
        return map_snapshot(config, snapshot, received_time_ns=received_time_ns)


def make_engine(symbol: str) -> SpreadEngine:
    return SpreadEngine(mapping={symbol: "XAUUSD"}, mapping_version="local-symbol-confirmed-v1")


def quote_status(observation: Observation) -> str:
    flags = set(observation.spread.data_quality_flags)
    if QualityFlag.STALE in flags:
        return "STALE"
    if QualityFlag.FUTURE_SOURCE_TIME in flags:
        return "CLOCK_SKEW"
    if flags.intersection(
        {
            QualityFlag.MISSING_SOURCE_TIME,
            QualityFlag.MISSING_BID,
            QualityFlag.MISSING_ASK,
            QualityFlag.INVALID_BID,
            QualityFlag.INVALID_ASK,
            QualityFlag.CROSSED,
            QualityFlag.UNSUPPORTED_SYMBOL,
            QualityFlag.SOURCE_OUT_OF_ORDER,
            QualityFlag.RECEIVE_TIME_REVERSED,
        }
    ):
        return "INVALID_OR_MISSING"
    return "VALID"
