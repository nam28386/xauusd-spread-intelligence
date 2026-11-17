"""One transformation path for all permitted adapters, with explicit processing time."""

from collections.abc import Mapping

from xbsis.models import InstrumentMetadata, Observation, RawQuote
from xbsis.normalization import normalize
from xbsis.quality import DataQuality
from xbsis.spread import derive_spread


class SpreadEngine:
    def __init__(
        self,
        *,
        mapping: Mapping[str, str],
        mapping_version: str,
        stale_after_ns: int = 5_000_000_000,
    ) -> None:
        self.mapping = dict(mapping)
        self.mapping_version = mapping_version
        self.quality = DataQuality(stale_after_ns=stale_after_ns)

    def process(
        self, raw: RawQuote, metadata: InstrumentMetadata | None, *, processing_time_ns: int
    ) -> Observation:
        quote = normalize(raw, self.mapping, mapping_version=self.mapping_version)
        flags = self.quality.evaluate(quote, processing_time_ns=processing_time_ns)
        return Observation(
            quote=quote,
            metadata=metadata,
            spread=derive_spread(quote, metadata, flags),
            processing_time_ns=processing_time_ns,
        )
