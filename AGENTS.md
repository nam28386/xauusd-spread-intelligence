# XBSIS contributor contract

## Scope and safety
- Phase 01 is synthetic, read-only observation only. Never trade, submit/modify
  orders, manage positions, or call order/position APIs. Do not add execution code.
- Never connect cloud tasks to MT5 or a broker. Do not request/store account IDs,
  passwords, investor passwords, tokens, cookies, sessions, or terminal logs.
- Keep this repository private. Change only this repository. Before any push,
  verify private visibility; if unknown, stop the upload. Never merge into main.
- Use a dedicated feature branch and a Draft PR. No automatic merging. An empty
  remote has no PR base: do not seed main without separate authorization.
- Only visibly synthetic fixtures belong in Git. No real quotes, account data,
  databases, Parquet files, terminal files, or local logs may be committed.
- Servers bind to 127.0.0.1 by default. No public bind or remote ingestion endpoint.

## Architecture
`BrokerAdapter -> RawQuote -> normalize -> DataQuality -> SpreadEngine -> Storage -> API`
Core modules have no platform SDK imports or network side effects. Adapters emit
immutable raw records. Preserve raw strings and all clocks; derive Decimal values
without rounding to display digits. Explicit symbol mappings and versioned metadata
are required. Unknowns remain null. No forward fill, pip assumptions, commission,
slippage, execution, analytics models, frontend, or broker comparisons in Phase 01.
Windows integration is a contract with fake-port tests only, not a live collector.

## Development and review
Use the existing isolated checkout; do not create worktrees unless requested.
Python 3.12, uv.lock, `uv sync --frozen --extra dev` (never `--all-extras` in Linux).
Run `uv run --frozen --extra dev ruff check .`, `ruff format --check .`, and
`uv run --frozen --extra dev pytest`. Replay with `uv run --frozen python -m xbsis replay`.
Review formulas, null behavior, units, Decimal coercions, all four clock roles,
stream boundaries, fixture hash, SDK isolation, and ignored outputs. New semantics
require version/documentation changes and independent expected-value tests.
Passing tests establishes software behavior, not live compatibility or market facts.
