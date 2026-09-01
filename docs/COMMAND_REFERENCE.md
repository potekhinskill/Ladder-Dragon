# Command and service reference

Run project commands through the repository virtual environment:

```bash
.venv/bin/python -m bin.COMMAND --help
```

Use `PYTHONPATH=.` when the package is not installed in the environment.
Help output is the authoritative option reference.

## Verification and audit commands

| Command | Purpose |
| --- | --- |
| `verification_harness` | runs local, release, Testnet, Pi, or Mainnet-canary verification |
| `audit_ai_readiness` | checks real AI evidence for APPLY readiness |
| `audit_backtest_reports` | classifies saved backtest reports |
| `audit_exchange_boundaries` | rejects authenticated exchange calls outside reviewed adapters |
| `audit_execution_authority_paths` | checks authority calls, gates, ordering, and supervisor cadence |
| `audit_guard_contracts` | checks registered fail-closed functions and qualified class methods |
| `audit_legacy_compatibility` | reports remaining legacy accounting dependencies |
| `audit_numeric_boundaries` | finds direct float calls at financial boundaries |
| `audit_replay_readiness` | checks archive, latency, regime, and validation evidence |
| `audit_semantic_authorities` | rejects copied or divergent financial semantics and indicator implementations |
| `audit_user_stream_soak` | checks the current reviewed epoch for duration, stability, and events |
| `check_technical_english` | checks current guides against the project writing profile |
| `semgrep_scan` | tests local Semgrep rules or scans production Python paths |
| `production_soak_report` | builds a sanitized non-mutating soak report |
| `testnet_soak_monitor` | monitors Testnet safety with bounded source retries |

The harness supports these profiles:

| Profile | Scope |
| --- | --- |
| `local` | evidence, compileall, tests, domain audits, secret scan, and Semgrep |
| `release` | local checks plus replay, recovery, migration, deployment, and continuity |
| `testnet` | public and separately confirmed authenticated Testnet checks |
| `pi` | deployed SHA, services, assets, risk, stream, journal, and soak evidence |
| `mainnet-canary` | separately confirmed bounded Mainnet acceptance test |

The exit codes are `0` for PASS, `1` for FAILED, and `2` for BLOCKED.

Install Semgrep in its isolated environment:

```bash
python3 -m venv .semgrep-venv
.semgrep-venv/bin/python -m pip install \
  --require-hashes -r requirements/semgrep.lock
```

Test the local rules before you scan production paths:

```bash
.venv/bin/python -m bin.semgrep_scan --rules-test
.venv/bin/python -m bin.semgrep_scan
```

The scan does not use network rules or send metrics.
The harness does not pass application credentials to the scanner process.
The Pi profile does not install or run Semgrep.

## Strategy, prediction, and replay commands

See [Historical entry replay](HISTORICAL_ENTRY_REPLAY.md) for continuous source and offline selection contracts.

| Command | Purpose |
| --- | --- |
| `backtest` | runs OHLC backtest and optional archived L2 replay |
| `calibrate_replay` | creates a source-hashed replay calibration report |
| `validate_replay_outcomes` | compares replay with real terminal order outcomes |
| `validate_replay_sessions` | validates separate contiguous replay sessions without joining gaps |
| `record_depth_archive` | records public depth and aggregate-trade JSONL |
| `depth_archive_service` | rotates one continuous public stream and processes calibration separately |
| `depth_archive_retention` | encrypts eligible L2 segments externally before local removal |
| `replay_historical_entries` | generates historical opportunities from immutable inputs; optional `--context-db` verifies source-owned context |
| `historical_replay_planner` | creates frozen selection and post-cutoff confirmation draft cohorts |
| `historical_replay_runner` | processes a bounded SHADOW replay queue under an explicit import mode |
| `volatility_policy` | freezes empirical volatility buckets from selection-only calibration reports |
| `migrate_volatility_policy` | binds a verified legacy policy to the exact 55-minute measurement window |
| `import_entry_veto_l2` | imports source-hashed public L2 entry features into SHADOW evidence |
| `import_v23_confirmation` | imports reviewed post-cutoff diff-depth reports into one v23 confirmation generation |
| `prediction_history_backfill` | creates cutoff-safe samples from archived bars |
| `backfill_prediction_archive` | repairs eligible expired prediction outcomes |
| `prediction_experiment` | bootstraps and audits independent SHADOW confirmation |
| `monthly_prediction_report` | creates the monthly defensive SHADOW report |
| `market_scenario_shadow` | collects public multi-symbol scenario evidence |
| `regime_pnl_report` | compares strategy, buy-and-hold, and USDT by regime |
| `auto_ladder_map` | generates deterministic ladder diagnostics |
| `ladder_pct_runner` | runs the percentage-ladder utility |
| `gen_vwap_autotune` | generates PnL-adjusted VWAP configuration text |
| `gen_vwap_env` | generates regime-adjusted VWAP configuration text |
| `update_vwap_env` | runs both generators with the active project interpreter |

