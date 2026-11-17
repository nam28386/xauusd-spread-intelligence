# v1 release evidence

This repository contains a synthetic cloud test path and a separate local Windows
MT5 path. The release status must be established from the delivery's actual command
results and hosted CI runs; a workflow configuration is not a passing CI run.
WINDOWS_FAKE_VERIFIED requires a successful GitHub-hosted Windows FakeSDK job.
LOCAL_EXNESS_UNVERIFIED, LOCAL_PEPPERSTONE_UNVERIFIED and
LOCAL_MULTI_BROKER_UNVERIFIED remain unchanged until local acceptance is performed.
Do not claim PRODUCTION_READY without actual evidence and review.

FACT: quote records preserve source and receive timestamps, user-supplied source
labels and metadata; aliases do not authenticate brokers. MEASUREMENT: descriptive
statistics and comparisons are computed from recorded, bounded observations.
INFERENCE: differences may reflect account, platform or timing effects.
HYPOTHESIS: any causal explanation requires independent testing. UNKNOWN: actual
execution costs, missed ticks and the outcome of unperformed Windows tests.

Known boundaries include local clock jumps, poll sampling, unsealed data after
forced termination, bounded local storage, no automatic account-change detection
for a same-mode switch, and data exposure to untrusted same-user processes.
See [methodology](ANALYTICS_METHODOLOGY.md) and [local acceptance](LOCAL_ACCEPTANCE.md).
