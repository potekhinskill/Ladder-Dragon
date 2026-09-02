# Configuration reference

The authoritative configuration template is [`.env.example`](../.env.example).
The updater does not copy new example values into a live `.env` file.

Review each new value before you add it to a Raspberry Pi.
Never copy credentials into documentation, Git, logs, or command arguments.

## Execution authority

| Setting | Purpose | Safe default |
| --- | --- | --- |
| `BOT_LIVE_CONFIRMED` | permits reviewed Mainnet LIVE execution | `NO` |
| `BOT_TESTNET_ORDER_CONFIRMED` | permits the Testnet limit-cancel test | `NO` |
| `BOT_TESTNET_BUY_OCO_CONFIRMED` | permits the Testnet BUY and OCO lifecycle | `NO` |
| `BOT_EXPECTANCY_APPROVED` | permits expectancy APPLY | `NO` |
| `BOT_INVENTORY_SKEW_APPROVED` | permits inventory APPLY | `NO` |
| `BOT_MAKER_POLICY_APPROVED` | permits maker-policy APPLY | `NO` |
| `BOT_REGIME_GATE_APPROVED` | permits regime-gate APPLY | `NO` |
| `BOT_FAST_MARKET_APPROVED` | permits fast-market APPLY | `NO` |
| `BOT_OTOCO_APPROVED` | permits OTOCO APPLY | `NO` |
| `BOT_WS_TRADING_APPROVED` | permits WebSocket trading APPLY | `NO` |
| `BOT_EXECUTION_PROMOTION_APPROVED_<SYMBOL>` | permits one confirmed symbol promotion | `NO` |

An approval variable does not bypass HALT, CAP, reserve, or reconciliation.
The applicable mode must also be `APPLY`.
Candidate promotion also requires a current `CONFIRMED` experiment.
It requires explicit order and managed-inventory CAPs for that symbol.
Confirmation permits activation review but does not start execution.
Activation requires a persistent HALT and the reviewed report and manifest fingerprints.

## Strategy and prediction

| Prefix or setting | Purpose |
| --- | --- |
| `ADAPT_*` and `DIR_*` | deterministic ladder adaptation |
| `ADAPTIVE_REANCHOR_MODE` and `REANCHOR_*` | bounded BUY refresh |
| `PREDICTION_*` | SHADOW database, interval, fees, and slippage |
| `BOT_EXECUTION_CANDIDATE_SYMBOLS` | staged symbols that remain outside execution |
| `BOT_MARKET_ANALYSIS_*` | public scenario symbols, intervals, costs, and evidence paths |
| `BOT_EXPECTANCY_*` | exact execution-cost floor evidence |
| `BOT_FEE_PCT` | conservative Spot fee per side; `0.001` means 0.1% |
| `BOT_REGIME_*` | regime state machine and hysteresis |
| `BOT_INVENTORY_SKEW_*` | managed-inventory size reduction |
| `BOT_STATISTICAL_REGIME_MODE` | OFF or SHADOW statistical challenger |
| `BUY_VWAP_HYSTERESIS_PCT` | VWAP gate Schmitt band |
| `BUY_VWAP_DISCOUNT_*` | bounded VWAP discount adaptation from regime and ATR |
| `VWAP_AUTOTUNE_DISCOUNT_*` | bounded VWAP discount adaptation from exact PnL evidence |

A larger VWAP discount requires a deeper price decline before CAP scaling.
DOWN, loss, and volatility evidence increase this threshold.
UP and profit evidence decrease it.
Set a lower fee only after you confirm the active account discount.

Each traded symbol requires an explicit managed-inventory hard CAP.
For example, SOL uses `RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT`.
This value does not fall back to the portfolio CAP.
The Risk Manager enforces this CAP in every strategy-control mode.
Each staged symbol also requires `RISK_SYMBOL_CAP_<SYMBOL>`.
The per-order CAP cannot exceed the managed-inventory hard CAP.

## AI and RAG