Use `--archive` for one completed public archive.
Use `--archive-directory` to attach retained archives after a filled episode becomes terminal.

Run an OHLC backtest:

```bash
.venv/bin/python -m bin.backtest data.csv --output report.json
```

Add an archived L2 event stream:

```bash
.venv/bin/python -m bin.backtest data.csv \
  --archive archive.jsonl \
  --calibration calibration.json \
  --output report.json
```

The positional CSV must contain `ts,open,high,low,close`.
The `--archive` option does not make the replay an L3 reconstruction.

Validate replay with the exact frozen account fee schedule:

```bash
.venv/bin/python -m bin.validate_replay_outcomes archive.jsonl \
  --execution-log execution-latency.ndjson \
  --calibration calibration.json \
  --maker-buy-fee-pct MAKER_BUY_RATE \
  --maker-sell-fee-pct MAKER_SELL_RATE \
  --taker-buy-fee-pct TAKER_BUY_RATE \
  --taker-sell-fee-pct TAKER_SELL_RATE \
  --output validation.json
```

Validate separate archives without joining recording gaps:

```bash
.venv/bin/python -m bin.validate_replay_sessions \
  --session maker.jsonl maker-calibration.json \
  --session stop.jsonl stop-calibration.json \
  --calibration-context low-calibration.json \
  --calibration-context normal-calibration.json \
  --calibration-context high-calibration.json \
  --volatility-policy volatility-policy.json \
  --batch-manifest BATCH_MANIFEST \
  --execution-log execution-latency.ndjson \
  --maker-buy-fee-pct MAKER_BUY_RATE \
  --maker-sell-fee-pct MAKER_SELL_RATE \
  --taker-buy-fee-pct TAKER_BUY_RATE \
  --taker-sell-fee-pct TAKER_SELL_RATE \
  --output validation.json \
  --prediction-db db/prediction_shadow.sqlite3 \
  --experiment-id EXPERIMENT_ID \
  --symbol SOLUSDT \
  --execution-model-rule minute_l2_fifo_oco_gap_v3 \
  --confirm-import IMPORT_PASS
```

Each `--session` must belong to the complete order validation batch.
Each `--calibration-context` must contain only read-only public archive calibration.
The two cohorts must not share an archive SHA-256.
The calibration context must cover two days and all required volatility regimes.
If used, the policy must come from a disjoint pre-cutoff selection cohort.

Each terminal order must fit inside one session.
The validator rejects duplicate or overlapping archive identities.
Production import requires every archive and order from the completed batch.
The importer recomputes PASS with the built-in acceptance policy.
CLI options cannot weaken production acceptance thresholds.

Inspect the local experiment lifecycle:

```bash
.venv/bin/python -m bin.prediction_experiment status --symbol SOLUSDT
```

Freeze the preregistered SOL execution candidate:

```bash
.venv/bin/python -m bin.prediction_experiment episode-bootstrap \
  --experiment-id EXPERIMENT_ID \
  --symbol SOLUSDT \
  --generation v23 \
  --confirm BOOTSTRAP
```

The command requires a clean checkout of the exact published release tag.
It freezes one preselected candidate before live episodes start.
Diagnostic-only generations cannot enter confirmation.
The `report` command never changes lifecycle state.

Import one reviewed execution-model validation:

```bash
.venv/bin/python -m bin.prediction_experiment model-validation-import \
  --symbol SOLUSDT \
  --generation v23 \
  --experiment-id EXPERIMENT_ID \
  --report validation.json \
  --report-sha256 REPORT_SHA256 \
  --confirm IMPORT
```

The report must contain sanitized real LIMIT_MAKER and STOP_LOSS_LIMIT fills.
It must include strict readiness across three replay archives and two days.

Inspect cutoff-safe entry-veto selection evidence:

```bash
.venv/bin/python -m bin.prediction_experiment entry-veto-report \
  EXPERIMENT_ID --cutoff-ts-ms CUTOFF_TS_MS
```

Freeze the reviewed selection artifact only after the report becomes ready:

```bash
.venv/bin/python -m bin.prediction_experiment entry-veto-freeze \
  EXPERIMENT_ID --cutoff-ts-ms CUTOFF_TS_MS --confirm FREEZE-VETO
```

The cutoff, evidence identifiers, hashes, latency, and selected rule become immutable.
The artifact cannot authorize orders or change the source generation.

