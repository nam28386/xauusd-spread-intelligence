from decimal import Decimal

import pytest
from pydantic import ValidationError

from xbsis.models import InstrumentMetadata, Observation, RawQuote


def test_raw_preserves_original_text_and_is_immutable(case):
    raw = case.raw
    assert raw.bid == "2000.10000"
    assert raw.ask == "2000.35000"
    with pytest.raises(ValidationError):
        raw.bid = "1"
    assert RawQuote.model_validate_json(raw.model_dump_json()) == raw


@pytest.mark.parametrize(
    "field,value",
    [
        ("bid", 2000.1),
        ("ask", 2001),
        ("received_time_ns", True),
        ("received_time_ns", 1.5),
        ("received_time_ns", -1),
        ("source_time_ms", -1),
        ("source_time_ms", 1.5),
        ("source_time_ms", True),
        ("flags", -1),
        ("source_sequence_or_null", -1),
        ("account_environment", "LIVE"),
        ("ingestion_mode", "UNKNOWN"),
        ("account_number", "forbidden-extra"),
        ("password", "forbidden-extra"),
    ],
)
def test_invalid_contract_input_rejected(case, field, value):
    with pytest.raises(ValidationError):
        RawQuote.model_validate(case.raw.model_dump() | {field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("point_size", "0"),
        ("tick_size", "-0.01"),
        ("contract_size", "NaN"),
        ("point_size", 0.01),
        ("digits", 1.5),
        ("digits", 19),
        ("quote_currency", "EUR"),
        ("point_size", "1e99"),
        ("point_size", "bad"),
    ],
)
def test_invalid_metadata_rejected(case, field, value):
    with pytest.raises(ValidationError):
        InstrumentMetadata.model_validate(case.metadata.model_dump() | {field: value})


def test_json_preserves_decimal_and_nanosecond_precision(case):
    record = case.process()
    data = record.model_dump(mode="json")
    assert data["quote"]["raw"]["received_time_ns"] == "1700000000010000123"
    assert data["processing_time_ns"] == "1700000000010001123"
    assert data["spread"]["spread_usd_per_oz"] == "0.25000"
    assert data["quote"]["bid"] == "2000.10000"
    assert Observation.model_validate_json(record.model_dump_json()) == record
    assert record.quote.bid == Decimal("2000.1")


def test_persisted_record_cannot_invert_processing_clock(case):
    data = case.process().model_dump()
    data["processing_time_ns"] = case.raw.received_time_ns - 1
    with pytest.raises(ValidationError, match="processing clock"):
        Observation.model_validate(data)


def test_derived_contract_rejects_float_and_negative_values(case):
    from xbsis.models import DerivedSpread

    for invalid in [0.1, "-0.1", "NaN"]:
        data = case.process().spread.model_dump() | {"spread_points": invalid}
        with pytest.raises(ValidationError):
            DerivedSpread.model_validate(data)
