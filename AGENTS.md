# XBSIS contributor contract

## Scope and safety
- This repository is public by owner approval. Commit only source, docs and visibly
  synthetic fixtures. Never upload real quotes, account data, terminal logs, SDK
  session files, credentials, tokens, database files or other local runtime data.
- Never connect cloud tasks to MT5 or a broker. Never request/store account IDs,
  passwords, investor passwords, tokens, cookies or terminal sessions.
- Observation only: never submit/modify orders, manage positions, switch accounts,
  or introduce automated execution or account/history APIs. The Windows adapter
  may read only the SDK account trade-mode enum and must discard the account object.
- Use dedicated feature branches and Draft PRs; never merge automatically or change
  other repositories. Do not rewrite the Phase 01 commit or golden fixtures.
- Local API servers bind to 127.0.0.1 by default. No public bind or remote ingestion.

## Architecture
`BrokerAdapter -> RawQuote -> normalize -> DataQuality -> SpreadEngine -> Storage -> API`
Preserve raw price text and distinct clocks, use versioned metadata and explicit
symbol mapping. Unknowns remain null. No forward fill, universal pip assumption,
commission or slippage inference. MT5 is optional and imported lazily only for an
explicit local Windows operation. SDK float-to-string conversion cannot reconstruct
wire precision. Polling captures snapshots, not all source ticks. The Phase 01 API
remains synthetic and separate from live local capture.

## Development and review
Use the existing isolated checkout; do not create worktrees unless requested.
Python 3.12, uv.lock, `uv sync --frozen --extra dev` (never `--all-extras` on Linux).
Run `uv run --frozen --extra dev ruff check .`, `ruff format --check .`, and
`uv run --frozen --extra dev pytest`. Replay with `uv run --frozen python -m xbsis replay`.
Review formulas, units, Decimal coercions, timestamps, SDK isolation and ignored
outputs. New semantics require version/documentation changes and tests. Passing
cloud FakeMT5 tests does not establish actual Windows or broker connectivity.

## Session research and release review
Sessions rotate into immutable sealed DuckDB segments; never query an active writer
file. Review interrupted state, size/duration bounds and recovery behavior before
changing storage. Analytics must document receive-time validity, uncertainty, units,
thresholds and as-of alignment; never label observed differences arbitrage or execution
costs. Keep report exports local. Browser and Windows FakeSDK tests do not replace
actual Windows terminal acceptance. Do not merge automatically.
