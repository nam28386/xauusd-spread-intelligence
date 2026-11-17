# Phase 01 engineering evidence

Historical report: the owner subsequently approved public visibility and Phase 01
commit f01220dcb11c800143051f14e50584b01f15c9df was published to main. The original
observations below describe Phase 01 before that publication.

Research ID: XBSIS-P01. Modes: greenfield scaffold and deterministic replay.
Scientific status: SOFTWARE_CONTRACT_ONLY, no market hypothesis or live observation.
Baseline: empty selected repository, no commits/files/remote refs/main; feature branch
`feat/phase-01-core`. No other repository was modified.

## Files and architecture

All project files are new: AGENTS.md; README.md; .gitignore; .python-version;
pyproject.toml; uv.lock; .github/workflows/ci.yml; the seven documents under docs/;
source under src/xbsis/ (models, normalization, quality, spread, pipeline, storage,
API, CLI, base/mock/Windows contracts and packaged fixtures); tests/; scripts/.
No frontend, live collector or actual SDK binding exists.

`BrokerAdapter -> RawQuote -> Normalization -> DataQuality -> SpreadEngine -> Observation`
feeds explicit local storage or a read-only synthetic API. Source/receive/process
clocks, raw prices, metadata and semantic versions are retained. Display time is a
future separate UI field. Future analytics, comparison and execution are not inferred.

## Commands actually executed

From /workspace/xauusd-spread-intelligence on Linux x86_64, CPython 3.12.14, uv 0.13.6:

```sh
git status --short --branch
git ls-files
git ls-remote origin
git switch -c feat/phase-01-core
uv lock
uv sync --frozen --extra dev
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev ruff format --check .
uv run --frozen --extra dev pytest
uv run --frozen python scripts/audit_repository.py
uv run --frozen python scripts/smoke_api.py
uv run --frozen python -m xbsis replay
uv build --out-dir /tmp/xbsis-phase01-dist-final
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/xbsis-phase01-runtime-requirements.txt
uv venv --python 3.12 /tmp/xbsis-phase01-wheel-env
uv pip sync --python /tmp/xbsis-phase01-wheel-env/bin/python --require-hashes /tmp/xbsis-phase01-runtime-requirements.txt
uv pip install --python /tmp/xbsis-phase01-wheel-env/bin/python --no-deps /tmp/xbsis-phase01-dist-final/xbsis-0.1.0-py3-none-any.whl
```

uv commands used writable `UV_CACHE_DIR=/workspace/.cache/uv`. Ruff auto-fixes and
formatting were run during development. The installed wheel was then run from /tmp:
`/tmp/xbsis-phase01-wheel-env/bin/python -m xbsis replay`, explicit local storage
round-trip/export assertions, SDK/dev-package absence assertions, and the smoke API
script using that same wheel interpreter. It imported the installed package rather
than the editable checkout. Runtime-only environment: 15 dependencies plus XBSIS;
neither MetaTrader5 nor pytest installed.

Read-only GitHub inspection attempted:
`gh api repos/nam28386/xauusd-spread-intelligence --jq '{full_name,private,visibility,default_branch,permissions}'`.
Result: Forbidden. A curl status-only check confirmed the CONNECT proxy returned 403
for api.github.com. The runtime's enforced allowlist lacked that hostname. Native
Git reads succeeded but returned no remote refs; this proves neither private
visibility nor API/push authorization. No token value was inspected or requested.

## Executed tests and outcomes

| Check | Result | Evidence / failure significance |
|---|---|---|
| CLI | 6 passed | loopback-only invocation, invalid args, no-overwrite export |
| Contracts | 27 passed | raw precision, immutable/extra rejection, strict clocks, exact JSON |
| Integration | 5 passed | golden replay, hash corruption, DuckDB/Parquet order/precision, API, CLI determinism |
| Safety | 3 passed | no SDK/prohibited call paths, no SDK installed/imported, sensitive paths ignored |
| Spread/normalization | 32 passed | hand-derived values, invalid/null/crossed, units, varying point size, invariants, Decimal context/recurrence |
| Temporal | 14 passed | clock units/order, staleness boundary, processing delay, duplicates, high-water marks, stream isolation, no fill |
| Windows contract | 6 passed on Linux fakes | snapshot mapping, missing tick, credential/session fields rejected |
| **Total pytest** | **93 passed, 0 failed, 0 skipped** | final full run, no warnings |
| Ruff lint / formatting | PASS | all source, scripts and tests |
| Repository audit | PASS | intended/tracked files, no prohibited artifacts or common secret patterns |
| Local HTTP smoke | PASS | real CLI/server + health/spread/duplicate functional requests; server stopped |
| sdist/wheel + runtime-only wheel | PASS | build, packaged fixture hash, replay, storage, API and SDK absence |
| GitHub-hosted Actions | UNRUN | workflow prepared locally; no remote upload |
| Actual Windows / MT5 | UNRUN | no terminal, account or SDK was accessed |