Create deterministic replay drafts from separate verified production sessions:

```bash
.venv/bin/python -m bin.historical_replay_planner \
  --archive-directory DEPTH_DIRECTORY \
  --draft-directory DEPTH_DIRECTORY/.historical-replay/drafts \
  --context-db HISTORICAL_CONTEXT_DB \
  --prediction-db PREDICTION_DB
```

Review and copy accepted drafts into `.historical-replay/requests`.
The planner reports L2-ready and context-ready progress separately.
It freezes one selection cohort and prevents rolling draft growth.
After v23 freezes, it creates separate post-cutoff confirmation drafts.
The planner automatically queues each complete confirmation block.
The background runner uses `--import-mode automatic_confirmation`.
The strict importer verifies each queued block before statistical evaluation.

Import a reviewed post-cutoff report manually when automatic import is unavailable:

```bash
.venv/bin/python -m bin.import_v23_confirmation \
  --prediction-db PREDICTION_DB \
  --report REPORT_PATH REPORT_SHA256 REQUEST_PATH REQUEST_SHA256 \
  --confirm IMPORT-V23-DISJOINT-CONFIRMATION
```

The importer binds each report to its exact request.
It rejects selection sources, overlapping reports, and model changes.
It has no order interface.

Import four reviewed historical selection blocks:

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

The command stores only a strict selection artifact.
It cannot satisfy confirmation or authorize an order.

Finalize the exact reviewed report:

```bash
.venv/bin/python -m bin.prediction_experiment finalize EXPERIMENT_ID \
  --report-sha256 REPORT_SHA256 \
  --confirm FINALIZE
```

Use `show` and `supersede` for other lifecycle operations.

Preview a confirmed CHAMPION policy:

```bash
.venv/bin/python -m bin.prediction_experiment champion-preview EXPERIMENT_ID \
  --maximum-order-usdt 6 \
  --maximum-inventory-usdt 18
```

Activate only the reviewed policy while persistent HALT exists:

```bash
.venv/bin/python -m bin.prediction_experiment champion-activate EXPERIMENT_ID \
  --report-sha256 REPORT_SHA256 \
  --manifest-sha256 MANIFEST_SHA256 \
  --expected-execution-policy-fingerprint POLICY_SHA256 \
  --expected-previous-activation-id NONE \
  --maximum-order-usdt 6 \
  --maximum-inventory-usdt 18 \
  --confirm ACTIVATE
```

Activation resolves the authoritative HALT from Risk Manager configuration.
It rejects missing or invalid HALT evidence.
Use the current activation identifier instead of `NONE` for replacement.
Restart the supervisor before you reset HALT.
The worker verifies the activation again before LIVE execution.
Probation never extends automatically.
An expired insufficient probation requires review and a new activation.
Existing protected lifecycles can close without new BUY authority.

WARNING: The next command creates real Mainnet orders.

Run only an independently approved batch manifest:

```bash
BOT_MAINNET_VALIDATION_BATCH_RUN_CONFIRMED=YES \
  .venv/bin/python -m bin.run_mainnet_validation_batch \
  --manifest BATCH_MANIFEST \
  --notional-usdt 6 \
  --confirm RUN_VALIDATION_BATCH
```

The runner follows the immutable LIMIT_MAKER and STOP_LOSS_LIMIT sequence.
It records each reservation before mutation.
It closes each reservation as `SUCCEEDED`, `FAILED_DEFINITE`, or `FAILED_UNCERTAIN`.
A `FAILED_DEFINITE` attempt consumes its quota and permits the fixed sequence to continue.
The runner returns `INCOMPLETE` when any attempt has a proven failure.
An uncertain result permanently closes the batch.
Only an all-`SUCCEEDED` batch can become replay evidence.

## Execution and operator commands

