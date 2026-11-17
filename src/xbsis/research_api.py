"""Bounded local research services over sealed session segments only."""

import itertools
import json
from decimal import Decimal, InvalidOperation

from xbsis.analytics import compare, summarize
from xbsis.sessions import _directory, iter_observations, read_manifest


def threshold_value(text: str) -> Decimal:
    if len(text) > 80:
        raise ValueError("threshold too long")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError("invalid threshold") from None
    if (
        not value.is_finite()
        or value < 0
        or not -18 <= value.adjusted() <= 18
        or len(value.as_tuple().digits) > 38
    ):
        raise ValueError("invalid threshold")
    return value


def stats(session_id, threshold, freshness_ns, start_ns=None, end_ns=None):
    manifest = read_manifest(session_id)
    segments = manifest["segments"]
    if not segments:
        raise ValueError("no sealed observations")
    bounds = (
        [int(s["min_receive_ns"]) for s in segments],
        [int(s["max_receive_ns"]) for s in segments],
    )
    first, last = min(bounds[0]), max(bounds[1])
    start = first if start_ns is None else max(first, start_ns)
    end = last if end_ns is None else min(last, end_ns)
    if start > end:
        raise ValueError("window does not overlap sealed observations")
    metrics = summarize(
        iter_observations(session_id),
        start_ns=start,
        end_ns=end,
        freshness_ns=freshness_ns,
        widening_threshold=threshold_value(threshold),
    )
    return {
        "session_id": session_id,
        "session_state": manifest["state"],
        "source": manifest["source"],
        "code_revision": manifest["code_revision"],
        "code_dirty": manifest.get("code_dirty"),
        "sealed_segments": len(segments),
        "metrics": metrics,
    }


def comparison(left_id, right_id, tolerance_ns):
    if left_id == right_id:
        raise ValueError("select two different sessions")
    left = read_manifest(left_id)
    right = read_manifest(right_id)
    if not left["segments"] or not right["segments"]:
        raise ValueError("both sessions require sealed observations")
    left_source, right_source = left.get("source"), right.get("source")
    if not left_source or not right_source or left_source["source_id"] == right_source["source_id"]:
        raise ValueError("sessions require distinct source identities")
    left_iter = iter(iter_observations(left_id))
    right_iter = iter(iter_observations(right_id))
    left_first, right_first = next(left_iter, None), next(right_iter, None)
    if left_first is None or right_first is None:
        raise ValueError("both sessions require observations")
    for observation in (left_first, right_first):
        metadata = observation.metadata
        if (
            metadata is None
            or metadata.quote_currency != "USD"
            or metadata.price_unit != "USD_PER_TROY_OUNCE"
        ):
            raise ValueError("both sources require confirmed USD per troy ounce units")
    result = compare(
        itertools.chain((left_first,), left_iter),
        itertools.chain((right_first,), right_iter),
        tolerance_ns=tolerance_ns,
    )
    return {
        "left_instrument": left_first.metadata.model_dump(mode="json"),
        "right_instrument": right_first.metadata.model_dump(mode="json"),
        "left_session": left_id,
        "right_session": right_id,
        "left_source": left_source,
        "right_source": right_source,
        "left_state": left["state"],
        "right_state": right["state"],
        "result": result,
    }


def report(session_id, threshold, freshness_ns):
    result = stats(session_id, threshold, freshness_ns)
    summary_path = _directory(session_id) / "summary.json"
    summary = None
    if (
        summary_path.is_file()
        and not summary_path.is_symlink()
        and summary_path.stat().st_size <= 16384
    ):
        source = json.loads(summary_path.read_text(encoding="utf-8"))
        summary = {
            key: source.get(key)
            for key in (
                "mode",
                "status",
                "snapshots",
                "fresh_snapshots",
                "duplicate_snapshots",
                "stale_snapshots",
                "observed_changes",
                "queue_dropped_display",
                "account_type_user_label",
            )
        }
    return {
        "report_version": "research-report-v1",
        "research": result,
        "capture_summary": summary,
        "comparison_method_version": "receive-asof-v1",
        "epistemic_status": "MEASUREMENT",
        "execution_costs": "UNKNOWN",
    }
