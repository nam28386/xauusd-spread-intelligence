# Windows local multi-terminal validation — Phase 02.5

**LOCAL_EXNESS_UNVERIFIED / LOCAL_PEPPERSTONE_UNVERIFIED.** The cloud has run only
FakeMT5. No real terminal, account or simultaneous Windows SDK session has been
validated. This repository is public: never upload real quotes, account details,
terminal files or logs. Keep local data outside cloud-synced directories; protect
it with OS permissions and disk encryption.

## Prepare two terminals

Use Windows x64, Python 3.12 and uv 0.13.6. Install Exness MT5 and Pepperstone MT5
in **different installation directories** using their official installers. Start
each terminal and authenticate manually using your normal broker process. The app
does not register accounts, request/store passwords, call login, or switch accounts.
Confirm personally inside each terminal that the intended broker and REAL/DEMO
account are active. Two terminals using the same executable are not supported as
independent sources; same-mode account switches cannot be detected without reading
account identifiers, which this system intentionally does not do.

From the project root, install dependencies once, before starting either worker:

```powershell
uv sync --frozen --extra dev --extra mt5
uv run --frozen --no-sync python -m pytest
```

The examples use `--no-sync` so two workers do not modify the shared virtual
environment while running. Each command below is a separate Python process. Do not
run two terminals from one worker or share one SDK session between threads.
The SDK import is Windows-only. Cloud/Linux never installs the `mt5` extra.

## Exness REAL doctor

In PowerShell window A, enter the **actual** terminal executable and exact symbol
locally when prompted. The prompts do not request an account number or password.
No placeholder paths or symbols in this document identify your installation.

```powershell
$ExnessTerminal = Read-Host 'Absolute path to the running Exness terminal64.exe'
$ExnessSymbol = Read-Host 'Exact gold symbol confirmed in the Exness terminal'
uv run --frozen --no-sync python -m xbsis mt5-doctor --terminal-path $ExnessTerminal --symbol $ExnessSymbol --source-id exness.real.01 --broker-id exness --server-alias exness-real-a --confirm-usd-per-oz
```

Use `--confirm-usd-per-oz` **only after** verifying from the instrument specification
that the quote is USD per troy ounce. The SDK profit-currency field alone does not
prove the quote unit. Without confirmation, USD/oz spread remains null. If profit
currency is not USD, the unit remains UNKNOWN even with confirmation. Point spread
uses the source's actual point size. Doctor displays the selected symbol, user
aliases, account environment, quote status, quote currency, price unit, point,
tick size, contract size and versioned metadata. It does not show prices, terminal
paths or account identifiers. Confirm each value with the terminal/broker details.

Aliases are user labels, **not** SDK-verified broker or server identities; do not
put account numbers, names, credentials or personal information in them. Numeric-only
aliases are rejected. Doctor requires `VALID` and `REAL` for the first milestone;
`STALE`, `CLOCK_SKEW`, and `INVALID_OR_MISSING` are not valid fresh quotes. If the
symbol is ambiguous, omit `--symbol` in the doctor command to list local candidates,
then repeat with the exact chosen symbol.

## Pepperstone DEMO doctor

In PowerShell window B, from the same project root, enter the different terminal
installation and its exact symbol:

```powershell
$PepperstoneTerminal = Read-Host 'Absolute path to the running Pepperstone terminal64.exe'
$PepperstoneSymbol = Read-Host 'Exact gold symbol confirmed in the Pepperstone terminal'
uv run --frozen --no-sync python -m xbsis mt5-doctor --terminal-path $PepperstoneTerminal --symbol $PepperstoneSymbol --source-id pepperstone.demo.01 --broker-id pepperstone --server-alias pepperstone-demo-a --confirm-usd-per-oz
```

Check `DEMO`, fresh `VALID` and the instrument specification as above. A future FP
Markets DEMO can use the same CLI with a third installation and distinct aliases;
there is no broker-specific implementation or automated account setup.

## Two 120-second captures

After completing the doctors and confirming broker, account environment, symbol
and metadata in **both** terminals, start the following command in window A:

```powershell
uv run --frozen --no-sync python -m xbsis mt5-capture --terminal-path $ExnessTerminal --symbol $ExnessSymbol --source-id exness.real.01 --broker-id exness --server-alias exness-real-a --confirm-usd-per-oz --confirm-real --account-type UNKNOWN --run-name exness-001
```

