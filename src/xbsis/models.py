"""Immutable, extra-field-forbidden contracts; raw prices are original text."""

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)


def decimal_input(value: object) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("prices/metadata require Decimal or decimal text, never float")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal metadata") from exc
    if not result.is_finite():
        raise ValueError("metadata must be finite")
    if len(result.as_tuple().digits) > 38 or not -18 <= result.adjusted() <= 18:
        raise ValueError("decimal outside v1 precision/range")
    return result


def clock_input(value: object) -> int:
    # Nanoseconds cross JSON as decimal strings to avoid JavaScript precision loss.
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    if type(value) is not int:
        raise ValueError("clock must be integer nanoseconds or unsigned decimal text")
    return value


PositiveDecimal = Annotated[Decimal, BeforeValidator(decimal_input), Field(gt=0)]
Nanoseconds = Annotated[int, BeforeValidator(clock_input), Field(ge=0)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
RawPrice = Annotated[str, Field(strict=True, max_length=128)]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class AccountEnvironment(StrEnum):
    REAL = "REAL"
    DEMO = "DEMO"
    UNKNOWN = "UNKNOWN"


class IngestionMode(StrEnum):
    MOCK_REPLAY = "MOCK_REPLAY"
    MT5_LOCAL = "MT5_LOCAL"


class QualityFlag(StrEnum):
    MISSING_BID = "MISSING_BID"
    MISSING_ASK = "MISSING_ASK"
    INVALID_BID = "INVALID_BID"
    INVALID_ASK = "INVALID_ASK"
    CROSSED = "CROSSED"
    STALE = "STALE"
    DUPLICATE = "DUPLICATE"
    SOURCE_OUT_OF_ORDER = "SOURCE_OUT_OF_ORDER"
    RECEIVE_TIME_REVERSED = "RECEIVE_TIME_REVERSED"
    FUTURE_SOURCE_TIME = "FUTURE_SOURCE_TIME"
    MISSING_SOURCE_TIME = "MISSING_SOURCE_TIME"
    UNSUPPORTED_SYMBOL = "UNSUPPORTED_SYMBOL"
    METADATA_MISSING = "METADATA_MISSING"
    UNKNOWN_PRICE_UNIT = "UNKNOWN_PRICE_UNIT"


class RawQuote(Contract):
    source_id: Identifier
    broker_id: Identifier  # User-defined alias, never an account number.
    server_id: Identifier  # User-defined alias, never a terminal/session identifier.
    account_environment: AccountEnvironment
    symbol_raw: Identifier
    symbol_canonical: Identifier | None
    bid: RawPrice | None
    ask: RawPrice | None
    source_time_ms: Annotated[int, Field(strict=True, ge=0)] | None
    received_time_ns: Nanoseconds
    flags: Annotated[int, Field(strict=True, ge=0)]
    ingestion_mode: IngestionMode
    source_sequence_or_null: Annotated[int, Field(strict=True, ge=0)] | None

    @field_serializer("received_time_ns", when_used="json")
    def serialize_ns(self, value: int) -> str:
        return str(value)


class InstrumentMetadata(Contract):
    symbol_canonical: Literal["XAUUSD"] = "XAUUSD"
    point_size: PositiveDecimal | None
    tick_size: PositiveDecimal | None
    digits: Annotated[int, Field(strict=True, ge=0, le=18)] | None
    contract_size: PositiveDecimal | None
    quote_currency: Literal["USD", "UNKNOWN"]
    price_unit: Literal["USD_PER_TROY_OUNCE", "UNKNOWN"]
    metadata_source: Identifier
    metadata_version: Identifier


def derived_decimal_input(value: object) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise ValueError("derived prices require Decimal or decimal text")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid derived decimal") from exc
    if not result.is_finite():
        raise ValueError("derived decimals must be finite")
    return result


ExactDecimal = Annotated[Decimal, BeforeValidator(derived_decimal_input)]


class NormalizedQuote(Contract):
    raw: RawQuote
    symbol_canonical: Literal["XAUUSD"] | None
    bid: ExactDecimal | None
    ask: ExactDecimal | None
    normalization_version: Literal["normalization-v1"] = "normalization-v1"
    mapping_version: Identifier


class DerivedSpread(Contract):
    spread_usd_per_oz: Annotated[ExactDecimal, Field(ge=0)] | None
    spread_points: Annotated[ExactDecimal, Field(ge=0)] | None
    data_quality_flags: tuple[QualityFlag, ...]
    metric_version: Literal["spread-v1"] = "spread-v1"


class Observation(Contract):
    schema_version: Literal["observation-v1"] = "observation-v1"
    quote: NormalizedQuote
    metadata: InstrumentMetadata | None
    spread: DerivedSpread
    processing_time_ns: Nanoseconds

    @field_serializer("processing_time_ns", when_used="json")
    def serialize_ns(self, value: int) -> str:
        return str(value)

    @model_validator(mode="after")
    def check_processing_clock(self) -> "Observation":
        if self.processing_time_ns < self.quote.raw.received_time_ns:
            raise ValueError("processing clock must be >= receive clock")
        return self
