"""Bounded in-memory live view; the hub never opens worker-owned storage."""

import asyncio
import multiprocessing
import queue
import sys
import time
import uuid
from collections import deque

from xbsis.live_workers import mock_worker, mt5_worker
from xbsis.models import IngestionMode, Observation, QualityFlag

MAX_HISTORY = 6000
STALE_SECONDS = 5.0


class LiveHub:
    def __init__(self, mode, sources, duration, *, queue_size=128, context=None):
        self.mode = mode
        self.sources = sources
        self.duration = duration
        self.context = context or multiprocessing.get_context("spawn")
        self.queue = self.context.Queue(maxsize=queue_size)
        self.stop_event = self.context.Event()
        self.workers = []
        self.entries = {}
        self._task = None
        self._run_id = uuid.uuid4().hex[:12]
        self._started = time.monotonic()
        self.clients = 0
        self.rejected_events = 0
        for source in sources:
            self.entries[source["source_id"]] = {
                "source": {
                    k: source[k]
                    for k in (
                        "source_id",
                        "broker_id",
                        "server_alias",
                        "expected_account_environment",
                        "account_type_user_label",
                        "symbol",
                    )
                },
                "state": self.context.Value("i", 0),
                "dropped": self.context.Value("L", 0),
                "latest": None,
                "last_valid": None,
                "history": deque(maxlen=MAX_HISTORY),
                "sequence": 0,
                "duplicates": 0,
                "stale": 0,
                "changes": 0,
                "last_seen": None,
                "last_change": None,
                "signature": None,
                "gap": False,
                "last_dropped": 0,
                "active_since": None,
                "active_until": None,
            }

    def start(self):
        try:
            for i, source in enumerate(self.sources):
                entry = self.entries[source["source_id"]]
                common = (
                    i,
                    self.queue,
                    entry["dropped"],
                    entry["state"],
                    self.stop_event,
                    self.duration,
                    self._run_id,
                )
                args = common if self.mode == "mock" else (i, source, *common[1:])
                worker = self.context.Process(
                    target=mock_worker if self.mode == "mock" else mt5_worker,
                    args=args,
                    daemon=False,
                )
                worker.start()
                self.workers.append(worker)
        except Exception:
            self.stop_event.set()
            self.close()
            raise
        self._task = asyncio.create_task(self._pump())

    async def _pump(self):
        while not self.stop_event.is_set():
            self.drain()
            self.refresh()
            await asyncio.sleep(0.05)
        self.drain()
        self.refresh()

    def drain(self):
        for _ in range(256):
            try:
                msg = self.queue.get_nowait()
            except queue.Empty:
                break
            if (
                not isinstance(msg, dict)
                or msg.get("kind") != "observation"
                or msg.get("source_id") not in self.entries
            ):
                self.rejected_events += 1
                continue
            try:
                obs = Observation.model_validate(msg["observation"])
                expected = self.entries[msg["source_id"]]["source"]
                raw = obs.quote.raw
                if (
                    raw.source_id != expected["source_id"]
                    or raw.broker_id != expected["broker_id"]
                    or raw.server_id != expected["server_alias"]
                    or raw.account_environment.value != expected["expected_account_environment"]
                    or raw.symbol_raw != expected["symbol"]
                    or raw.ingestion_mode
                    != (
                        IngestionMode.MOCK_REPLAY
                        if self.mode == "mock"
                        else IngestionMode.MT5_LOCAL
                    )
                ):
                    self.rejected_events += 1
                    continue
            except Exception:
                self.rejected_events += 1
                continue
            self.accept(msg["source_id"], obs)

    def accept(self, source_id, obs, *, now=None):
        entry = self.entries[source_id]
        now = time.monotonic() if now is None else now
        raw = obs.quote.raw
        flags = set(obs.spread.data_quality_flags)
        invalid = bool(
            flags
            & {
                QualityFlag.STALE,
                QualityFlag.CROSSED,
                QualityFlag.MISSING_BID,
                QualityFlag.MISSING_ASK,
                QualityFlag.INVALID_BID,
                QualityFlag.INVALID_ASK,
                QualityFlag.MISSING_SOURCE_TIME,
                QualityFlag.FUTURE_SOURCE_TIME,
                QualityFlag.UNSUPPORTED_SYMBOL,
                QualityFlag.SOURCE_OUT_OF_ORDER,
                QualityFlag.RECEIVE_TIME_REVERSED,
            }
        )
        dropped = entry["dropped"].value
        if dropped > entry["last_dropped"]:
            entry["history"].append(
                {
                    "time_ns": str(raw.received_time_ns),
                    "source_time_ms": raw.source_time_ms,
                    "spread": None,
                    "at": now,
                }
            )
            entry["last_dropped"] = dropped
        if QualityFlag.DUPLICATE in flags:
            entry["duplicates"] += 1
        if QualityFlag.STALE in flags:
            entry["stale"] += 1
        signature = (raw.source_time_ms, raw.bid, raw.ask, raw.flags)
        changed = not invalid and entry["signature"] is not None and signature != entry["signature"]
        if not invalid and raw.source_time_ms is not None:
            entry["signature"] = signature
            if changed:
                entry["changes"] += 1
                entry["last_change"] = now
            elif entry["last_change"] is None:
                entry["last_change"] = now
        entry["sequence"] += 1
        entry["last_seen"] = now
        entry["latest"] = obs.model_dump(mode="json")
        if not invalid:
            entry["last_valid"] = entry["latest"]
        # Invalid and stale samples explicitly break the plotted line. Duplicates do not
        # create new price events; preserve the latest quote in the card regardless.
        if invalid or QualityFlag.DUPLICATE not in flags:
            point = {
                "time_ns": str(raw.received_time_ns),
                "source_time_ms": raw.source_time_ms,
                "spread": None
                if invalid or obs.spread.spread_usd_per_oz is None
                else str(obs.spread.spread_usd_per_oz),
                "at": now,
            }
            entry["history"].append(point)
        entry["gap"] = invalid

    def refresh(self):
        now = time.monotonic()
        for i, source in enumerate(self.sources):
            entry = self.entries[source["source_id"]]
            if i < len(self.workers):
                worker = self.workers[i]
                if worker.exitcode is not None and entry["state"].value in (0, 1, 2):
                    entry["state"].value = 3 if worker.exitcode == 0 else 4
            current_state = entry["state"].value
            if current_state == 2 and entry["active_since"] is None:
                entry["active_since"] = now
            elif (
                current_state in (3, 4, 5)
                and entry["active_since"] is not None
                and entry["active_until"] is None
            ):
                entry["active_until"] = now
            if entry["last_seen"] is not None and (
                now - entry["last_seen"] > STALE_SECONDS or current_state in (3, 4, 5, 6, 7)
            ):
                if not entry["gap"] and entry["latest"] is not None:
                    raw = entry["latest"]["quote"]["raw"]
                    entry["history"].append(
                        {
                            "time_ns": raw["received_time_ns"],
                            "source_time_ms": raw["source_time_ms"],
                            "spread": None,
                            "at": now,
                        }
                    )
                    entry["gap"] = True

    def status(self, entry, now):
        state = entry["state"].value
        if state == 6:
            return "STORAGE_LIMIT"
        if state == 7:
            return "FORCED_TERMINATION"
        if state == 4:
            return "ERROR"
        if state == 5:
            return "DISCONNECTED"
        if state == 3:
            return "STOPPED"
        if state == 0 or state == 1 or entry["latest"] is None:
            return "CONNECTING"
        if entry["last_seen"] is None or now - entry["last_seen"] > STALE_SECONDS:
            return "STALE"
        flags = entry["latest"]["spread"]["data_quality_flags"]
        if "STALE" in flags:
            return "STALE"
        if self.mode == "mt5":
            local_age = time.time_ns() - int(entry["latest"]["quote"]["raw"]["received_time_ns"])
            if local_age < 0:
                return "INVALID"
            if local_age > STALE_SECONDS * 1_000_000_000:
                return "STALE"
        if any(
            flag in flags
            for flag in (
                "CROSSED",
                "MISSING_BID",
                "MISSING_ASK",
                "INVALID_BID",
                "INVALID_ASK",
                "MISSING_SOURCE_TIME",
                "FUTURE_SOURCE_TIME",
                "UNSUPPORTED_SYMBOL",
                "SOURCE_OUT_OF_ORDER",
                "RECEIVE_TIME_REVERSED",
            )
        ):
            return "INVALID"
        if now - entry["last_change"] > STALE_SECONDS:
            return "NO_NEW_QUOTES"
        return "MOCK" if self.mode == "mock" else "LIVE"

    def snapshot(self):
        self.refresh()
        now = time.monotonic()
        sources = []
        for entry in self.entries.values():
            index = len(sources)
            output_run = f"{'mock' if self.mode == 'mock' else 'live'}-{self._run_id}-{index}"
            sources.append(
                entry["source"]
                | {
                    "output_run": output_run,
                    "status": self.status(entry, now),
                    "latest": entry["latest"],
                    "last_valid": entry["last_valid"],
                    "sequence": entry["sequence"],
                    "duplicates": entry["duplicates"],
                    "stale_observations": entry["stale"],
                    "observed_changes": entry["changes"],
                    "queue_dropped": entry["dropped"].value,
                    "account_environment_verified_at_last_observation": (
                        self.mode == "mt5" and entry["latest"] is not None
                    ),
                    "active_seconds": None
                    if entry["active_since"] is None
                    else round((entry["active_until"] or now) - entry["active_since"], 1),
                    "last_update_age_seconds": None
                    if entry["last_seen"] is None
                    else round(now - entry["last_seen"], 2),
                }
            )
        return {
            "mode": self.mode.upper(),
            "sources": sources,
            "rejected_events": self.rejected_events,
            "session_seconds": round(now - self._started, 1),
        }

    def history(self, source_id, seconds):
        entry = self.entries.get(source_id)
        if entry is None:
            return None
        cutoff = time.monotonic() - seconds
        return [
            {k: v for k, v in point.items() if k != "at"}
            for point in entry["history"]
            if point["at"] >= cutoff
        ]

    def close(self):
        self.stop_event.set()
        if self._task:
            self._task.cancel()
        for index, worker in enumerate(self.workers):
            deadline = time.monotonic() + 3
            while worker.is_alive() and time.monotonic() < deadline:
                self.drain()
                worker.join(timeout=0.05)
            if worker.is_alive():
                print("A worker did not stop cleanly and was terminated.", file=sys.stderr)
                worker.terminate()
                worker.join(timeout=2)
                self.entries[self.sources[index]["source_id"]]["state"].value = 7
                if not worker.is_alive():
                    from xbsis.sessions import mark_forced_termination

                    session_id = (
                        f"{'mock' if self.mode == 'mock' else 'live'}-{self._run_id}-{index}"
                    )
                    try:
                        mark_forced_termination(session_id)
                    except (OSError, ValueError):
                        pass  # The worker may have failed before creating a manifest.
        self.drain()
        self.refresh()
        self.queue.close()
        self.queue.cancel_join_thread()
