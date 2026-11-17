"""Acquisition boundary: source order must be preserved, not sorted by source clock."""

from collections.abc import Iterator
from typing import Protocol

from xbsis.models import RawQuote


class BrokerAdapter(Protocol):
    def quotes(self) -> Iterator[RawQuote]:
        """Yield raw observations without mutation or forward fill."""
        ...
