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


Phase 03 synthetic local dashboard (two spawned mock workers, no SDK):

```sh
uv run --frozen python -m xbsis live-serve --mode mock --port 8765
```

Open the local `/live/` route in your browser. See the Windows runbook for ignored
local source configuration, explicit real-mode confirmation and two-terminal setup.
Cloud mock results do not verify Windows SDK connectivity.

## Local research workstation

The existing dashboard now includes sealed local session history, descriptive
spread statistics and backward-looking two-source comparison. Install and try
synthetic mode on Windows from PowerShell:

```powershell
.\scripts\install.ps1
.\scripts\start.ps1 -Mode mock
Start-Process 'http://127.0.0.1:8765/live/'
```

The server stays up after its default 120-second capture; stop it with Ctrl+C.
For local Windows MT5, install with `-IncludeMT5`, prepare the ignored source file
as described in [Windows runbook](docs/WINDOWS_RUNBOOK.md), then use
`.\scripts\start.ps1 -Mode mt5 -SourcesFile data/config/sources.json -ConfirmLiveReadonly -Duration 28800`.
Only confirm a REAL/DEMO environment and USD per troy ounce unit after checking it
locally. Never commit local configuration or data. See the [user guide](docs/V1_USER_GUIDE.md),
[methodology](docs/ANALYTICS_METHODOLOGY.md), and [acceptance steps](docs/LOCAL_ACCEPTANCE.md).
Cloud mocks do not establish real Windows, broker or executable-price behavior.
