# Analytics methodology

Version `spread-statistics-v1` uses only observations with confirmed USD per troy
ounce metadata and a non-null spread, excluding stale, crossed, missing, invalid,
unsupported, missing/future source time and time-reversal flags. Duplicate
snapshots may still be valid, and are counted separately. Rates divide by snapshots
in the selected window, so flags can overlap. Source time is a broker quote time,
not exchange time; receive time is a local clock, not a latency measurement.

Mean, min/max and median/p95/p99 are snapshot-weighted. Quantiles linearly
interpolate at `(n-1)*p` in sorted Decimal values using 80-digit context. For each
valid snapshot at receive time t, valid duration is `[max(t,start),
min(next_receive,t+freshness,end))`; invalid or missing next snapshots terminate
continuity. The final interval is capped by the sealed data boundary. Duration
weighted mean is sum(spread * valid duration) / sum(valid duration); coverage is
valid duration / window duration. Zero duration gives null. Snapshot inclusion is
inclusive at both window endpoints. Reverse receive times break continuity and are
invalid. Clock changes and polling gaps limit interpretation.

A widening starts at a valid spread >= the user's explicit threshold. It ends at
the first subsequent valid spread below threshold; duration is end minus start,
recovery duration is end minus the last observed above-threshold time. Freshness
expiry, invalidity or window end censors the event; unobserved transitions are not
invented. At most 1,000 event details are returned with a truncation indicator.
Change intensity counts changed valid `(source_time,bid,ask,flags)` snapshots per
valid covered second; this is polling intensity, not the tick arrival rate.

`receive-asof-v1` evaluates each left receive time against the most recent right
observation at or before it. The right observation must be valid and no older than
the selected tolerance; an invalid latest observation blocks fill. Both sources
must confirm USD/oz. Coverage is matched / left evaluations; differences are left
minus right spread, with mean and absolute dispersion. Different point sizes,
metadata, source labels and REAL/DEMO remain independent. No interpolation or
future quote is used. Same-host clocks can jump and do not prove simultaneity.
Observed spreads exclude commission, slippage, fill probability and size, so they
are not execution costs or evidence of an executable arbitrage.
