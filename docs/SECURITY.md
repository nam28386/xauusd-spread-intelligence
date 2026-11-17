# Security and privacy

## Non-negotiable boundaries

Read-only observation only. There is no execution, order, modification, position
management or broker authentication code. Cloud tasks must never contact the user's
local terminal or real trading account. Do not request account identifiers,
passwords/investor passwords, session files, cookies or trading tokens. The Windows
connector may read only `trade_mode` from SDK account metadata and must immediately
discard the object. Do not read account identifiers, balance,
server, history, orders or positions.

The repository is public by explicit owner approval. Audit each commit for secrets,
account information, real quotes and terminal files before publication. Never merge
main automatically, change other repositories or change visibility without a
separately authorized workflow. GitHub connection credentials are platform-managed; never extract, print or commit their values.

## Data handling

Commit only source, docs, locked dependency metadata and explicitly synthetic
fixtures. No actual account data, quotes, terminal logs, sessions or secrets may be
uploaded to GitHub, CI artifacts, issues or PR bodies. `.gitignore` excludes local
datasets, output directories, credentials, logs, databases, Parquet and MT5 files.
Ignore rules are convenience, not access control: `git add -f` can bypass them.

Use local paths under ignored `data/` (or outside the checkout). Storage is not
encrypted; protect it with OS permissions and disk encryption. No automatic sync,
cloud storage, telemetry or data upload is implemented. Do not put data in folders
synced to consumer cloud tools. Do not log quote payloads, SDK errors or environment
contents. Synthetic replay prints hashes; local MT5 capture prints sanitized counts,
and doctor prints the selected symbol, user-supplied aliases, environment, quality
status and instrument metadata. Those aliases do not verify broker identity. API
access logging is disabled.

## Local API threat boundary

Use `python -m xbsis serve`: fixed 127.0.0.1, no host option, GET-only synthetic data,
TrustedHost allowlist, no CORS, no broker/ingestion/config/file endpoints. Do not
expose it through tunnels, reverse proxies or public uvicorn binds. Localhost is not
an authorization boundary against malicious software on the same machine. There is
no application auth; the Phase 01 API must not be repurposed for live data exposure.
OpenAPI docs can load third-party UI assets in a browser; deterministic tests use
local JSON endpoints and require no external browser assets.

## Dependencies and CI

Python 3.12, uv.lock hashes, frozen install, isolated .venv. MetaTrader5 is an optional
extra with Windows AMD64 markers, imported only after local Windows checks and an
explicit doctor/capture command. Linux CI installs only `dev`, verifies the SDK is
absent, runs FakeMT5 tests and uploads no data.
GitHub Actions use pinned action SHAs, read-only repository permissions and no
persisted checkout credentials. Dependabot/security alerts and human dependency
review are still needed; no vulnerability-database audit has been claimed.

## Verification and reporting

`tests/test_safety.py` checks SDK imports and prohibited call families with AST;
`scripts/audit_repository.py` scans intended/tracked files for prohibited artifact
paths/types and common secret patterns without printing contents. Unit tests reject
extra credential fields. Review the staged diff manually before every commit/push.
These checks cannot establish absence of every secret, malicious dependency, real
quote or future behavioral bug. Treat unexpected findings as blockers, remove the
cause and re-run checks. If an actual credential ever reaches Git, revoke it through
the provider and arrange reviewed history remediation; do not paste it into chat.
