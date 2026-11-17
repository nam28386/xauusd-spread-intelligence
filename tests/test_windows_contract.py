import pytest
from pydantic import ValidationError

from xbsis.adapters.windows_contract import (
    ReadOnlyTickPort,
    TickSnapshot,
    WindowsSourceConfig,
    map_snapshot,
)
from xbsis.models import AccountEnvironment, IngestionMode, QualityFlag
from xbsis.pipeline import SpreadEngine


def config():
    return WindowsSourceConfig(
        source_id="synthetic-windows",
        broker_id="synthetic-broker",
        server_id="synthetic-server",
        symbol_raw="XAUUSD.mock",
    )


class FakeTickPort:
    def symbol_info_tick(self, symbol: str) -> TickSnapshot | None:
        assert symbol == "XAUUSD.mock"
        return TickSnapshot(
            bid="2000.10000", ask="2000.35000", source_time_ms=1700000000000, flags=2
        )


def test_windows_boundary_with_fake_only(case):
    port: ReadOnlyTickPort = FakeTickPort()
    raw = map_snapshot(
        config(), port.symbol_info_tick("XAUUSD.mock"), received_time_ns=1700000000010000123
    )
    assert raw.bid == "2000.10000"
    assert raw.flags == 2
    assert raw.ingestion_mode == IngestionMode.MT5_LOCAL
    assert raw.account_environment == AccountEnvironment.UNKNOWN
    assert raw.source_sequence_or_null is None
    engine = SpreadEngine(mapping={"XAUUSD.mock": "XAUUSD"}, mapping_version="synthetic-v1")
    record = engine.process(raw, case.metadata, processing_time_ns=raw.received_time_ns)
    assert str(record.spread.spread_usd_per_oz) == "0.25000"


def test_no_tick_maps_to_missing_not_previous_quote(case):
    raw = map_snapshot(config(), None, received_time_ns=1700000000010000123)
    record = case.engine().process(raw, case.metadata, processing_time_ns=raw.received_time_ns)
    assert raw.bid is None and raw.ask is None
    assert QualityFlag.MISSING_BID in record.spread.data_quality_flags
    assert QualityFlag.MISSING_ASK in record.spread.data_quality_flags


@pytest.mark.parametrize("field", ["password", "account_number", "terminal_path", "token"])
def test_windows_config_rejects_credentials_and_session_paths(field):
    with pytest.raises(ValidationError):
        WindowsSourceConfig.model_validate(config().model_dump() | {field: "forbidden-extra"})
