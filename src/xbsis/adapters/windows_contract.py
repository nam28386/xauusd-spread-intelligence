"""Windows-only future SDK boundary. Phase 01 contains no real SDK binding.

The port is testable on Linux with fakes. No initialize/login/account/history/
order/position operations are exposed. A production binding is a separate phase.
"""

from typing import Annotated, Protocol

from pydantic import Field

from xbsis.models import (
    AccountEnvironment,
    Contract,
    Identifier,
    IngestionMode,
    RawPrice,
    RawQuote,
)


class WindowsSourceConfig(Contract):
    source_id: Identifier
    broker_id: Identifier
    server_id: Identifier
    account_environment: AccountEnvironment = AccountEnvironment.UNKNOWN
    symbol_raw: Identifier


class TickSnapshot(Contract):
    bid: RawPrice | None
    ask: RawPrice | None
    source_time_ms: Annotated[int, Field(strict=True, ge=0)] | None
    flags: Annotated[int, Field(strict=True, ge=0)]


class ReadOnlyTickPort(Protocol):
    def symbol_info_tick(self, symbol: str) -> TickSnapshot | None:
        """Return only sanitized quote fields; no account/session fields."""
        ...


def map_snapshot(
    config: WindowsSourceConfig, snapshot: TickSnapshot | None, *, received_time_ns: int
) -> RawQuote:
    """Pure mapping of a future local snapshot. Does not call a port or SDK.

    A missing tick yields missing sides/time instead of reusing the previous tick.
    The future binding must timestamp reception immediately after its local read.
    """
    return RawQuote(
        **config.model_dump(),
        symbol_canonical=None,
        bid=snapshot.bid if snapshot else None,
        ask=snapshot.ask if snapshot else None,
        source_time_ms=snapshot.source_time_ms if snapshot else None,
        received_time_ns=received_time_ns,
        flags=snapshot.flags if snapshot else 0,
        ingestion_mode=IngestionMode.MT5_LOCAL,
        source_sequence_or_null=None,
    )
