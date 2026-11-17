"""Per-stream replay state. Time comparisons are diagnostics, not latency claims."""

from dataclasses import dataclass

from xbsis.models import NormalizedQuote, QualityFlag


@dataclass
class StreamState:
    signature: tuple[object, ...] | None = None
    source_high_water_ms: int | None = None
    receive_high_water_ns: int | None = None


class DataQuality:
    def __init__(self, *, stale_after_ns: int = 5_000_000_000) -> None:
        if type(stale_after_ns) is not int or stale_after_ns < 0:
            raise ValueError("stale_after_ns must be a nonnegative integer")
        self.stale_after_ns = stale_after_ns
        self._streams: dict[tuple[object, ...], StreamState] = {}

    def evaluate(
        self, quote: NormalizedQuote, *, processing_time_ns: int
    ) -> tuple[QualityFlag, ...]:
        raw = quote.raw
        if type(processing_time_ns) is not int or processing_time_ns < raw.received_time_ns:
            raise ValueError("processing clock must be integer ns >= receive clock")
        flags: list[QualityFlag] = []
        for side in ("bid", "ask"):
            if getattr(raw, side) is None:
                flags.append(QualityFlag[f"MISSING_{side.upper()}"])
            elif getattr(quote, side) is None:
                flags.append(QualityFlag[f"INVALID_{side.upper()}"])
        if quote.bid is not None and quote.ask is not None and quote.ask < quote.bid:
            flags.append(QualityFlag.CROSSED)
        if quote.symbol_canonical is None:
            flags.append(QualityFlag.UNSUPPORTED_SYMBOL)
        key = (
            raw.source_id,
            raw.broker_id,
            raw.server_id,
            raw.account_environment,
            raw.symbol_raw,
            raw.ingestion_mode,
        )
        state = self._streams.setdefault(key, StreamState())
        signature = (raw.source_time_ms, raw.source_sequence_or_null, raw.bid, raw.ask, raw.flags)
        identifiable = raw.source_time_ms is not None or raw.source_sequence_or_null is not None
        if identifiable and signature == state.signature:
            flags.append(QualityFlag.DUPLICATE)
        if state.receive_high_water_ns is not None:
            if raw.received_time_ns < state.receive_high_water_ns:
                flags.append(QualityFlag.RECEIVE_TIME_REVERSED)
        state.receive_high_water_ns = max(state.receive_high_water_ns or 0, raw.received_time_ns)
        if raw.source_time_ms is None:
            flags.append(QualityFlag.MISSING_SOURCE_TIME)
        else:
            source_ns = raw.source_time_ms * 1_000_000
            if source_ns > raw.received_time_ns:
                flags.append(QualityFlag.FUTURE_SOURCE_TIME)
            if processing_time_ns - source_ns > self.stale_after_ns:
                flags.append(QualityFlag.STALE)
            if state.source_high_water_ms is not None:
                if raw.source_time_ms < state.source_high_water_ms:
                    flags.append(QualityFlag.SOURCE_OUT_OF_ORDER)
            state.source_high_water_ms = max(state.source_high_water_ms or 0, raw.source_time_ms)
        state.signature = signature
        return tuple(sorted(flags))
