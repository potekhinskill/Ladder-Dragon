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
| `audit_legacy_compatibility` | reports remaining legacy accounting dependencies |
| `audit_numeric_boundaries` | finds direct float calls at financial boundaries |
| `audit_replay_readiness` | checks archive, latency, regime, and validation evidence |
| `audit_user_stream_soak` | checks current-epoch stream duration, stability, and events |
| `check_technical_english` | checks current guides against the project writing profile |
| `semgrep_scan` | tests local Semgrep rules or scans production Python paths |
| `production_soak_report` | builds a sanitized non-mutating soak report |
| `testnet_soak_monitor` | monitors Testnet safety without order mutation |

The harness supports these profiles:

| Profile | Scope |
| --- | --- |
| `local` | evidence, compileall, tests, numeric audit, secret scan, and Semgrep |
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

| Command | Purpose |
| --- | --- |
| `backtest` | runs OHLC backtest and optional archived L2 replay |
| `calibrate_replay` | creates a source-hashed replay calibration report |
| `validate_replay_outcomes` | compares replay with real terminal order outcomes |
| `record_depth_archive` | records public depth and aggregate-trade JSONL |
| `prediction_history_backfill` | creates cutoff-safe samples from archived bars |
| `backfill_prediction_archive` | repairs eligible expired prediction outcomes |
| `monthly_prediction_report` | creates the monthly defensive SHADOW report |
| `regime_pnl_report` | compares strategy, buy-and-hold, and USDT by regime |
| `auto_ladder_map` | generates deterministic ladder diagnostics |
| `ladder_pct_runner` | runs the percentage-ladder utility |
| `gen_vwap_autotune` | generates PnL-adjusted VWAP configuration text |
| `gen_vwap_env` | generates regime-adjusted VWAP configuration text |
| `update_vwap_env` | runs both generators with the active project interpreter |

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

## Execution and operator commands

| Command | Purpose | Mutation boundary |
| --- | --- | --- |
| `ai_supervisor` | supervises symbols and workers | mode and risk gates |
| `autosize_universal` | runs one execution worker | mode and risk gates |
| `ai_plan_runner` | runs a reviewed AI plan | no direct AI order authority |
| `binance_testnet_smoke` | runs public or confirmed Testnet checks | explicit mode confirmation |
| `binance_mainnet_canary` | runs one bounded Mainnet lifecycle | three explicit confirmations |
| `mainnet_user_stream_drill` | proves one Mainnet order event and REST reconciliation | three explicit confirmations and persistent HALT |
| `tools_cancel_open` | previews or cancels selected open orders | `--live` plus venue selection |
| `risk_ctl` | reads or resets the persistent HALT | manual reset review |
| `maintenance_state` | sets, clears, or reads maintenance state | explicit operator command |
| `import_legacy_cost_basis` | previews or applies a FIFO basis plan | `--apply` plus confirmations |
| `review_unattributed_fills` | reviews exact historical attribution gaps | `--apply` plus confirmation |
| `retire_legacy_accounting` | previews or applies exact-only retirement | stopped runtime evidence, backup, `--apply`, and confirmation |
| `revalue_legacy_commissions` | repairs exact legacy commission values | explicit reviewed operation |
| `db_migrate` | applies versioned SQLite migrations | migration transaction |
| `database_retention` | archives terminal SHADOW evidence and applies bounded retention | fresh encrypted backup |
| `migrate_indexes` | applies the legacy index migration helper | reviewed database path |

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

`daily_trading_digest --dry-run` prints private account data.
Do not publish its output.

## Raspberry Pi services

| Unit | Function | Schedule or state |
| --- | --- | --- |
| `mybot.service` | supervisor and execution workers | persistent service |
| `pi-dashboard.service` | private dashboard | persistent service |
| `pi-watchdog-v3.service` | host and bot recovery check | timer target |
| `pi-watchdog-v3.timer` | starts the watchdog | each 5 minutes |
| `ladder-dragon-backup.service` | encrypted private backup | timer target |
| `ladder-dragon-backup.timer` | starts backup | 02:20 each day |
| `ladder-dragon-daily-digest.service` | exact Telegram trading report | timer target |
| `ladder-dragon-daily-digest.timer` | starts the digest | 08:00 Asia/Almaty |
| `ladder-dragon-database-retention.service` | archives terminal SHADOW data | fresh encrypted backup |
| `ladder-dragon-database-retention.timer` | starts database retention | daily after backup |
| `ladder-dragon-depth-archive.service` | public L2 archive recorder | timer target |
| `ladder-dragon-depth-archive.timer` | starts archive collection | each hour |
| `ladder-dragon-log-export.service` | sanitized dashboard log export | timer target |
| `ladder-dragon-log-export.timer` | refreshes the log export | each minute |
| `ladder-dragon-monthly-prediction.service` | monthly SHADOW report | timer target |
| `ladder-dragon-monthly-prediction.timer` | starts the prediction report | monthly |
| `ladder-dragon-soak-audit.service` | signed production soak report | timer target |
| `ladder-dragon-soak-audit.timer` | starts the soak report | each 15 minutes |
| `ladder-dragon-user-stream-shadow.service` | read-only authenticated stream observer | persistent service |

An inactive disabled or masked `mybot.service` is an intentional operator stop.
The watchdog does not restart it.
