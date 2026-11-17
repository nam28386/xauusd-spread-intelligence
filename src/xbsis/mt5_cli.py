"""Explicit local doctor and bounded capture; summaries never contain quotes or identities."""

import json
import math
import re
import time
from pathlib import Path

from xbsis.adapters.mt5 import MT5Error, connect_local, make_engine, quote_status
from xbsis.models import AccountEnvironment, QualityFlag
from xbsis.storage import ObservationStore


def add_commands(commands) -> None:
    for command in ("mt5-doctor", "mt5-capture"):
        parser = commands.add_parser(command, help="explicit local Windows MT5 read-only operation")
        parser.add_argument("--terminal-path", required=True, type=Path)
        parser.add_argument("--symbol", required=command == "mt5-capture")
        parser.add_argument("--confirm-usd-per-oz", action="store_true")
        if command == "mt5-capture":
            parser.add_argument("--confirm-real", action="store_true", required=True)
            parser.add_argument("--run-name", required=True)
            parser.add_argument("--duration", type=float, default=120.0)
            parser.add_argument("--interval-ms", type=int, default=250)


def _new_output(run_name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_name):
        raise MT5Error("Run name must contain only letters, digits, underscores or hyphens.")
    cwd = Path.cwd().resolve()
    try:
        ignore_file = (cwd / ".gitignore").read_text(encoding="utf-8").splitlines()
    except OSError:
        raise MT5Error("Run capture from the project root with its existing .gitignore.") from None
    if not (cwd / "pyproject.toml").is_file() or "/data/" not in ignore_file:
        raise MT5Error("Run capture from the project root with its existing .gitignore.")
    base = (cwd / "data").resolve()
    output = (base / "mt5" / run_name).resolve()
    if base != cwd / "data" or not output.is_relative_to(base) or output == base:
        raise MT5Error("Output must remain inside the local ignored data directory.")
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise MT5Error("Run name already exists; choose a new run name.") from None
    return output


def _validate_bounds(duration: float, interval_ms: int) -> None:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise MT5Error("Duration must be greater than 0 and at most 120 seconds.")
    if not math.isfinite(duration) or not 0 < duration <= 120:
        raise MT5Error("Duration must be greater than 0 and at most 120 seconds.")
    if type(interval_ms) is not int or not 50 <= interval_ms <= 10_000:
        raise MT5Error("Polling interval must be 50 to 10000 milliseconds.")


def capture(adapter, symbol, metadata, *, duration, interval_ms, output, clock=time):
    """Poll snapshots in acquisition order; preserve duplicates and return sanitized counts."""
    _validate_bounds(duration, interval_ms)
    engine = make_engine(symbol)
    total = fresh = duplicates = changes = stale = 0
    last_signature = None
    deadline = clock.monotonic() + duration
    with ObservationStore(output / "observations.duckdb") as store:
        while clock.monotonic() < deadline:
            raw = adapter.quote(symbol)
            observation = engine.process(raw, metadata, processing_time_ns=clock.time_ns())
            store.append(observation)
            total += 1
            status = quote_status(observation)
            if status == "STALE":
                stale += 1
            if QualityFlag.DUPLICATE in observation.spread.data_quality_flags:
                duplicates += 1
            signature = (raw.source_time_ms, raw.bid, raw.ask, raw.flags)
            if status == "VALID":
                fresh += 1
                if last_signature is not None and signature != last_signature:
                    changes += 1
            if raw.source_time_ms is not None:
                last_signature = signature
            remaining = deadline - clock.monotonic()
            if remaining > 0:
                clock.sleep(min(interval_ms / 1000, remaining))
    if changes:
        status = "OK"
    elif fresh:
        status = "NO_NEW_QUOTES"
    elif stale:
        status = "STALE"
    else:
        status = "NO_NEW_QUOTES"
    summary = {
        "mode": "READ_ONLY_POLLING",
        "account_environment": adapter.environment.value,
        "status": status,
        "snapshots": total,
        "fresh_snapshots": fresh,
        "duplicate_snapshots": duplicates,
        "stale_snapshots": stale,
        "observed_changes": changes,
        "duration_seconds_requested": duration,
        "poll_interval_ms": interval_ms,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def run(args) -> None:
    if args.command == "mt5-capture":
        _validate_bounds(args.duration, args.interval_ms)
    with connect_local(args.terminal_path) as adapter:
        symbol = adapter.select_symbol(args.symbol)
        metadata = adapter.metadata(symbol, confirm_usd_per_oz=args.confirm_usd_per_oz)
        if args.command == "mt5-doctor":
            raw = adapter.quote(symbol)
            obs = make_engine(symbol).process(raw, metadata, processing_time_ns=time.time_ns())
            # Local output intentionally excludes prices, terminal paths, account and server fields.
            print(
                json.dumps(
                    {
                        "mode": "READ_ONLY",
                        "account_environment": adapter.environment.value,
                        "symbol": symbol,
                        "quote_status": quote_status(obs),
                        "quality_flags": list(obs.spread.data_quality_flags),
                        "usd_per_oz_confirmed": metadata.price_unit == "USD_PER_TROY_OUNCE",
                    }
                )
            )
            return
        if adapter.environment != AccountEnvironment.REAL:
            raise MT5Error("Capture requires a verified REAL terminal; doctor may inspect DEMO.")
        output = _new_output(args.run_name)
        result = capture(
            adapter,
            symbol,
            metadata,
            duration=args.duration,
            interval_ms=args.interval_ms,
            output=output,
        )
        print(json.dumps(result, sort_keys=True))
