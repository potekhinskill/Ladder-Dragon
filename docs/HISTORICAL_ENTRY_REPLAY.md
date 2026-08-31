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
Binance limits one WebSocket connection to 24 hours.
The recorder commits the last valid segment when it receives `serverShutdown`.

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
The worker keeps only one offline child active.
Calibration and diagnostic imports have a five-minute time limit.
One batched historical block has a 30-minute time limit.

`calibration_inventory.json` distinguishes unprocessed archives from absent volatility regimes.
`BACKLOG_NOT_CALIBRATED` means that unprocessed sources can still contain the missing regime.
`NOT_OBSERVED` means that current valid reports do not contain that regime.
Neither status proves that the underlying market never experienced high volatility.

The version one policy keeps fixed thresholds of 0.5 and 2 basis points.
The version two policy uses calibration event-move P95 values from a selection cohort.
It detects zero-inflated cohorts and splits their positive tail.
Preflight requires at least 20 selection reports in each future bucket.
An immutable selection policy defines empirical thresholds for a later confirmation cohort.
Its selection reports must end before the fixed cutoff.
Its confirmation archives must start after the cutoff and use different source hashes.
Public receive latency never proves real order execution.
This inventory does not replace replay readiness or order validation.

## Historical selection inputs

The provider-bounded replay request contains exactly these top-level fields:

| Field | Required content |
| --- | --- |
| `request_schema_version` | Integer `2` |
| `cohort_contract` | `provider_bounded_executable_paths_v2` |
| `stability_block_index` | Chronological block index from zero through three |
| `policy` | Every field in `HistoricalPolicy`, including explicit timing and capacity limits |
| `paths` | Three chronological source-disjoint path objects |

Each path contains `archives`, `start_ms`, `entry_end_ms`, `end_ms`, and `cutoff_ms`.
Each archive object contains one path and one pinned SHA-256 value.

Financial inputs use decimal strings.
Timestamps use integer milliseconds.
Context rows require audited source hashes, observation times, and expiry times.
They require the classifier fingerprint that the policy fixes.
Current exchange filters or fees cannot replace missing historical inputs.
The tool does not manufacture missing context or infer regimes from future outcomes.

## Source-owned context journal

The supervisor can record context independently of candidate plans, including during persistent HALT.
`BOT_HISTORICAL_CONTEXT_ENABLED=1` enables this observer.
`BOT_HISTORICAL_CONTEXT_SYMBOLS=SOLUSDT` sets its default scope.
The service and example configuration enable this SOL observer.
The library default remains disabled.
This list never expands execution scope.

The journal uses `historical_context.sqlite3` beside the prediction database.
One background task reads exchange filters and account commission rates through bounded GET requests.
The isolated transport limits each decoded response to 64 KiB before JSON parsing.
It rejects redirects and every endpoint except exchange time, symbol filters, and symbol commissions.
Exchange rate-limit responses defer later observer reads without retry storms.
Current depth archives contain Mainnet data, so this observer rejects Testnet source hosts.
This restriction does not enable Mainnet execution or change the configured trading venue.
The observer has no order interface and no waiting work queue.
Its source cache supports at most eight configured symbols.
Unchanged runtime inputs permit one observation every thirty seconds.
Observed state changes bypass that interval.
Slow network requests do not hold the runtime lock.

Each record contains only normalized values, source times, source hashes, and the confirmed classifier contract.
Remote bodies, request headers, credentials, and account identifiers never enter this journal.
Commission estimates include standard, tax, and special rates without assuming a discount.
Missing commission components block the observation instead of becoming zero.

Source times use local receipt timestamps, as do the depth archives.
They never use candle-close times or request-start times.
Filter and fee sources expire after five minutes.
Runtime observations expire after three minutes.
The complete context expires with its earliest source.
Repeated cache use never renews a source timestamp.

The runtime source records the exact confirmed regime and PANIC input consumed by the supervisor.
A public supervisor observer refreshes PANIC state when the execution worker is absent.
The observer state expires after two minutes.
Its fingerprint fixes the calculation, debounce, cooldown, and recovery rules.
Unknown or stale PANIC state blocks collection; it never becomes a false value.
A missing initial state primes the public observer without writing a journal gap.
The next cycle records the exact PANIC state consumed by the runtime.
A state change during a pending source read creates an explicit unavailable record.
The status appears under `historical_context` in the runtime status object.
Failure status contains an error class, not an exception message.

