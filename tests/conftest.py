from dataclasses import dataclass

import pytest

from xbsis.adapters.mock import MockBrokerAdapter
from xbsis.models import InstrumentMetadata, RawQuote
from xbsis.pipeline import SpreadEngine


@dataclass
class Case:
    raw: RawQuote
    metadata: InstrumentMetadata

    def engine(self, **kwargs: object) -> SpreadEngine:
        return SpreadEngine(
            mapping={"XAUUSD.mock": "XAUUSD"}, mapping_version="test-mapping-v1", **kwargs
        )

    def process(self, **updates: object):
        raw = RawQuote.model_validate(self.raw.model_dump() | updates)
        return self.engine().process(
            raw, self.metadata, processing_time_ns=raw.received_time_ns + 1000
        )


@pytest.fixture
def case() -> Case:
    adapter = MockBrokerAdapter()
    return Case(next(adapter.quotes()), adapter.metadata)
