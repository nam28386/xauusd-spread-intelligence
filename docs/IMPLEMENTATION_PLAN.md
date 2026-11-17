# Phase 01 implementation and review plan

## Baseline

At task inspection the selected checkout was empty: no files, local commits, remote
refs or remote main. The supplied origin is nam28386/xauusd-spread-intelligence.
No user edits existed. Python 3.12.14 and uv 0.13.6 were available on Linux x86_64.
Work is isolated on feat/phase-01-core. Existing account/MT5 state was never inspected.

## Frozen scope

Research ID XBSIS-P01; hypothesis ID null; scientific status SOFTWARE_CONTRACT_ONLY.
Unit of observation: one synthetic XAUUSD quote with independent clocks. Venue,
broker metadata and live timestamp behavior are UNKNOWN. No predictive estimand,
labels, split, strategy, execution-cost model or empirical market result is defined.
Those concepts are not applicable to this deterministic software contract.

| Work | Phase 01 completion criterion |
|---|---|
| A/B | inspect baseline, feature branch, contributor safety/review contract |
| C | product, architecture, data/security contracts, Windows runbook and plan |
| D/E | immutable models, explicit normalization, quality, Decimal spreads, mock/hash manifest |
| F | hand-specified golden values; schema, unit, invariant, temporal and integration tests |
| G/H | uv.lock, optional platform SDK, Linux-only deterministic CI, no SDK installation/import |
| I/J | ignore/audit local outputs and credentials; pure Windows port plus fake tests |
| Additional core boundaries | exact-text local DuckDB/Parquet round trips and GET-only mock API |

## Required checks

Frozen dependency installation; Ruff lint/format; complete nonzero pytest run;
repeated replay and stable hashes; no missing-value fill or clock overwrite; per-stream
quality isolation; idempotent persistence with append order; exact Decimal/ns JSON and
Parquet round trips; real local HTTP smoke; package build/resource verification;
SDK absence and no prohibited call/import paths; intended-file secret/artifact audit.
Windows and GitHub-hosted CI are separate follow-ups, never inferred from Linux.

## Review and Git handoff

Review full diff, formulas/units, staleness clock assumptions, schema versions,
packaged synthetic hash and raw provenance. Commit only explicit source/docs/test
paths on the feature branch. The owner has approved public repository visibility.
Create a Draft PR only if GitHub access is allowed and a legitimate main base exists.
An empty repository cannot have a PR against a nonexistent main; do not invent the
base, seed main or auto-merge. Report exact blockers and retain the local commit.

## Deferred, requires another request

Actual Windows SDK binding and local validation; live collection; metadata capture;
reconnect/retention/migrations; time-aware analytical schemas; multi-broker comparison;
React/TypeScript/Plotly; empirical research. Nothing here authorizes those phases.

## Current v1 implementation and evidence gates

Sealed session storage, bounded local history, descriptive analytics, comparison,
local dashboard, mock browser checks and Windows FakeSDK CI configuration are
implemented. A configured CI job is not evidence of a successful hosted run.
Actual Exness REAL, Pepperstone DEMO and simultaneous multi-terminal acceptance
remain separate local evidence gates; see [local acceptance](LOCAL_ACCEPTANCE.md).
No automated execution, live cloud connection or automatic merge is in scope.
