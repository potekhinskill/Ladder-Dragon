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
| `BOT_STRATEGY_CONTROLS_APPROVED` | permits approved strategy controls | `NO` |
| `BOT_FAST_MARKET_APPROVED` | permits fast-market APPLY | `NO` |
| `BOT_OTOCO_APPROVED` | permits OTOCO APPLY | `NO` |
| `BOT_WS_TRADING_APPROVED` | permits WebSocket trading APPLY | `NO` |

An approval variable does not bypass HALT, CAP, reserve, or reconciliation.
The applicable mode must also be `APPLY`.

## Strategy and prediction

| Prefix or setting | Purpose |
| --- | --- |
| `ADAPT_*` and `DIR_*` | deterministic ladder adaptation |
| `ADAPTIVE_REANCHOR_MODE` and `REANCHOR_*` | bounded BUY refresh |
| `PREDICTION_*` | SHADOW database, interval, fees, and slippage |
| `BOT_EXPECTANCY_*` | exact execution-cost floor evidence |
| `BOT_REGIME_*` | regime state machine and hysteresis |
| `BOT_INVENTORY_SKEW_*` | managed-inventory size reduction |
| `BOT_STATISTICAL_REGIME_MODE` | transparent statistical challenger |
| `BUY_VWAP_HYSTERESIS_PCT` | VWAP gate Schmitt band |

Each traded symbol requires an explicit managed-inventory hard CAP.
For example, SOL uses `RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT`.
This value does not fall back to the portfolio CAP.

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

A zero VaR or Expected Shortfall CAP disables that optional gate.
Unvalued-asset exclusion and acknowledgement lists must match exactly.
Excluded assets cannot increase equity or CAP.
HALT, reset, cooldown, and evaluation use one process lock.
`RISK_MAX_CONSECUTIVE_LOSSES` cannot exceed 4,096 retained SELL outcomes.
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
An authentication or source-consensus failure keeps BUY blocked.
Automatic acceptance never removes HALT or changes a trading limit.

## Data paths

| Setting | Raspberry Pi example |
| --- | --- |
| `BOT_STATS_DB` | `/home/bot/apps/binance_bot/db/bot_stats.db` |
| `BOT_ORDER_JOURNAL` | `/home/bot/apps/binance_bot/db/order_intents.sqlite3` |
| `PREDICTION_SHADOW_DB` | `/home/bot/apps/binance_bot/db/prediction_shadow.sqlite3` |
| `AI_DECISIONS_DB` | `/home/bot/apps/binance_bot/db/ai_decisions.sqlite3` |
| `LADDER_DRAGON_CONTROL_DIR` | `/var/lib/ladder-dragon/control` |
| `BOT_RUN_DIR` | `/run/mybot` |

Persistent safety evidence belongs below `/var/lib/ladder-dragon`.
Process-lifetime state belongs below `/run/mybot`.

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