| Prefix or setting | Purpose |
| --- | --- |
| `AI_ADVISOR_ENABLE` | enables provider requests |
| `AI_MODE` | selects `DISABLED`, `SHADOW`, or `APPLY` |
| `AI_PROVIDER` and `AI_MODEL` | select the provider adapter and model |
| `AI_TIMEOUT_SEC` | bounds one provider request |
| `AI_CACHE_SEC` | sets the normal advice cache time |
| `AI_NEGATIVE_CACHE_SEC` | sets the first provider-error cache time |
| `AI_*LIMIT*` and `AI_MAX_REQUESTS_PER_DAY` | set daily budgets |
| `AI_MIN_CLOSED_DECISIONS` | sets the real-closure minimum for AI APPLY; default `60` |
| `AI_RAG_*` | set real-only retrieval limits and retention |
| `AI_DECISIONS_DB` and `AI_USAGE_LOG` | store local evidence |

Consecutive provider failures use bounded exponential negative-cache backoff.
A valid response resets the failure sequence.
Identical operator diagnostics appear at most once each hour.
Decision and usage evidence still records each provider result.

`AI_RAG_INCLUDE_VIRTUAL` must remain `0`.
Historical virtual documents are archive data and cannot enter retrieval.

## Risk and circuit breaker

| Prefix or setting | Purpose |
| --- | --- |
| `CB_*` | daily loss, drawdown, HALT, state, and alerts |
| `RISK_PORTFOLIO_*` | portfolio exposure limits |
| `RISK_DAILY_*` | turnover, BUY, and trade-count limits |
| `RISK_RESERVE_USDT` | minimum free quote reserve |
| `RISK_RECONCILE_TOLERANCE_FRACTION` | account and ledger quantity tolerance; `0.001` means 0.1% |
| `RISK_RECONCILE_*` | account and ledger reconciliation controls |
| `RISK_VAR_*` | optional Value at Risk gate |
| `RISK_EXPECTED_SHORTFALL_*` | optional Expected Shortfall gate |
| `RISK_CLUSTER_*` | correlation-cluster evidence and limits |
| `RISK_UNVALUED_ASSETS*` | reviewed nontradeable dust exclusions |
| `RISK_PUBLIC_READ_CONCURRENCY` | public ticker, kline, and depth concurrency from 1 through 4 |
| `RISK_UNVALUED_NEGATIVE_CACHE_SEC` | invalid-symbol cache duration from 0 through 900 seconds |

A zero VaR or Expected Shortfall CAP disables that optional gate.
Unvalued-asset exclusion and acknowledgement lists must match exactly.
Excluded assets cannot increase equity or CAP.
The invalid-symbol cache is disposable, memory-only, and limited to 128 markets.
Only Binance error `-1121` enters this cache.
Expired entries cause a new public market check.
HALT, reset, cooldown, and evaluation use one process lock.
`RISK_MAX_CONSECUTIVE_LOSSES` cannot exceed 4,096 retained SELL outcomes.
Each SELL loss sign uses exact FIFO cost allocation.
`--pos-max-base-map` and `--pos-max-usdt-map` use `SYMBOL:VALUE` items.
One malformed, duplicate, negative, or unconfigured item stops startup.

## Transport and latency

| Prefix or setting | Purpose |
| --- | --- |
| `BINANCE_AUTH_BACKOFF_*` | definitive authentication failure backoff |
| `BINANCE_PREFLIGHT_BACKOFF_*` | transient preflight backoff |
| `BINANCE_PUBLIC_IP_ENDPOINTS` | two-source IP consensus before signed automatic acceptance |
| `BOT_USER_STREAM_*` | notification-only stream state |
| `BOT_EXECUTION_LATENCY_LOG` | intent-to-exchange-event samples |
| `BOT_LATENCY_TRACE_LOG` | local execution phase samples |
| `BOT_FAST_MARKET_*` | snapshot age, spread, move, and edge gates |
| `BOT_OTOCO_*` | atomic order-list observation or application |
| `BOT_WS_TRADING_*` | signed WebSocket trading transport |
| `BINANCE_KEY_TYPE` | selects HMAC or ED25519 signing |

The ED25519 key path must be absolute and owner-only.
The application does not log private key material.
IP Guard accepts a changed fingerprint only after the complete signed read-only preflight passes.
Runtime authentication rejection refreshes the same two-source IP evidence.
When the fingerprint changed, signed recovery checks run once each minute.
Telegram reports a new fingerprint transition once and omits diagnostic identifiers.
Successful signed recovery sends one clear notice and preserves all other risk gates.
Other authentication failures keep the configured exponential backoff.
An authentication or source-consensus failure keeps BUY blocked.
Automatic acceptance never removes HALT or changes a trading limit.
Read-only symbol fallback uses the exact-accounting quote list.
An unknown quote suffix blocks balance-dependent work instead of guessing asset names.

