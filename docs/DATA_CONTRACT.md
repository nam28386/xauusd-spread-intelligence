# Data contract v1

## RawQuote (immutable)

All fields are required, including explicit nullable fields. Unknown extra fields
are rejected. Identifiers are 1–128 ASCII letters/digits/underscore/dot/colon/hyphen;
use non-sensitive aliases, never an account number or session identifier.

| Field | Type / semantics |
|---|---|
| source_id | stable source alias |
| broker_id | non-sensitive broker alias |
| server_id | non-sensitive logical server alias |
| account_environment | REAL / DEMO / UNKNOWN; never infer from connectivity |
| symbol_raw | exact source symbol within the identifier grammar |
| symbol_canonical | source assertion or null; validated against explicit mapping |
| bid, ask | original string (max 128 chars) or null; floats/numbers rejected |
| source_time_ms | nonnegative integer UTC Unix milliseconds or null, broker-source clock |
| received_time_ns | nonnegative integer UTC Unix nanoseconds; JSON decimal string |
| flags | opaque nonnegative integer source bitmask, preserved without invented meanings |
| ingestion_mode | MOCK_REPLAY / MT5_LOCAL; the latter is a contract label, not evidence of connectivity |
| source_sequence_or_null | nonnegative integer source sequence or null; never fabricate one |

Prices remain verbatim even if malformed, negative, zero, NaN or infinite. Only
normalization parses a valid positive decimal grammar into a Decimal. No whitespace,
underscores, Unicode digits or nonfinite values are normalized. v1 bounds normalized
prices and non-null numeric metadata to at most 38 coefficient digits and adjusted
exponent -18..18. Out-of-range prices are flagged invalid; originals remain intact.
Raw source bytes/SDK binary floats cannot be recovered from text; see Windows runbook.

## InstrumentMetadata

`symbol_canonical=XAUUSD`, `point_size`, `tick_size`, `digits`, `contract_size`,
`quote_currency`, `metadata_source`, `metadata_version`; additionally `price_unit`
explicitly records USD_PER_TROY_OUNCE or UNKNOWN. Numeric metadata may be null;
non-null decimal fields require positive decimal text/Decimal, and digits is an
integer 0..18. Currency is USD or UNKNOWN for this XAUUSD-specific v1 schema.
Metadata must refer to the same symbol/source session and be acquired no later than
processing; the caller owns that association. This phase uses synthetic metadata
only and makes no historical point-in-time metadata claim.

`digits` is display metadata, never a rounding instruction. `tick_size` is not
`point_size`; do not assume equivalence. `contract_size` is preserved, not used in
per-ounce price spread. No pip field or universal XAUUSD pip conversion exists.
Missing metadata stays null; no broker specification is guessed.

## NormalizedQuote and Observation

NormalizedQuote nests the unchanged RawQuote, parsed nullable bid/ask, the resolved
nullable canonical symbol, `normalization_version=normalization-v1` and explicit
`mapping_version`. Only an explicit mapping to XAUUSD is recognized; a contradictory
source assertion or absent mapping produces UNSUPPORTED_SYMBOL.
Observation nests that quote, the metadata snapshot, DerivedSpread, and independent
`processing_time_ns`, with `schema_version=observation-v1`. Models reject extras,
nonfinite derived numbers, float price inputs and processing before receive.

## DerivedSpread (`metric_version=spread-v1`)

Let D = ask - bid. With positive valid sides, ask >= bid and supported mapping:

- `spread_usd_per_oz = D` only when metadata explicitly confirms USD_PER_TROY_OUNCE
  and currency USD; otherwise null.
- `spread_points = D / point_size` only when point_size is known; otherwise null.
- Crossed/invalid/missing/unsupported-symbol observations have both metrics null.
- Missing metadata nulls both metrics. Unknown price unit nulls USD only; points
  can still be known. No contract-size scaling, pip, commission or slippage inference.

Arithmetic uses a local Decimal context (80 significant digits, ROUND_HALF_EVEN).
The bounded v1 subtraction is exact; a recurring point ratio may round to 80 digits.
It never inherits a caller's rounding context. No float round trip is used.
Stale, duplicate, missing-source-time and clock-anomaly quotes can retain diagnostic
metrics; consumers must inspect flags, not treat a non-null value as a fresh quote.

## Quality and temporal rules

Flags are sorted, unique enum values separate from opaque source flags:

| Flag | Condition |
|---|---|
| MISSING_BID / MISSING_ASK | raw side is null |
| INVALID_BID / INVALID_ASK | raw side exists but cannot normalize |
| CROSSED | both valid sides, ask < bid |
| STALE | processing_ns - source_ms*1,000,000 > threshold; default 5 seconds |
| DUPLICATE | adjacent observation in the same stream has equal source time, sequence, raw sides and source flags, with at least time or sequence known |
| SOURCE_OUT_OF_ORDER | source ms below previous stream high-water mark |
| RECEIVE_TIME_REVERSED | local receive ns below previous stream high-water mark |
| FUTURE_SOURCE_TIME | source ms*1,000,000 > local receive ns; could be clock offset |
| MISSING_SOURCE_TIME | source ms null; source age is unknown, no stale assertion |
| UNSUPPORTED_SYMBOL | missing/contradictory explicit mapping |
| METADATA_MISSING | metadata is null |
| UNKNOWN_PRICE_UNIT | metadata cannot establish USD per troy ounce |

Duplicate detection is adjacent-per-stream, not global history or all sequence reuse.
No records are dropped or forward-filled. Sequence ordering/gaps/resets and tick-grid
validation are not inferred in this phase. Tick size is retained for later validation.

Clocks must stay distinct:
1. **Source:** broker quote clock in ms, never described as exchange time.
2. **Receive:** local host wall-clock acquisition time in ns, never replaced by source time.
3. **Processing:** local host wall-clock processing time in ns, explicit in replay,
   must be >= receive; a clock reversal rejects processing rather than changing raw data.
4. **Display:** conversion/rendering time, absent in Phase 01; a future UI must label
   timezone and record display time separately without changing stored clocks.

All epoch values mean UTC. Source/local differences are diagnostics, not proven
one-way latency or clock synchronization. No missing timestamp is fabricated. JSON
nanosecond clocks are decimal strings to preserve precision in future TypeScript;
Python decodes them as integers. Source milliseconds remain JSON integers.

## Storage and fixtures

DuckDB stores `(ordinal BIGINT, observation_id VARCHAR PRIMARY KEY, payload VARCHAR)`;
Parquet exports those fields. Payload is validated Observation JSON with decimal and
nanosecond strings, deliberately avoiding implicit DOUBLE casts or fixed-scale loss.
A caller parses/validates payload before analytical use. Typed analytics tables are
future work. SHA-256 identifies full payload including versions, metadata and clocks;
this is content integrity, not proof of authenticity.

Packaged quotes.json contains nine labeled synthetic events; manifest.json includes
its hash, versions, origin and scientific status. No broker data, labels, trading
outcomes, train/test splits or market inference exists. Golden expected results are
hand-specified in tests, not regenerated from the implementation under test.
