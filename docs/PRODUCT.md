# Product contract — Phase 01

XBSIS-P01 is a personal, API-first observation system for XAUUSD broker quotes.
Its present evidence status is **SOFTWARE_CONTRACT_ONLY**. Fixtures are entirely
synthetic; software checks make no claim about an actual broker, latency, market
quality, execution cost, profitability, or live MT5 compatibility.

The system preserves a source quote, normalizes explicit symbol aliases, diagnoses
quality, derives a price difference, optionally stores it locally and exposes it
through a read-only localhost API. Stream identifiers prepare the schema for future
comparison; no multi-broker integration or comparison exists in this phase.

Required deliverables: immutable Pydantic contracts, Decimal arithmetic, deterministic
mock replay, unit/invariant/temporal/integration tests, exact-text DuckDB/Parquet
storage, read-only mock API, dependency isolation, CI, and a Windows boundary/runbook.

Out of scope: live collection, SDK initialization, broker authentication, account
inspection, trading/position/order operations, commission/slippage estimates,
frontend/Plotly, multi-broker analytics, and statistical research claims.

Raw prices, source and local clocks must survive every transformation. Unknown
values remain null; no guessed pip size, symbol suffix, metadata or fill is allowed.
A stale/duplicate quote may retain a diagnostic spread but is never labeled fresh.
Crossed/invalid/missing sides produce null metrics. No quote is silently dropped.

Acceptance requires real execution of the core suite on Linux, repeated identical
mock replay, provenance and quality assertions, a localhost functional request,
local storage round trips, and a repository safety review. GitHub-hosted CI and
Windows checks are separate outcomes and must never be claimed from Linux tests.

## Local research scope

Overview, Realtime, Compare, History, Analytics and System present observations,
quality and operational status, plus an explicit aggregate JSON download. The
research view is descriptive: FACT is a recorded observation and its provenance;
MEASUREMENT is a computed statistic; INFERENCE is an interpretation; HYPOTHESIS
requires testing; UNKNOWN includes execution costs and unverified connectivity.
REAL and DEMO observations do not establish comparable execution conditions.
Polling is incomplete and local clock alignment is uncertain.