## Data paths

| Setting | Raspberry Pi example |
| --- | --- |
| `BOT_STATS_DB` | `/home/bot/apps/binance_bot/db/bot_stats.db` |
| `BOT_ORDER_JOURNAL` | `/home/bot/apps/binance_bot/db/order_intents.sqlite3` |
| `PREDICTION_SHADOW_DB` | `/home/bot/apps/binance_bot/db/prediction_shadow.sqlite3` |
| `BOT_PREDICTION_SHADOW_SYMBOLS` | `SOLUSDT,ETHUSDT,BTCUSDT` |
| `BOT_EXECUTION_CANDIDATE_SYMBOLS` | `BTCUSDT,ETHUSDT` |
| `BOT_MARKET_ANALYSIS_SYMBOLS` | `SOLUSDT,ETHUSDT,BTCUSDT` |
| `BOT_MARKET_ANALYSIS_TIMEFRAMES` | `1h,4h,1d,1w,1M` |
| `BOT_MARKET_ANALYSIS_ROUND_TRIP_COST_PCT` | `0.0025` |
| `BOT_MARKET_ANALYSIS_DB` | `db/market_scenario_shadow.sqlite3` |
| `BOT_MARKET_ANALYSIS_STATUS_FILE` | `/var/lib/ladder-dragon/market-analysis/status.json` |
| `AI_DECISIONS_DB` | `/home/bot/apps/binance_bot/db/ai_decisions.sqlite3` |
| `LADDER_DRAGON_CONTROL_DIR` | `/var/lib/ladder-dragon/control` |
| `BOT_RUN_DIR` | `/run/mybot` |

Testnet always replaces the statistics database, order journal, and runtime directory together.
Missing `BOT_TESTNET_*` values use isolated defaults below the project database directory.
The Testnet runtime default is `/run/mybot/testnet`.
Any Testnet and Mainnet path collision blocks startup before environment changes.

Persistent safety evidence belongs below `/var/lib/ladder-dragon`.
Process-lifetime state belongs below `/run/mybot`.

Prediction SHADOW symbols use separate symbol-scoped evidence.
They never extend `BOT_SERVICE_SYMBOLS` or start execution workers.
Each symbol requires its own statistical PASS before separate APPLY approval.
Execution candidates remain staged until all promotion gates pass.
An execution symbol without an active CHAMPION remains SHADOW-only.
The supervisor does not start its execution worker.
Removing a symbol from the candidate list cannot bypass the CHAMPION gate.
Market analysis uses an independent public-data symbol list.
Its symbols never extend `BOT_SERVICE_SYMBOLS`.
SOLUSDT version sixteen tests a 48 basis-point gap and three entry lifetimes.
ETHUSDT version fifteen uses 20, 21, and 22 basis-point gaps.
BTCUSDT version fourteen uses 8.4, 9.4, and 10.3 basis-point gaps.
These generations use the authoritative Binance account commission schedule.
Earlier SOLUSDT, ETHUSDT, and BTCUSDT generations remain visible as superseded evidence.

## Dashboard and notifications

| Prefix or setting | Purpose |
| --- | --- |
| `DASHBOARD_BINANCE_*` | separate read-only Binance credentials |
| `DASHBOARD_AUTH_TOKEN` | private dashboard authentication |
| `DASHBOARD_*LIMIT*` | request, stream, and metrics limits |
| `TELEGRAM_ALERTS_CONFIG` | root-managed Telegram environment file |
| `TELEGRAM_ALERTS_ENABLED` | enables Telegram delivery |
| `BOT_ALERT_WEBHOOK_URL` | optional notification webhook |

Do not put a token or signature in a webhook URL.
Use the separate read-only Binance key for dashboard endpoints.
Set `DASHBOARD_RATE_LIMIT_PER_MIN=360` for the standard five-second refresh.
The browser honors `Retry-After` when the dashboard returns HTTP 429.
