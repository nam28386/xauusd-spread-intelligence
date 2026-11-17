"""Packaged, explicitly synthetic fixture; replay has no wall-clock dependency."""

import hashlib
import json
from collections.abc import Iterator
from importlib.resources import files

from xbsis.models import InstrumentMetadata, Observation, RawQuote
from xbsis.pipeline import SpreadEngine


class MockBrokerAdapter:
    def __init__(self) -> None:
        content = files("xbsis.fixtures").joinpath("quotes.json").read_bytes()
        manifest = json.loads(files("xbsis.fixtures").joinpath("manifest.json").read_bytes())
        if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
            raise ValueError("synthetic fixture hash mismatch")
        self.fixture_sha256 = manifest["sha256"]
        fixture = json.loads(content)
        self.metadata = InstrumentMetadata.model_validate(fixture["metadata"])
        self.mapping = fixture["mapping"]
        self.mapping_version = fixture["mapping_version"]
        self._quotes = tuple(RawQuote.model_validate(row) for row in fixture["quotes"])
        self._processing_times = tuple(int(t) for t in fixture["processing_times_ns"])
        if len(self._quotes) != len(self._processing_times):
            raise ValueError("one processing time required per quote")

    def quotes(self) -> Iterator[RawQuote]:
        return iter(self._quotes)

    def replay(self) -> tuple[Observation, ...]:
        engine = SpreadEngine(mapping=self.mapping, mapping_version=self.mapping_version)
        return tuple(
            engine.process(quote, self.metadata, processing_time_ns=processing)
            for quote, processing in zip(self._quotes, self._processing_times, strict=True)
        )
