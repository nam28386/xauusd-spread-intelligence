# Windows local MT5 validation — Phase 02

Cloud has not accessed your terminal. **LOCAL_MT5_UNVERIFIED** until you execute
these steps locally and confirm the result. This repository is public: never upload
real quotes, account details, terminal files or logs. Keep the data directory out of
cloud-synced folders and protect the machine with OS permissions and disk encryption.

## Prepare

Use Windows x64, Python 3.12, uv 0.13.6 and an already-running MT5 terminal that
you have authenticated yourself. Confirm the intended terminal and account in MT5.
Do not paste credentials or account identifiers into the CLI, chat, issues or files.
The SDK is optional and is installed only on this Windows machine:

```powershell
uv sync --frozen --extra dev --extra mt5
uv run --frozen --extra dev --extra mt5 pytest
```

Check out the reviewed Phase 02 feature branch in the project root. Do not use
`--all-extras` on Linux. The explicit path must point to the running `terminal64.exe`.
Discovery reads local symbol names; if several XAUUSD/GOLD candidates exist, the
command prints them locally and requires an explicit `--symbol` selection. Paths
below are placeholders: substitute your installed terminal path and selected symbol.

```powershell
uv run --frozen --extra mt5 python -m xbsis mt5-doctor --terminal-path 'C:\path\to\terminal64.exe'
uv run --frozen --extra mt5 python -m xbsis mt5-doctor --terminal-path 'C:\path\to\terminal64.exe' --symbol 'XAUUSD' --confirm-usd-per-oz
```

`--confirm-usd-per-oz` is your explicit confirmation that this symbol's quoted price
is USD per troy ounce, after checking your broker's contract specification. Without
it USD/oz spread stays null. Point spread uses the actual metadata `point`. The
first fresh, valid quote should yield `quote_status: VALID` and account environment
`REAL`. `STALE`, `CLOCK_SKEW`, or `INVALID_OR_MISSING` is not a valid live milestone.
Doctor prints no account identifier, terminal path or price. If no quote is fresh,
for example during a closed market, report that outcome truthfully and try later.

## Bounded capture

After confirming terminal, environment, symbol and quote unit locally, start one
120-second read-only run. Use a new name on each run:

```powershell
uv run --frozen --extra mt5 python -m xbsis mt5-capture --terminal-path 'C:\path\to\terminal64.exe' --symbol 'XAUUSD' --confirm-usd-per-oz --confirm-real --run-name 'local-001'
```

Default duration is 120 seconds and default poll interval is 250 ms. `--duration`
accepts >0 up to 120 seconds; `--interval-ms` accepts 50–10000. The loop uses a
monotonic deadline but cannot impose a hard upper bound on a blocked external SDK
call. The process rechecks the REAL enum, and refuses DEMO/UNKNOWN capture.

Outputs are created once under ignored `data/mt5/local-001/`:

- `observations.duckdb` contains private, unencrypted raw snapshots, source and
  receive clocks, metadata, quality flags and Decimal spreads. Never upload it.
- `summary.json` contains sanitized counts, status, REAL/DEMO label and polling
  parameters; it excludes quotes, symbols, paths, timestamps and account identifiers.

`NO_NEW_QUOTES` means no fresh distinct follow-up snapshot was observed; the initial
snapshot alone does not prove a new event. `STALE` means no valid fresh quote and
at least one stale snapshot were observed. `OK` means a fresh change was observed, not that
all market ticks were captured. `DUPLICATE` labels repeated source time/price/flags;
each polling observation remains recorded. Repeated snapshots are not new events.
SDK binary floats are converted with `str(float)`; this preserves the SDK value's
round-trip text, not original broker wire bytes or precision.

## Local inspection and sanitized summary

To inspect the last record **only on your Windows machine**, run from the project root:

```powershell
uv run --frozen --extra mt5 python -c "from pathlib import Path; from xbsis.storage import ObservationStore; p=Path('data/mt5/local-001/observations.duckdb'); s=ObservationStore(p); r=s.records()[-1]; print('bid=',r.quote.raw.bid,'ask=',r.quote.raw.ask,'source_ms=',r.quote.raw.source_time_ms,'spread_usd_per_oz=',r.spread.spread_usd_per_oz,'points=',r.spread.spread_points,'flags=',r.spread.data_quality_flags); s.close()"
Get-Content 'data\mt5\local-001\summary.json'
```

Compare the displayed Bid/Ask and ask-minus-bid spread locally with the same symbol
in MT5, allowing for the fact that the terminal may have moved since the snapshot.
Do not send console output containing quotes to GitHub or cloud. The already-created
`summary.json` is the sanitized diagnostic export; review it locally before sharing.
It is not proof of complete tick capture or precise latency.

The preflight verifies that an exact `terminal64.exe` process is running at the
specified path and checks the connected terminal installation path. MT5's SDK may
launch/reconnect a terminal as part of `initialize`; process state can change between
checks, and SDK behavior cannot be proven from cloud fakes. No login, password,
account number, server or portable flag is passed, and no account-switching call is
made. Multiple terminals using the same executable cannot be distinguished without
reading account identifiers, so personally confirm the selected terminal locally.
If the terminal is stopped or CIM cannot inspect its process path, preflight fails. The SDK's `trade_mode` enum is read only to classify REAL/DEMO; the account
object is discarded without logging or persisting other fields. Disconnects, market
closure, wrong symbol and source/local clock differences must be checked locally.
