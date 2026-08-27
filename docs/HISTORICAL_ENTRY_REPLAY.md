# Continuous depth and historical entry replay

Level two (L2) data describes aggregated order-book quantities, not individual exchange queues.
The historical model remains a conservative first-in, first-out queue approximation.
It has no exchange credentials or order interface.

## Capture boundaries

The continuous recorder keeps one WebSocket and one reconstructed book across file rotation.
Calibration and delayed diagnostic imports run in a separate, bounded child process.
The existing single-file recorder remains available for separately authorized validation drills.

Each completed segment has a source hash, session identifier, segment index, and previous source hash.
Its seed contains the carried book and depth sequence identifier.
The reader verifies carried prices, quantities, timestamps, and aggregate-trade sequence identifiers.
A reconnect creates another session.
The reader never joins separate sessions or old files across an unproven boundary.

Sequence failures stop capture and leave unfinished files unpublished.
Network outages, exchange disconnects, storage exhaustion, and process restarts can still create gaps.
File rotation alone does not close the connection.

The service accepts one symbol per process.
Additional capture symbols require separate services and output directories.
The capture list never expands execution scope.

## Calibration coverage

The worker scans completed sidecars, including archives that lack older calibration reports.
It creates one immutable calibration report per source archive.
It never overwrites an existing report.
The worker keeps only one calibration or diagnostic-import child active.
Each child has a five-minute time limit.

`calibration_inventory.json` distinguishes unprocessed archives from absent volatility regimes.
`BACKLOG_NOT_CALIBRATED` means that unprocessed sources can still contain the missing regime.
`NOT_OBSERVED` means that current valid reports do not contain that regime.
Neither status proves that the underlying market never experienced high volatility.

The high threshold remains two basis points.
The low threshold remains one-half basis point.
Public receive latency never proves real order execution.
This inventory does not replace replay readiness or order validation.

## Historical selection inputs

The replay request contains exactly these fields:

| Field | Required content |
| --- | --- |
| `policy` | Every field in `HistoricalPolicy`, including explicit timing and capacity limits |
| `context` | Chronological historical filter, fee, classifier, regime, and PANIC attestations |
| `archives` | Ordered objects with `path` and pinned `sha256` fields |
| `start_ms` | First permitted entry time |
| `entry_end_ms` | Last permitted entry-window boundary |
| `end_ms` | End of the terminal observation tail |
| `cutoff_ms` | Immutable selection cutoff |

Financial inputs use decimal strings.
Timestamps use integer milliseconds.
Context rows require audited source hashes, observation times, and expiry times.
They require the classifier fingerprint that the policy fixes.
Current exchange filters or fees cannot replace missing historical inputs.
The tool does not manufacture missing context or infer regimes from future outcomes.

The policy fixes gap, target, stop, quantity budget, fees through context, cadence, latency, and permitted regimes.
The model uses the current book midpoint as its reference price.
It rounds entry quantities and prices with the historical exchange filters.
Passive prices outside the observed book block the replay.
The output includes model source hashes and the policy fingerprint.

The signal uses only the preceding observation window.
It combines price movement, signed trade quantity, and book order-flow imbalance.
The signal does not use a future fill timestamp.

Baseline and veto policies each own one independent position slot.
An accepted cancel remains exposed until its fixed arrival time.
Trades win ambiguous cancellation-time ties; submission-time ties do not earn fills.
Partial fills retain their quantity and protection requirement.
A successful zero-fill cancel permits another opportunity at the next fixed cadence boundary.
New opportunities come from market history, not a list of previously recorded fills.

The entry window ends before the full holding-period observation tail.
This prevents selection of only quickly completed trades.
Missing context, sequence gaps, insufficient warmup, and incomplete observation tails block the report.
Unresolved positions remain censored rather than receiving invented exit prices.

## Run an offline replay

CAUTION: the request requires audited historical context and exact source hashes.
The following command neither creates orders nor changes a canary.

```bash
PYTHONPATH=. .venv/bin/python -m bin.replay_historical_entries \
  --request /absolute/path/selection-request.json \
  --output /absolute/path/selection-replay.json
```

`COMPLETE_SELECTION_REPLAY` means the historical replay completed without missing evidence.
It does not approve a candidate, prove profitability, or authorize promotion.
Independent time-block selection, runtime parity, and independent confirmation remain separate requirements.
An existing output file blocks publication rather than being replaced.

## Storage contract

| Record | Classification | Growth bound | Retention and archive dependency |
| --- | --- | --- | --- |
| Public segments and sidecars | Authoritative source evidence | Directory byte cap and 10,000 segment limit | Indefinite until verified encrypted archival and reference review |
| Calibration reports | Derived evidence | One report per source segment | Same retention as the retained source |
| Calibration inventory | Disposable status | One bounded replacement file | Rebuilt by the worker; no archive dependency |
| Historical replay reports | Derived selection evidence | 10,000 attempts per policy and immutable output | Retain with policy, context, and source archives |
| Unfinished temporary files | Disposable incomplete capture | Shared directory byte cap | Manual review; never selected as evidence |

The worker checks the backlog every thirty seconds when idle.
The recorder checks storage capacity at every rotation and before each write.
The default directory limit is eight gibibytes.
The capture service no longer deletes files solely because of their age.
Pending diagnostics, selection references, and validation evidence can depend on older files.
Storage exhaustion stops capture instead of removing protected evidence.
Archive removal requires a recent verified encrypted backup and an explicit reference review.
No automated archive-removal job is introduced by this change.
