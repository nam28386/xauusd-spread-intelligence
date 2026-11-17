# Local research user guide

Install Python 3.12 and uv 0.13.6, then run `.\scripts\install.ps1` and
`.\scripts\start.ps1 -Mode mock` in PowerShell. Open
`http://127.0.0.1:8765/live/`. Synthetic REAL/DEMO labels are fixtures.

Overview shows current source health; Realtime plots the selected sources and
bounded visible window. History selects a recorded session, sealed segment and
optional receive-time bounds, then pages through original bid/ask and spreads.
Analytics requires an explicit USD/oz widening threshold and reports sample and
duration metrics; Download writes an aggregate JSON through the browser. Compare
selects two different sources, an age tolerance and threshold; its two quality
summaries and matched spread differences are descriptive. System shows worker
and queue status. A session can be incomplete, interrupted, or legacy with unknown
completeness. An empty active segment is not evidence of a completed capture.

For Windows real terminals follow [WINDOWS_RUNBOOK.md](WINDOWS_RUNBOOK.md) and
[LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md). The browser download location is local
sensitive storage; review before sharing. The server continues after collection;
Ctrl+C requests worker shutdown. No app page submits trades.
