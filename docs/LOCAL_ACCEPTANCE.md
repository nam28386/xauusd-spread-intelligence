# Local Windows acceptance — evidence required

These steps must be performed on the user's own Windows computer. Never send raw
quotes, local paths, terminal output, credentials or account identifiers to cloud,
GitHub or CI. The [Windows runbook](WINDOWS_RUNBOOK.md) provides commands. A passed
FakeSDK test is not live acceptance. Record only reviewed, non-sensitive pass/fail
results locally and keep the following statuses UNVERIFIED until actually observed.

1. Install Python 3.12, uv 0.13.6 and dependencies using
   `.\scripts\install.ps1 -IncludeMT5`; run `uv run --frozen --no-sync pytest`.
2. Manually sign in to a dedicated Exness terminal. Run the Exness REAL doctor in
   the runbook and independently confirm environment, selected symbol, point size,
   contract metadata and USD/oz unit.
3. Run the separate bounded Exness capture command and inspect locally that fresh
   observations and source/receive timestamps are sensible.
4. Configure one Exness source under ignored `data/config` and start MT5 dashboard
   with explicit `-ConfirmLiveReadonly`; compare its bid/ask locally to the terminal.
5. Stop gracefully; inspect the source session, sealed history, metadata, quality,
   and aggregate report locally. Confirm no data was uploaded.
6. Install a genuinely separate second terminal, sign in manually and verify its
   own terminal path, symbol and specification.
7. Run Pepperstone DEMO doctor and separate capture; confirm DEMO and valid quotes.
8. Configure both independent source entries, start the two-worker dashboard and
   verify both statuses, labels, updates and distinct local session directories.
9. Choose both sealed sessions in Compare, specify threshold/tolerance, inspect
   alignment, quality and coverage. REAL and DEMO are not execution-equivalent.
10. Disconnect one terminal, inspect its state and gaps, then Ctrl+C; check that
    workers exit and interrupted/complete states and sealed data remain truthful.
11. Generate and review the aggregate JSON locally, preserving revision and run IDs.
    Keep private artifacts outside synced folders; delete only by deliberate local
    decision. Repeat with realistic duration only after short tests pass.

LOCAL_EXNESS_UNVERIFIED; LOCAL_PEPPERSTONE_UNVERIFIED;
LOCAL_MULTI_BROKER_UNVERIFIED. Windows named mutex and SDK process isolation require
actual local confirmation. Do not claim PRODUCTION_READY without evidence and review.
