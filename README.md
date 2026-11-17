# XAUUSD Broker Spread Intelligence System (XBSIS)

Read-only, local-first XAUUSD observation with a synthetic Phase 01 core and an
explicitly invoked Windows MT5 Phase 02.5 adapter for isolated source workers. This repository is public. Only
synthetic fixtures belong in Git; never upload account data or real market quotes.

```sh
uv sync --frozen --extra dev
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev ruff format --check .
uv run --frozen --extra dev pytest
uv run --frozen python scripts/audit_repository.py
uv run --frozen python scripts/smoke_api.py
uv run --frozen python -m xbsis replay
```

Toolchain: CPython 3.12; uv 0.13.6. `uv.lock` pins transitive dependencies and
artifact hashes. `dev` is optional; **never use `--all-extras` in Linux CI**.
`mt5` is optional and Windows AMD64 only; Linux never imports or installs it.
For explicit local Windows doctor/capture, see [Windows runbook](docs/WINDOWS_RUNBOOK.md).
Cloud FakeMT5 checks do not verify actual terminal connectivity.

Start the synthetic API explicitly:

```sh
uv run --frozen python -m xbsis serve
```

The CLI binds to `127.0.0.1:8000`, with no host option. Use local HTTP requests to
`/health`, `/v1/quotes`, `/v1/metadata`, `/docs` and `/openapi.json`.
Responses always identify synthetic replay; startup does not poll a broker.

Optional **local** fixture storage (choose a new directory each export):

```sh
uv run --frozen python -m xbsis replay --output-dir data/synthetic-run-001
```

Default replay prints only a deterministic summary, not raw quotes, and writes
nothing. Explicit export writes ignored DuckDB and Parquet files. Do not force-add
local outputs to Git, even if they appear harmless.

See [product scope](docs/PRODUCT.md), [architecture](docs/ARCHITECTURE.md),
[data contract](docs/DATA_CONTRACT.md), [security](docs/SECURITY.md),
[Windows runbook](docs/WINDOWS_RUNBOOK.md), [implementation plan](docs/IMPLEMENTATION_PLAN.md)
and [Phase 01 evidence](docs/PHASE01_REPORT.md). Contributor rules: [AGENTS.md](AGENTS.md).
