"""Metric v1: ask minus bid; points use instrument point_size, never pips."""

from decimal import ROUND_HALF_EVEN, Context, localcontext

from xbsis.models import DerivedSpread, InstrumentMetadata, NormalizedQuote, QualityFlag

ARITHMETIC = Context(prec=80, rounding=ROUND_HALF_EVEN)


def derive_spread(
    quote: NormalizedQuote,
    metadata: InstrumentMetadata | None,
    flags: tuple[QualityFlag, ...],
) -> DerivedSpread:
    quality = set(flags)
    usd = points = None
    if metadata is None:
        quality.add(QualityFlag.METADATA_MISSING)
    elif metadata.price_unit != "USD_PER_TROY_OUNCE" or metadata.quote_currency != "USD":
        quality.add(QualityFlag.UNKNOWN_PRICE_UNIT)
    if (
        quote.symbol_canonical is not None
        and quote.bid is not None
        and quote.ask is not None
        and quote.ask >= quote.bid
    ):
        with localcontext(ARITHMETIC):
            difference = quote.ask - quote.bid
            if metadata is not None:
                if metadata.price_unit == "USD_PER_TROY_OUNCE" and metadata.quote_currency == "USD":
                    usd = difference
                if metadata.point_size is not None:
                    points = difference / metadata.point_size
    return DerivedSpread(
        spread_usd_per_oz=usd,
        spread_points=points,
        data_quality_flags=tuple(sorted(quality)),
    )
