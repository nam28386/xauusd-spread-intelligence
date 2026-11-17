"""Spawn entrypoints: each owns its engine, store and (only on Windows) SDK session."""

import json
import queue
import time
from decimal import Decimal

from xbsis.adapters.mock import MockBrokerAdapter
from xbsis.models import RawQuote
from xbsis.pipeline import SpreadEngine
from xbsis.sessions import SessionLimitError, SessionRecorder


def publish(out, dropped, message):
    try:
        out.put_nowait(message)
    except queue.Full:
        with dropped.get_lock():
            dropped.value += 1


def mock_worker(index, out, dropped, state, stop, duration, run_id):
    """Two reproducible synthetic sources; no SDK and no external data."""
    # Import only in the worker, to keep output-path ownership out of the hub.
    from xbsis.mt5_cli import _new_output

    source_id = f"synthetic-{index + 1}"
    state.value = 1
    try:
        adapter = MockBrokerAdapter()
        raw_template = next(adapter.quotes()).model_dump()
        engine = SpreadEngine(mapping=adapter.mapping, mapping_version=adapter.mapping_version)
        output = _new_output(f"mock-{run_id}-{index}")
        state.value = 2
        end = time.monotonic() + duration
        step = 0
        with SessionRecorder(output, stop_event=stop) as store:
            while time.monotonic() < end and not stop.is_set():
                event = step // 2
                bid = Decimal("2000.10000") + Decimal(index) + Decimal(event % 5) / 100
                ask = bid + Decimal("0.25000") + Decimal(index) / 100
                source_ms = 1_700_000_000_000 + event * 500
                raw = RawQuote.model_validate(
                    raw_template
                    | {
                        "source_id": source_id,
                        "broker_id": f"synthetic-broker-{index + 1}",
                        "server_id": f"synthetic-server-{index + 1}",
                        "account_environment": "REAL" if index == 0 else "DEMO",
                        "bid": str(bid),
                        "ask": None if event % 12 == 4 else str(ask),
                        "source_time_ms": source_ms,
                        "received_time_ns": (1_700_000_000_000 + step * 250) * 1_000_000,
                    }
                )
                obs = engine.process(raw, adapter.metadata, processing_time_ns=raw.received_time_ns)
                store.append(obs)
                publish(
                    out,
                    dropped,
                    {
                        "kind": "observation",
                        "source_id": source_id,
                        "observation": obs.model_dump(mode="json"),
                    },
                )
                step += 1
                stop.wait(min(0.25, max(0.0, end - time.monotonic())))
        (output / "summary.json").write_text(
            json.dumps({"mode": "MOCK", "snapshots": step, "queue_dropped_display": dropped.value})
            + "\n",
            encoding="utf-8",
        )
        state.value = 3
    except SessionLimitError:
        state.value = 6
    except Exception:
        state.value = 4


def mt5_worker(index, source_data, out, dropped, state, stop, duration, run_id):
    """The SDK is imported lazily only inside this spawned worker."""
    from pathlib import Path

    from xbsis.adapters.mt5 import MT5Error, SourceIdentity, connect_local
    from xbsis.models import AccountEnvironment
    from xbsis.mt5_cli import _new_output, capture

    state.value = 1
    try:
        identity = SourceIdentity(
            source_id=source_data["source_id"],
            broker_id=source_data["broker_id"],
            server_id=source_data["server_alias"],
        )
        with connect_local(Path(source_data["terminal_path"]), identity=identity) as adapter:
            if adapter.environment != AccountEnvironment(
                source_data["expected_account_environment"]
            ):
                raise RuntimeError("account environment mismatch")
            symbol = adapter.select_symbol(source_data["symbol"])
            metadata = adapter.metadata(
                symbol, confirm_usd_per_oz=source_data["confirm_usd_per_oz"]
            )
            output = _new_output(f"live-{run_id}-{index}")
            state.value = 2

            def send(obs):
                publish(
                    out,
                    dropped,
                    {
                        "kind": "observation",
                        "source_id": source_data["source_id"],
                        "observation": obs.model_dump(mode="json"),
                    },
                )

            summary = capture(
                adapter,
                symbol,
                metadata,
                duration=duration,
                interval_ms=source_data["poll_interval_ms"],
                output=output,
                account_type=source_data["account_type_user_label"],
                on_observation=send,
                stop_event=stop,
                max_duration=28_800,
                store_context=SessionRecorder(output, stop_event=stop),
            )
            summary["queue_dropped_display"] = dropped.value
            (output / "summary.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )
        state.value = 3
    except SessionLimitError:
        state.value = 6
    except MT5Error as exc:
        state.value = 5 if str(exc) == "Terminal is disconnected." else 4
    except Exception:
        # Never forward SDK errors, terminal paths, account information or quotes in logs.
        state.value = 4
