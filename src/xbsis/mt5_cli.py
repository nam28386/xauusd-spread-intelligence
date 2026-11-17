"""Explicit local doctor and bounded capture; summaries never contain quotes or identities."""

import json
import math
import re
import time
from pathlib import Path

from pydantic import ValidationError

from xbsis.adapters.mt5 import MT5Error, SourceIdentity, connect_local, make_engine, quote_status
from xbsis.models import AccountEnvironment, QualityFlag
from xbsis.storage import ObservationStore


def add_commands(commands) -> None:
    for command in ("mt5-doctor", "mt5-capture"):
        parser = commands.add_parser(command, help="explicit local Windows MT5 read-only operation")
        parser.add_argument("--terminal-path", required=True, type=Path)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--broker-id", required=True)
        parser.add_argument("--server-alias", required=True)
        parser.add_argument("--symbol", required=command == "mt5-capture")
        parser.add_argument("--confirm-usd-per-oz", action="store_true")
        if command == "mt5-capture":
            confirmation = parser.add_mutually_exclusive_group(required=True)
            confirmation.add_argument("--confirm-real", action="store_true")
            confirmation.add_argument("--confirm-demo", action="store_true")
            parser.add_argument(
                "--account-type", choices=("STANDARD", "RAW", "RAZOR", "UNKNOWN"), default="UNKNOWN"
            )
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


def _validate_bounds(duration: float, interval_ms: int, *, max_duration: int = 120) -> None:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise MT5Error(f"Duration must be greater than 0 and at most {max_duration} seconds.")
    if not math.isfinite(duration) or not 0 < duration <= max_duration:
        raise MT5Error(f"Duration must be greater than 0 and at most {max_duration} seconds.")
    if type(interval_ms) is not int or not 50 <= interval_ms <= 10_000:
        raise MT5Error("Polling interval must be 50 to 10000 milliseconds.")


def capture(
    adapter,
    symbol,
    metadata,
    *,
    duration,
    interval_ms,
    output,
    clock=time,
    account_type="UNKNOWN",
    on_observation=None,
    stop_event=None,
    max_duration=120,
    store_context=None,
):
    """Poll snapshots in acquisition order; preserve duplicates and return sanitized counts."""
    _validate_bounds(duration, interval_ms, max_duration=max_duration)
    if account_type not in {"STANDARD", "RAW", "RAZOR", "UNKNOWN"}:
        raise MT5Error("Invalid account type label.")
    engine = make_engine(symbol)
    total = fresh = duplicates = changes = stale = 0
    last_signature = None
    deadline = clock.monotonic() + duration
    with store_context or ObservationStore(output / "observations.duckdb") as store:
        while clock.monotonic() < deadline and (stop_event is None or not stop_event.is_set()):
            raw = adapter.quote(symbol)
            observation = engine.process(raw, metadata, processing_time_ns=clock.time_ns())
            store.append(observation)
            if on_observation is not None:
                on_observation(observation)
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
                delay = min(interval_ms / 1000, remaining)
                if stop_event is not None:
                    stop_event.wait(delay)
                else:
                    clock.sleep(delay)
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
        "account_type_user_label": account_type,
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
    try:
        identity = SourceIdentity(
            source_id=args.source_id, broker_id=args.broker_id, server_id=args.server_alias
        )
    except ValidationError:
        raise MT5Error(
            "Invalid source, broker or server alias; use non-sensitive identifiers."
        ) from None
    if args.command == "mt5-capture":
        real = getattr(args, "confirm_real", False)
        demo = getattr(args, "confirm_demo", False)
        if real == demo:
            raise MT5Error("Confirm exactly one of REAL or DEMO.")
    with connect_local(args.terminal_path, identity=identity) as adapter:
        if args.command == "mt5-capture":
            expected = AccountEnvironment.REAL if real else AccountEnvironment.DEMO
            if adapter.environment != expected:
                raise MT5Error(
                    f"Capture requires a verified {expected.value} terminal; "
                    "actual environment differs or is UNKNOWN."
                )
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
                        "aliases_user_supplied": identity.model_dump(mode="json"),
                        "broker_identity_verified": False,
                        "instrument": metadata.model_dump(mode="json"),
                        "quote_status": quote_status(obs),
                        "quality_flags": list(obs.spread.data_quality_flags),
                        "usd_per_oz_confirmed": metadata.price_unit == "USD_PER_TROY_OUNCE",
                    }
                )
            )
            return
        output = _new_output(args.run_name)
        result = capture(
            adapter,
            symbol,
            metadata,
            duration=args.duration,
            interval_ms=args.interval_ms,
            output=output,
            account_type=args.account_type,
        )
        print(json.dumps(result, sort_keys=True))
