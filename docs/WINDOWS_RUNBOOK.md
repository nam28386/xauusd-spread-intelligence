# Windows runbook — Phase 01 offline validation only

No live MT5 connector is implemented. Codex Cloud has not accessed and must never
access your local MT5 or account. The existing logged-in terminal is not required
for any step below. Leave it untouched; do not export or upload its state.

## Supported offline workflow

Use 64-bit CPython 3.12 on Windows and uv 0.13.6. Review/merge the feature PR manually
when a valid base branch exists; clone only this private repository over an approved
GitHub connection. Do not copy terminal folders, account config or datasets into it.
PowerShell, in the checkout:

```powershell
uv sync --frozen --extra dev
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev ruff format --check .
uv run --frozen --extra dev pytest
uv run --frozen python scripts/audit_repository.py
uv run --frozen python scripts/smoke_api.py
uv run --frozen python -m xbsis replay
uv run --frozen python -m xbsis serve
```

The smoke script starts/stops its own local server on port 18761. The serve command
remains foreground on 127.0.0.1:8000; stop with Ctrl+C. Validate with
`Invoke-RestMethod http://127.0.0.1:8000/health` from another local shell. It must report
MOCK_REPLAY and live_connectivity=NOT_TESTED, never a broker connection.

Optional local synthetic export:
`uv run --frozen python -m xbsis replay --output-dir data/synthetic-windows-001`.
This exercises DuckDB/Parquet only; do not commit outputs. The same nine fixture
observations and summary hashes should match Linux. Windows execution itself has
not been verified by the cloud task; record your actual outcome locally.

## Future MT5 integration contract — not an instruction to connect now

`adapters/windows_contract.py` provides config aliases, TickSnapshot, the narrow
`ReadOnlyTickPort.symbol_info_tick` protocol and pure `map_snapshot` conversion.
It has no initialize/login/account/history/order/position methods, SDK import or
terminal path. Linux tests use FakeTickPort only. REAL/DEMO/UNKNOWN is explicitly
supplied by a future local user configuration; never query the account to infer it.

The optional `mt5` dependency is declared/locked for Windows AMD64 only. Installing
it is unnecessary in Phase 01; do not use `--all-extras`. A separate reviewed phase
must implement the actual Windows binding and local consent/startup flow. It must
read only approved quote/metadata fields and never credentials or account data.

A future SDK returns binary floats; converting with `str(value)` preserves the SDK's
round-trip decimal representation, not original broker wire precision. Record that
provenance explicitly; never claim additional precision or round to `digits`.
Capture receive ns immediately after the local read, processing ns separately;
source time_msc is broker-source time, not exchange time. Missing snapshot/time,
symbol availability, metadata provenance, clock drift and reconnect behavior need
explicit local validation before any live collection is considered complete.

Do not paste screenshots/logs/quotes/account details into GitHub or chat for debugging.
Only sanitized synthetic reproduction and pass/fail summaries may be shared.