Schema version one binds every record to its preceding hash and supervisor session.
Update and delete triggers preserve existing records.
Export checks source hashes, record hashes, classifier identity, expiry, session continuity, and complete window coverage.
An unavailable record, restart boundary, or missing interval blocks export.
Sources observed after the cutoff cannot change an earlier export.
These hashes detect changes; they are not exchange signatures.

Existing depth archives without contemporaneous context remain unsuitable for complete policy replay.
The observer does not reconstruct missing past fees, filters, or PANIC state.

## Policy replay

The policy fixes gap, target, stop, quantity budget, fees through context, cadence, latency, and permitted regimes.
The model uses the current book midpoint as its reference price.
It rounds entry quantities and prices with the historical exchange filters.
Passive prices outside the observed book block the replay.
The output includes model source hashes and the policy fingerprint.

The signal uses only the preceding observation window.
It combines price movement, signed trade quantity, and book order-flow imbalance.
The signal does not use a future fill timestamp.
The frozen rule records the exact five-minute signal window.
Runtime rejects a snapshot from a different window.

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

Each path has a one-hour entry window and permits one terminal attempt for each policy arm.
The planner admits a path only when a causal RANGE interval overlaps its entry window.
PANIC-only and non-executable intervals remain visible as rejected context paths.

Selection freezes twelve executable paths in four source-disjoint blocks.
Confirmation freezes forty-two post-cutoff executable paths in three-path blocks.
Each complete report must contain one terminal attempt for each source path.
Only imported immutable L2 reports enter the fixed confirmation evaluator.
Concurrent live SHADOW episodes remain diagnostic and cannot change confirmation.

## Run an offline replay

CAUTION: the request requires audited historical context and exact source hashes.
The following command neither creates orders nor changes a canary.

```bash
PYTHONPATH=. .venv/bin/python -m bin.replay_historical_entries \
  --request /absolute/path/selection-request.json \
  --output /absolute/path/selection-replay.json
```

For source-owned context, omit `context` from the request and select the journal:

```bash
PYTHONPATH=. .venv/bin/python -m bin.replay_historical_entries \
  --request /absolute/path/selection-request.json \
  --context-db /absolute/path/historical_context.sqlite3 \
  --output /absolute/path/selection-replay.json
```

This mode opens SQLite read-only and includes the verified context proof in the immutable report.
Supplying both inline context and a journal blocks the request.
Missing journal files block replay without creating a database.

`COMPLETE_SELECTION_REPLAY` means the historical replay completed without missing evidence.
It does not approve a candidate, prove profitability, or authorize promotion.
Independent time-block selection, runtime parity, and independent confirmation remain separate requirements.
An existing output file blocks publication rather than being replaced.

The depth processor also runs a bounded SHADOW request queue every 15 minutes.
It first creates review-only drafts under `.historical-replay/drafts`.
The planner requires 12 complete paths and complete historical context.
It reports L2-ready and context-ready path counts separately.
Each path has five-minute warmup, five-minute entry, and six-hour terminal windows.
Each path remains inside one verified provider session.
The planner groups three chronological paths into each of four stability blocks.
It never joins reconnects or reuses a source segment.
Preflight compares path duration with the 24-hour provider lifetime.
An impossible design reports `DESIGN_UNREACHABLE` before draft creation.
One persistent marker freezes the first complete selection cohort.
Later planning cycles cannot replace that cohort or add rolling drafts.
It never copies drafts into the accepted request queue.
Place reviewed immutable requests under `.historical-replay/requests` in the depth directory.
The runner writes immutable reports under `.historical-replay/reports`.
It replays eight policies through one pass per path.
It accepts at most 256 queued requests.
The replaceable `status.json` reports queue progress without source paths or exception text.
The runner never imports selection, freezes a candidate, changes HALT, or creates orders.

After v23 freezes, the planner creates a separate post-cutoff confirmation cohort.
Its path count is fixed at the provider capacity boundary.
Three reserve paths protect the deadline from transport attrition.
The deadline capacity packs three complete paths into each provider session.
Fourteen days can contain at most forty-two complete paths.
Selection sources and pre-cutoff paths cannot enter this cohort.
Drafts remain under `.historical-replay/confirmation-drafts` as immutable evidence.
The planner queues each complete block under `.historical-replay/confirmation-requests`.
The runner writes reports under `.historical-replay/confirmation-reports`.
The importer verifies hashes and imports each complete queued block automatically.
Status separates queued, replayed, verified, imported, and evaluated block counts.

Import reviewed, non-overlapping historical replay blocks:

```bash
.venv/bin/python -m bin.prediction_experiment \
  entry-veto-import-history SOURCE_EXPERIMENT_ID \
  --cutoff-ts-ms CUTOFF_TS_MS \
  --report BLOCK_ONE.json --report-sha256 BLOCK_ONE_SHA256 \
  --report BLOCK_TWO.json --report-sha256 BLOCK_TWO_SHA256 \
  --report BLOCK_THREE.json --report-sha256 BLOCK_THREE_SHA256 \
  --report BLOCK_FOUR.json --report-sha256 BLOCK_FOUR_SHA256 \
  --confirm IMPORT-HISTORICAL-VETO
```

The provider-bounded importer requires 12 opportunities and 12 independent paths.
At least three of four stability blocks must show non-negative improvement.
Legacy block reports retain their 30-opportunity requirement.
The imported artifact remains selection-only and cannot satisfy live confirmation.

After v23 freezes, import only disjoint post-cutoff reports:

```bash
.venv/bin/python -m bin.import_v23_confirmation \
  --prediction-db PREDICTION_DB \
  --report REPORT_PATH REPORT_SHA256 \
  --confirm IMPORT-V23-DISJOINT-CONFIRMATION
```

The importer requires the same policy and replay implementation as selection.
It rejects every selection archive hash.
It writes each start and result in one SQLite transaction.
Minute REST evidence cannot enter v23 confirmation.

Freeze empirical volatility boundaries from pre-cutoff calibration reports:

```bash
.venv/bin/python -m bin.volatility_policy CALIBRATION_FILES \
  --cutoff-ts-ms CUTOFF_TS_MS \
  --created-at-ms CREATED_AT_MS \
  --output volatility-policy.json \
  --confirm FREEZE-VOLATILITY-SELECTION
```

Use the policy only with new calibration archives through `--volatility-policy`.
The confirmation cohort must span two days and cover each approved bucket.
An unapproved bucket remains blocked for BUY.

## Storage contract

| Record | Classification | Growth bound | Retention and archive dependency |
| --- | --- | --- | --- |
| Public segments and sidecars | Authoritative source evidence | Directory byte cap and 10,000 segment limit | Local 14-day minimum; external encrypted archive after reference review |
| Calibration reports | Derived evidence | One report per source segment | Same retention as the retained source |
| Calibration inventory | Disposable status | One bounded replacement file | Rebuilt by the worker; no archive dependency |
| Rolling volatility | Disposable status | One bounded replacement file | Overwritten every five minutes; no archive dependency |
| Historical replay reports | Derived selection evidence | 10,000 attempts per policy and immutable output | Retain with policy, context, and source archives |
| Historical replay drafts | Derived review input | 256 immutable drafts | Retain sources through operator review |
| Historical replay requests | Authoritative operator input | 256 queued immutable requests | Retain through operator review and selection import |
| Historical replay runner status | Disposable status | One bounded replacement file | Rebuilt every runner cycle |
| Historical context journal | Authoritative context evidence | 131,072 records and 256 MiB database limit | Indefinite; archive only after verified encrypted backup and reference review |
| Context export | Derived selection evidence | 4,096 records and 16 MiB compact JSON limit | Retain with the immutable replay report and journal |
| Historical selection artifact | Derived selection evidence | 1,024 database rows | Indefinite with referenced reports and source hashes |
| Volatility policy | Derived selection evidence | 2,048 calibration reports per immutable file | Indefinite with its confirmation report |
| Unfinished temporary files | Disposable incomplete capture | Shared directory byte cap | Manual review; never selected as evidence |

The worker checks the backlog every thirty seconds when idle.
The recorder checks storage capacity at every rotation and before each write.
The default directory limit is eight gibibytes.
Pending diagnostics, selection references, and validation evidence can depend on older files.
Storage exhaustion stops capture instead of removing protected evidence.
The daily retention job keeps at least 24 recent segments.
It selects only completed, calibrated, unreferenced segments older than 14 days.
Pending historical replay drafts and requests protect every pinned source hash.
It requires a recent verified encrypted application backup.
It streams selected files into an encrypted bundle on the external disk.
It verifies the encrypted bundle before it removes exact local files.
Any mount, hash, backup, encryption, or reference failure preserves local files.

The context writer checks record and database capacity on every observation.
Its write-ahead log requests a checkpoint every 256 pages.
SQLite readers can temporarily delay that checkpoint.
Exports have a fixed record and byte ceiling and close their read transaction after validation.
Capacity exhaustion blocks new observations without deleting existing context or other evidence.
The scheduled encrypted application backup includes project database files through the SQLite online backup API.
The journal remains outside automatic database retention.
Operator archival must preserve all context referenced by pending diagnostics, selection reports, or validation evidence.