Earlier lint/style findings were corrected. Earlier 80/83-test runs passed with an
HTTPX deprecation warning; inspected Starlette's supported import path, changed the
dev dependency to its supported httpx2 client, regenerated the lock and reran the
expanded suite successfully without warnings. The isolated /tmp install reported a
cross-filesystem hardlink fallback to copying; installation succeeded with hash
verification. No core test failure was observed.

Golden synthetic replay: 9 observations. Repeated source/wheel runs produced:

- fixture SHA-256: `7c846f644c1921bfd89a9c105a979d021ebac48ba35b66bfb5ea124de10f62b2`
- observation JSON SHA-256: `771959c849e87deccbde091cf7f0f829cc5497b159a0793d9e7cc082c4928a45`

These hashes prove repeatability for the locked inputs, not data authenticity or live
connectivity. Parquet validation compares semantic rows, not platform-wide bitwise bytes.

## Security findings

No account/password/session/terminal data was obtained. No live broker request,
order/position API, SDK import, raw-data upload, public server bind, force-add,
visibility change, other-repository modification or merge was performed. Only
explicit synthetic fixtures are intended for Git. SQL values/paths use bound
parameters; nanoseconds and decimals are not cast to DOUBLE. Scripts use fixed
subprocess arguments without a shell. CI permissions are read-only and no artifacts
are uploaded. Manual source/diff review complements AST, ignore and pattern audits.

No common secret pattern or prohibited local-data artifact was found. This is not
a comprehensive secret or dependency-vulnerability certification. At the time of
this report, GitHub API access was blocked and no push had been attempted. The owner
subsequently approved public visibility and the baseline was published to main.

## Engineering gates and limitations

| Gate | Status | Boundary |
|---|---|---|
| Provenance | PASS for fixtures | manifest hash, immutable raw values, versions, explicit synthetic source |
| Temporal | PASS for defined software contract | clock-order/staleness/missingness tests; no real clock synchronization claim |
| Split | not applicable | no training, prediction, labels or evaluation splits |
| Reproduction | PASS current Linux | frozen dependencies, repeated source + installed-wheel results |
| Artifact | PASS local | append order, content IDs, exact payload round trips; not remote publication |
| Scientific handoff | PASS limited scope | no upgrade to empirical, economic or live execution validity |

Storage is single-writer, exact-text payload oriented, unencrypted and not a typed
analytics warehouse. Metadata source/session/time association is caller-owned; only
synthetic metadata is used here. Duplicate detection is adjacent per stream, not a
global history index. Sequence gap/reset and tick-grid rules are deferred. Source
clock offsets can affect stale/future diagnostics; they do not prove latency. No
commission/slippage, forward fill or universal pip size is inferred. Runtime-only
wheel was validated on Linux, not a second restored cloud task or Windows.

## Windows and GitHub handoff

Windows is ready for **offline** Python 3.12 dependency installation, fake-port
contract tests, synthetic replay/storage and local API validation using
WINDOWS_RUNBOOK.md. Actual SDK binding/live collection requires a separate reviewed
phase; it is not part of this delivery.

At the time of this report, the remote had no main branch and the GitHub API was
blocked; the change existed only in a local feature-branch commit. The owner later
approved public visibility and authorized publication. Git transport confirmed main
at f01220dcb11c800143051f14e50584b01f15c9df. API access and hosted CI status have
not been verified.

The onboarding configuration draft saved install_script, start_skill and the custom
api.github.com domain addition, preserving package-manager presets. Saving did not
apply networking, publish a snapshot or prove new-task restoration. Review/save the
draft in environment settings, then publish when appropriate. Do not assume live
processes or unpublished local commits survive a fresh task.
