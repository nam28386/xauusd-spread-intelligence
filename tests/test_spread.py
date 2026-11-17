from decimal import Decimal, getcontext, localcontext

import pytest

from xbsis.models import InstrumentMetadata, QualityFlag
from xbsis.normalization import normalize, parse_price
from xbsis.spread import derive_spread


def test_known_spread_and_display_digits_do_not_round(case):
    result = case.process(bid="2000.100009", ask="2000.350019")
    assert result.spread.spread_usd_per_oz == Decimal("0.250010")
    assert result.spread.spread_points == Decimal("25.0010")
    assert result.quote.raw.bid == "2000.100009"


@pytest.mark.parametrize("point,expected", [("0.01", "25"), ("0.1", "2.5"), ("0.001", "250")])
def test_no_universal_pip_size(case, point, expected):
    quote = case.process().quote
    metadata = InstrumentMetadata.model_validate(case.metadata.model_dump() | {"point_size": point})
    result = derive_spread(quote, metadata, ())
    assert result.spread_points == Decimal(expected)
    assert result.spread_usd_per_oz == Decimal("0.25")


@pytest.mark.parametrize(
    "bid,ask,flag",
    [
        (None, "2", QualityFlag.MISSING_BID),
        ("1", None, QualityFlag.MISSING_ASK),
        ("NaN", "2", QualityFlag.INVALID_BID),
        ("1", "Infinity", QualityFlag.INVALID_ASK),
        ("0", "2", QualityFlag.INVALID_BID),
        ("-1", "2", QualityFlag.INVALID_BID),
        ("3", "2", QualityFlag.CROSSED),
        ("oops", "2", QualityFlag.INVALID_BID),
        ("1e99", "2", QualityFlag.INVALID_BID),
        (" 1", "2", QualityFlag.INVALID_BID),
    ],
)
def test_bad_quotes_are_preserved_and_metrics_null(case, bid, ask, flag):
    result = case.process(bid=bid, ask=ask)
    assert result.quote.raw.bid == bid
    assert result.quote.raw.ask == ask
    assert flag in result.spread.data_quality_flags
    assert result.spread.spread_usd_per_oz is None
    assert result.spread.spread_points is None


def test_equal_quotes_have_zero_spread(case):
    result = case.process(ask=case.raw.bid)
    assert result.spread.spread_usd_per_oz == Decimal("0")
    assert QualityFlag.CROSSED not in result.spread.data_quality_flags


@pytest.mark.parametrize("raw", ["-Infinity", "sNaN", "", "1_000", "0", "-1", "1e-99", "１"])
def test_price_parser_rejects_invalid_values(raw):
    assert parse_price(raw) is None


def test_mapping_must_be_explicit_and_consistent(case):
    for updates in [{"symbol_raw": "XAUUSD.unknown"}, {"symbol_canonical": "EURUSD"}]:
        result = case.process(**updates)
        assert result.quote.symbol_canonical is None
        assert result.spread.spread_usd_per_oz is None
        assert QualityFlag.UNSUPPORTED_SYMBOL in result.spread.data_quality_flags
    assert normalize(case.raw, {}, mapping_version="empty-v1").symbol_canonical is None


def test_missing_metadata_is_not_invented(case):
    result = case.engine().process(case.raw, None, processing_time_ns=case.raw.received_time_ns)
    assert result.spread.spread_usd_per_oz is None
    assert result.spread.spread_points is None
    assert QualityFlag.METADATA_MISSING in result.spread.data_quality_flags


def test_unit_and_point_missingness_independent(case):
    quote = case.process().quote
    unknown_unit = InstrumentMetadata.model_validate(
        case.metadata.model_dump() | {"price_unit": "UNKNOWN", "quote_currency": "UNKNOWN"}
    )
    result = derive_spread(quote, unknown_unit, ())
    assert result.spread_usd_per_oz is None
    assert result.spread_points == Decimal("25")
    assert QualityFlag.UNKNOWN_PRICE_UNIT in result.data_quality_flags
    missing_point = InstrumentMetadata.model_validate(
        case.metadata.model_dump() | {"point_size": None}
    )
    result = derive_spread(quote, missing_point, ())
    assert result.spread_usd_per_oz == Decimal("0.25")
    assert result.spread_points is None


@pytest.mark.parametrize("bid,ask", [("1.00000", "1.00001"), ("2000.10", "2000.35"), ("1", "1")])
def test_nonnegative_spread_and_points_identity(case, bid, ask):
    result = case.process(bid=bid, ask=ask).spread
    assert result.spread_usd_per_oz >= 0
    assert result.spread_points * Decimal("0.01") == result.spread_usd_per_oz


def test_arithmetic_is_independent_of_ambient_context(case):
    with localcontext() as context:
        context.prec = 3
        record = case.process(bid="2000.100009", ask="2000.350019")
        assert record.spread.spread_usd_per_oz == Decimal("0.250010")
        assert getcontext().prec == 3


def test_recurring_point_ratio_has_documented_rounding(case):
    metadata = InstrumentMetadata.model_validate(case.metadata.model_dump() | {"point_size": "3"})
    quote = case.process(bid="2000", ask="2001").quote
    with localcontext() as context:
        context.prec = 2
        result = derive_spread(quote, metadata, ())
    assert str(result.spread_points) == "0." + "3" * 80


def test_subtraction_does_not_lose_small_quote_difference(case):
    record = case.process(bid="2000.000000000000000001", ask="2000.000000000000000002")
    assert record.spread.spread_usd_per_oz == Decimal("0.000000000000000001")
    assert record.spread.spread_points == Decimal("0.0000000000000001")