| Command | Purpose | Mutation boundary |
| --- | --- | --- |
| `ai_supervisor` | supervises symbols and workers | mode and risk gates |
| `autosize_universal` | runs one execution worker | mode and risk gates |
| `ai_plan_runner` | runs a reviewed AI plan | no direct AI order authority |
| `binance_testnet_smoke` | runs public or confirmed Testnet checks | explicit mode confirmation |
| `binance_mainnet_canary` | runs one bounded Mainnet lifecycle | three explicit confirmations |
| `mainnet_user_stream_drill` | proves one Mainnet order event and REST reconciliation | three explicit confirmations and persistent HALT |
| `mainnet_limit_maker_validation` | collects one real passive fill for replay validation | separate approval, 6 USDT ceiling, cleanup, and persistent HALT |
| `mainnet_stop_limit_validation` | collects one real STOP_LOSS_LIMIT outcome | separate approval, 6 USDT ceiling, cleanup, and persistent HALT |
| `mainnet_validation_batch` | creates a bounded validation authorization | no order; fixed attempts, turnover, release, and expiry |
| `run_mainnet_validation_batch` | runs the fixed validation sequence | separate approval, persistent HALT, and automatic stop |
| `tools_cancel_open` | previews or cancels selected open orders | `--live` plus venue selection |
| `risk_ctl` | reads or resets the persistent HALT | manual reset review |
| `maintenance_state` | sets, clears, or reads maintenance state | explicit operator command |
| `import_legacy_cost_basis` | previews or applies a FIFO basis plan | `--apply` plus confirmations |
| `review_unattributed_fills` | reviews exact historical attribution gaps | `--apply` plus confirmation |
| `retire_legacy_accounting` | previews or applies exact-only retirement | stopped runtime evidence, backup, `--apply`, and confirmation |
| `revalue_legacy_commissions` | repairs exact legacy commission values | explicit reviewed operation |
| `db_migrate` | applies versioned SQLite migrations | migration transaction |
| `database_retention` | archives terminal SHADOW evidence and applies bounded retention | fresh encrypted backup |
| `migrate_indexes` | applies indexes for the active accounting schema | reviewed database path |

`tools_cancel_open` uses Testnet and dry-run by default.
Never remove a protective SELL order to make a test pass.

## Reporting and dashboard commands

| Command | Purpose |
| --- | --- |
| `daily_trading_digest` | sends the exact daily Telegram report |
| `pnl_24h` | calculates the 24-hour accounting view |
| `pnl_reporter` | prints an accounting report |
| `stats_view` | reads local statistics |
| `run_dashboard` | runs the dashboard on loopback |
| `user_stream_shadow` | runs the independent read-only stream observer |
| `generate_star_history` | generates the public star-history SVG |
| `ip_guard` | reads state or performs manual IP acceptance recovery |
| `ai_advisor_smoke` | tests an advisory provider without order tools |

Use this DRY command to validate a percentage ladder:

```bash
.venv/bin/python -m bin.ai_plan_runner --symbols SOLUSDT --ladder-pct=0.5,20,20
```

The command rejects malformed values before a market request or worker launch.

`daily_trading_digest --dry-run` prints private account data.
Do not publish its output.

## Raspberry Pi services

| Unit | Function | Schedule or state |
| --- | --- | --- |
| `mybot.service` | supervisor and execution workers | persistent service |
| `pi-healthd.service` | private dashboard | persistent service |
| `pi-watchdog-v3.service` | host and bot recovery check | timer target |
| `pi-watchdog-v3.timer` | checks network; checks bot health separately | each minute; health each 5 minutes |
| `ladder-dragon-backup.service` | encrypted private backup | timer target |
| `ladder-dragon-backup.timer` | starts backup | 02:20 each day |
| `ladder-dragon-daily-digest.service` | exact Telegram trading report | timer target |
| `ladder-dragon-daily-digest.timer` | starts the digest | 08:00 Asia/Almaty |
| `ladder-dragon-database-retention.service` | archives terminal SHADOW data | fails when retention is blocked |
| `ladder-dragon-database-retention.timer` | retries database retention | daily fallback |
| `ladder-dragon-depth-archive.service` | continuous public L2 archive recorder | persistent service |
| `ladder-dragon-depth-session-align.service` | starts a new L2 session after backup | backup success target |
| `ladder-dragon-depth-archive.timer` | legacy hourly archive schedule | disabled by deployment |
| `ladder-dragon-depth-retention.service` | verified encrypted L2 archive rotation | timer target |
| `ladder-dragon-depth-retention.timer` | starts L2 retention after backup | 04:10 each day |
| `ladder-dragon-log-export.service` | sanitized dashboard log export | timer target |
| `ladder-dragon-log-export.timer` | refreshes the log export | each minute |
| `ladder-dragon-monthly-prediction.service` | monthly SHADOW report | timer target |
| `ladder-dragon-market-scenario.service` | public multi-symbol scenarios | hourly timer target |
| `ladder-dragon-market-scenario.timer` | schedules public multi-symbol scenarios | hourly |
| `ladder-dragon-monthly-prediction.timer` | starts the prediction report | monthly |
| `ladder-dragon-soak-audit.service` | signed production soak report | timer target |
| `ladder-dragon-soak-audit.timer` | starts the soak report | each 15 minutes |
| `ladder-dragon-user-stream-shadow.service` | read-only authenticated stream observer | persistent service |

An inactive disabled or masked `mybot.service` is an intentional operator stop.
The watchdog does not restart it.