While that command is running, start this command in window B:

```powershell
uv run --frozen --no-sync python -m xbsis mt5-capture --terminal-path $PepperstoneTerminal --symbol $PepperstoneSymbol --source-id pepperstone.demo.01 --broker-id pepperstone --server-alias pepperstone-demo-a --confirm-usd-per-oz --confirm-demo --account-type UNKNOWN --run-name pepperstone-001
```

Remove `--confirm-usd-per-oz` unless you verified that unit for each broker. REAL
and DEMO confirmation flags are mutually exclusive and must match SDK `trade_mode`;
UNKNOWN and mismatches fail before recording. The current mode is rechecked before
each quote. A same-mode manual account change remains undetectable: do not change
accounts during a run. The optional `--account-type` is a **user-supplied label**:
`STANDARD`, `RAW`, `RAZOR` or `UNKNOWN`. Do not infer it from spreads or set it
without verifying it yourself; it is stored only in the local summary as an assertion.

Each process is bound to one terminal installation and one identity. A Windows named
mutex prevents another XBSIS worker in the same Windows session using the same
installation; the guard is not a lock against MT5 itself or other applications.
Each worker has its own engine, quality state and unique local directory. The SDK
may launch/reconnect a terminal as part of initialization if its state changes after
preflight; `terminal_info.path` is checked against the selected installation after
attachment and before each snapshot. If process-path inspection, connectivity or
path matching fails, capture stops. The
Windows mutex and real concurrent SDK behavior still require local validation.

Duration defaults to 120 seconds, polling to 250 ms. `--duration` accepts >0 to 120
seconds and `--interval-ms` 50–10000. The loop uses a monotonic deadline but cannot
bound a blocked external SDK call. Polling produces snapshots; it cannot capture
all broker ticks or support a claim about executable spread or arbitrage.

## Local files and sanitized summaries

Use a fresh run name each time. Files are under ignored `data/mt5/exness-001/` and
`data/mt5/pepperstone-001/`; existing run names cannot be overwritten. Each
`observations.duckdb` contains private raw snapshots and must never be uploaded.
Each `summary.json` contains status, REAL/DEMO, the user account-type label and
counts, without prices, symbol, aliases, timestamps, paths or account identifiers.
If a run fails or is interrupted, the DuckDB may contain partial data and no summary;
keep it local, diagnose safely, and use a new run name for another attempt:

```powershell
Get-Content 'data\mt5\exness-001\summary.json'
Get-Content 'data\mt5\pepperstone-001\summary.json'
```

Review a summary locally before sharing it. The following optional command inspects
**real quote values locally only**; never paste its output into chat, GitHub or logs:

```powershell
uv run --frozen --no-sync python -c "from pathlib import Path; from xbsis.storage import ObservationStore; s=ObservationStore(Path('data/mt5/exness-001/observations.duckdb')); r=s.records()[-1]; print('source=',r.quote.raw.source_id,'environment=',r.quote.raw.account_environment,'bid=',r.quote.raw.bid,'ask=',r.quote.raw.ask,'source_ms=',r.quote.raw.source_time_ms,'spread_usd_per_oz=',r.spread.spread_usd_per_oz,'points=',r.spread.spread_points,'flags=',r.spread.data_quality_flags); s.close()"
```

Repeat using the Pepperstone path to inspect that source. Compare its Bid/Ask and
ask-minus-bid locally with the matching terminal, allowing for intervening price
changes. Never compare REAL and DEMO as equivalent execution costs. Source and
receive timestamps are separate; broker quote time is not an exchange timestamp.

`NO_NEW_QUOTES` means no fresh distinct follow-up snapshot was observed; the initial
snapshot alone does not establish a new event. `STALE` means no valid fresh quote
and at least one stale snapshot. `OK` means at least one fresh change was observed.
Missing/stale/duplicate flags remain attached to each snapshot; no forward fill.
SDK binary floats are converted with `str(float)`, preserving the SDK value's
round-trip representation, not original broker wire precision. Metadata versions
hash the source aliases, environment, selected symbol and specification values;
this identifies a captured specification, not its authenticity or acquisition time.
