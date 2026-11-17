"""Explicit symbol mapping; no guessed suffixes, rounding or forward filling."""

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from xbsis.models import NormalizedQuote, RawQuote

DECIMAL_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def parse_price(raw: str | None) -> Decimal | None:
    if raw is None or not DECIMAL_TEXT.fullmatch(raw):
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    if len(value.as_tuple().digits) > 38 or not -18 <= value.adjusted() <= 18:
        return None
    return value


def normalize(
    raw: RawQuote, mapping: Mapping[str, str], *, mapping_version: str
) -> NormalizedQuote:
    canonical = mapping.get(raw.symbol_raw)
    if canonical != "XAUUSD" or raw.symbol_canonical not in (None, canonical):
        canonical = None
    return NormalizedQuote(
        raw=raw,
        symbol_canonical=canonical,
        bid=parse_price(raw.bid),
        ask=parse_price(raw.ask),
        mapping_version=mapping_version,
    )
