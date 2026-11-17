import pytest

from xbsis.models import QualityFlag, RawQuote


def process(engine, case, **updates):
    processing = updates.pop("processing_time_ns", None)
    raw = RawQuote.model_validate(case.raw.model_dump() | updates)
    return engine.process(
        raw,
        case.metadata,
        processing_time_ns=raw.received_time_ns if processing is None else processing,
    )


def test_separate_clock_units_and_stale_threshold(case):
    source_ns = case.raw.source_time_ms * 1_000_000
    for age, stale in [(5_000_000_000, False), (5_000_000_001, True)]:
        record = process(case.engine(), case, received_time_ns=source_ns + age)
        assert (QualityFlag.STALE in record.spread.data_quality_flags) == stale
        assert record.quote.raw.source_time_ms == case.raw.source_time_ms
        assert record.processing_time_ns == source_ns + age


def test_waiting_for_processing_can_make_quote_stale(case):
    record = process(
        case.engine(), case, processing_time_ns=case.raw.received_time_ns + 6_000_000_000
    )
    assert QualityFlag.STALE in record.spread.data_quality_flags


def test_processing_before_receive_is_rejected_and_does_not_mutate_state(case):
    engine = case.engine()
    with pytest.raises(ValueError, match="processing clock"):
        process(engine, case, processing_time_ns=case.raw.received_time_ns - 1)
    assert QualityFlag.DUPLICATE not in process(engine, case).spread.data_quality_flags


def test_missing_time_is_unknown_and_future_source_time_is_flagged(case):
    unknown = process(case.engine(), case, source_time_ms=None)
    assert QualityFlag.MISSING_SOURCE_TIME in unknown.spread.data_quality_flags
    assert QualityFlag.STALE not in unknown.spread.data_quality_flags
    assert unknown.quote.raw.source_time_ms is None
    future = process(case.engine(), case, source_time_ms=case.raw.source_time_ms + 1000)
    assert QualityFlag.FUTURE_SOURCE_TIME in future.spread.data_quality_flags


def test_duplicate_preserved_even_with_new_receive_time(case):
    engine = case.engine()
    first = process(engine, case)
    second = process(engine, case, received_time_ns=case.raw.received_time_ns + 1)
    assert QualityFlag.DUPLICATE not in first.spread.data_quality_flags
    assert QualityFlag.DUPLICATE in second.spread.data_quality_flags
    assert second.quote.raw.received_time_ns != first.quote.raw.received_time_ns
    assert second.spread.spread_usd_per_oz == first.spread.spread_usd_per_oz


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "synthetic-other-source"),
        ("broker_id", "synthetic-other-broker"),
        ("server_id", "synthetic-other-server"),
        ("account_environment", "DEMO"),
        ("symbol_raw", "XAUUSD.other"),
        ("ingestion_mode", "MT5_LOCAL"),
    ],
)
def test_quality_state_isolated_per_stream(case, field, value):
    engine = case.engine()
    process(engine, case)
    result = process(engine, case, **{field: value})
    assert QualityFlag.DUPLICATE not in result.spread.data_quality_flags
    assert QualityFlag.SOURCE_OUT_OF_ORDER not in result.spread.data_quality_flags


def test_out_of_order_and_receive_regression_use_high_water_marks(case):
    engine = case.engine()
    process(engine, case)
    result = process(
        engine,
        case,
        source_time_ms=case.raw.source_time_ms - 2,
        received_time_ns=case.raw.received_time_ns - 2,
    )
    assert QualityFlag.SOURCE_OUT_OF_ORDER in result.spread.data_quality_flags
    assert QualityFlag.RECEIVE_TIME_REVERSED in result.spread.data_quality_flags
    result = process(
        engine,
        case,
        source_time_ms=case.raw.source_time_ms - 1,
        received_time_ns=case.raw.received_time_ns - 1,
    )
    assert QualityFlag.SOURCE_OUT_OF_ORDER in result.spread.data_quality_flags
    assert QualityFlag.RECEIVE_TIME_REVERSED in result.spread.data_quality_flags


def test_no_forward_fill(case):
    engine = case.engine()
    process(engine, case)
    missing = process(engine, case, bid=None, ask=None, source_time_ms=None)
    assert missing.quote.bid is None
    assert missing.quote.ask is None
    assert missing.spread.spread_usd_per_oz is None


def test_no_identity_time_does_not_guess_duplicate(case):
    engine = case.engine()
    process(engine, case, source_time_ms=None)
    record = process(engine, case, source_time_ms=None)
    assert QualityFlag.DUPLICATE not in record.spread.data_quality_flags
