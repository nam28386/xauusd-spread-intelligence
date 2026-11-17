"""Versioned descriptive quote research; never execution cost or trading advice."""

from decimal import ROUND_FLOOR, Context, Decimal, localcontext

from xbsis.models import Observation, QualityFlag

METRIC_VERSION = "spread-statistics-v1"
COMPARISON_VERSION = "receive-asof-v1"
CONTEXT = Context(prec=80)
MAX_ROWS = 640_000
MAX_EVENTS = 1000
BAD = {
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


def valid(obs: Observation) -> bool:
    meta = obs.metadata
    return (
        obs.spread.spread_usd_per_oz is not None
        and not BAD.intersection(obs.spread.data_quality_flags)
        and meta is not None
        and meta.quote_currency == "USD"
        and meta.price_unit == "USD_PER_TROY_OUNCE"
    )


def percentile(sorted_values: list[Decimal], fraction: Decimal) -> Decimal | None:
    if not sorted_values:
        return None
    with localcontext(CONTEXT):
        position = Decimal(len(sorted_values) - 1) * fraction
        low = int(position.to_integral_value(rounding=ROUND_FLOOR))
        high = min(low + 1, len(sorted_values) - 1)
        return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _decimal(value):
    return None if value is None else str(value)


def summarize(
    observations, *, start_ns: int, end_ns: int, freshness_ns: int, widening_threshold: Decimal
) -> dict:
    """Snapshot quantiles and bounded forward intervals using receive time only.

    The last observation contributes through end only when supplied inside the
    known session boundary. Invalid observations terminate preceding validity.
    """
    if not 0 <= start_ns <= end_ns or not 1 <= freshness_ns <= 300_000_000_000:
        raise ValueError("invalid research window or freshness limit")
    if not widening_threshold.is_finite() or widening_threshold < 0:
        raise ValueError("invalid widening threshold")
    count = stale = duplicate = invalid = changes = observed = 0
    values = []
    metadata_versions = {}
    metadata_truncated = False
    covered = 0
    weighted = Decimal(0)
    last = None
    previous_time = None
    signature = None
    event = None
    events = []
    event_count = 0

    def finish_event(end: int, *, recovered: bool):
        nonlocal event, event_count
        if event is None:
            return
        event_count += 1
        if len(events) < MAX_EVENTS:
            events.append(
                {
                    "start_ns": str(event["start"]),
                    "end_ns": str(end),
                    "widening_duration_ns": str(max(0, end - event["start"])),
                    "recovery_duration_ns": str(max(0, end - event["last_high"]))
                    if recovered
                    else None,
                    "recovered": recovered,
                }
            )
        event = None

    def interval(previous, next_time: int):
        nonlocal covered, weighted
        if previous is None or not valid(previous):
            return
        t = previous.quote.raw.received_time_ns
        left = max(t, start_ns)
        right = min(next_time, t + freshness_ns, end_ns)
        if right > left:
            delta = right - left
            covered += delta
            with localcontext(CONTEXT):
                weighted += previous.spread.spread_usd_per_oz * delta

    for obs in observations:
        observed += 1
        if obs.metadata is not None and obs.metadata.metadata_version not in metadata_versions:
            if len(metadata_versions) < 64:
                metadata_versions[obs.metadata.metadata_version] = obs.metadata.model_dump(
                    mode="json"
                )
            else:
                metadata_truncated = True
        if observed > MAX_ROWS:
            raise ValueError("session exceeds analytics row limit")
        raw = obs.quote.raw
        t = raw.received_time_ns
        if previous_time is not None and t < previous_time:
            if start_ns <= t <= end_ns:
                count += 1
                invalid += 1
            if event is not None:
                finish_event(min(previous_time, end_ns), recovered=False)
            last = None
            continue
        interval(last, t)
        if event is not None and last is not None:
            expiry = last.quote.raw.received_time_ns + freshness_ns
            if not valid(last) or t > expiry:
                finish_event(min(expiry, end_ns), recovered=False)
        in_window = start_ns <= t <= end_ns
        if in_window:
            count += 1
            flags = set(obs.spread.data_quality_flags)
            stale += QualityFlag.STALE in flags
            duplicate += QualityFlag.DUPLICATE in flags
            if not valid(obs):
                invalid += 1
            else:
                spread = obs.spread.spread_usd_per_oz
                values.append(spread)
                current_signature = (raw.source_time_ms, raw.bid, raw.ask, raw.flags)
                if signature is not None and current_signature != signature:
                    changes += 1
                signature = current_signature
                if spread >= widening_threshold:
                    if event is None:
                        event = {"start": t, "last_high": t}
                    else:
                        event["last_high"] = t
                elif event is not None:
                    finish_event(t, recovered=True)
            if not valid(obs) and event is not None:
                finish_event(t, recovered=False)
        previous_time = t
        last = obs
    interval(last, end_ns)
    if event is not None:
        cap = min(end_ns, last.quote.raw.received_time_ns + freshness_ns)
        finish_event(cap, recovered=False)
    values.sort()
    duration = end_ns - start_ns
    with localcontext(CONTEXT):
        mean = sum(values, Decimal(0)) / len(values) if values else None
        time_mean = weighted / covered if covered else None
        coverage = Decimal(covered) / duration if duration else None
        intensity = Decimal(changes) * 1_000_000_000 / covered if covered else None
        rates = {
            "stale": _decimal(Decimal(stale) / count) if count else None,
            "duplicate": _decimal(Decimal(duplicate) / count) if count else None,
            "invalid": _decimal(Decimal(invalid) / count) if count else None,
        }
    return {
        "metric_version": METRIC_VERSION,
        "unit": "USD_PER_TROY_OUNCE",
        "instrument_metadata": list(metadata_versions.values()),
        "metadata_truncated": metadata_truncated,
        "window": {
            "start_ns": str(start_ns),
            "end_ns": str(end_ns),
            "freshness_ns": str(freshness_ns),
        },
        "snapshots": count,
        "valid_snapshots": len(values),
        "invalid_snapshots": invalid,
        "mean": _decimal(mean),
        "median": _decimal(percentile(values, Decimal("0.5"))),
        "p95": _decimal(percentile(values, Decimal("0.95"))),
        "p99": _decimal(percentile(values, Decimal("0.99"))),
        "minimum": _decimal(values[0] if values else None),
        "maximum": _decimal(values[-1] if values else None),
        "time_weighted_mean": _decimal(time_mean),
        "valid_duration_ns": str(covered),
        "valid_coverage": _decimal(coverage),
        "quality_rates": rates,
        "stale_snapshots": stale,
        "duplicate_snapshots": duplicate,
        "observed_changes": changes,
        "changes_per_valid_second": _decimal(intensity),
        "widening_threshold": str(widening_threshold),
        "widening_count": event_count,
        "widening_events": events,
        "events_truncated": event_count > len(events),
    }


def compare(left, right, *, tolerance_ns: int, row_limit=1000) -> dict:
    """Backward-only as-of match in receive time, without filling invalid observations."""
    if not 0 <= tolerance_ns <= 300_000_000_000 or not 1 <= row_limit <= 1000:
        raise ValueError("invalid comparison bounds")
    iterator = iter(right)
    pending = next(iterator, None)
    prior = None
    right_time = -1
    left_time = -1
    count = matched = unmatched = 0
    total = Decimal(0)
    total_absolute = Decimal(0)
    max_absolute = None
    rows = []
    for a in left:
        count += 1
        if count > MAX_ROWS:
            raise ValueError("session exceeds comparison row limit")
        t = a.quote.raw.received_time_ns
        left_reversed = t < left_time
        left_time = max(left_time, t)
        while pending is not None and pending.quote.raw.received_time_ns <= t:
            candidate_time = pending.quote.raw.received_time_ns
            if candidate_time >= right_time:
                prior = pending
                right_time = candidate_time
            else:
                # A backwards clock jump is a discontinuity, not permission to
                # reuse an older quote past the invalid observation.
                prior = None
            pending = next(iterator, None)
        if (
            left_reversed
            or not valid(a)
            or prior is None
            or not valid(prior)
            or t - prior.quote.raw.received_time_ns > tolerance_ns
        ):
            unmatched += 1
            continue
        matched += 1
        with localcontext(CONTEXT):
            delta = a.spread.spread_usd_per_oz - prior.spread.spread_usd_per_oz
            total += delta
            absolute = abs(delta)
            total_absolute += absolute
            max_absolute = absolute if max_absolute is None else max(max_absolute, absolute)
        if len(rows) < row_limit:
            rows.append(
                {
                    "evaluation_ns": str(t),
                    "matched_receive_ns": str(prior.quote.raw.received_time_ns),
                    "age_ns": str(t - prior.quote.raw.received_time_ns),
                    "left_bid": a.quote.raw.bid,
                    "left_ask": a.quote.raw.ask,
                    "right_bid": prior.quote.raw.bid,
                    "right_ask": prior.quote.raw.ask,
                    "left_spread": str(a.spread.spread_usd_per_oz),
                    "right_spread": str(prior.spread.spread_usd_per_oz),
                    "left_points": _decimal(a.spread.spread_points),
                    "right_points": _decimal(prior.spread.spread_points),
                    "spread_difference": str(delta),
                }
            )
    with localcontext(CONTEXT):
        coverage = Decimal(matched) / count if count else None
        mean = total / matched if matched else None
        mean_absolute = total_absolute / matched if matched else None
    return {
        "method_version": COMPARISON_VERSION,
        "tolerance_ns": str(tolerance_ns),
        "evaluations": count,
        "matched": matched,
        "unmatched": unmatched,
        "coverage": _decimal(coverage),
        "mean_spread_difference": _decimal(mean),
        "mean_absolute_spread_difference": _decimal(mean_absolute),
        "max_absolute_spread_difference": _decimal(max_absolute),
        "rows": rows,
        "rows_truncated": matched > len(rows),
        "warning": (
            "REAL and DEMO are not equivalent execution costs; quotes do not establish arbitrage."
        ),
    }
