<h1 align="center">Ladder Dragon — Binance Spot Grid Bot</h1>

<p align="center">
  <img src="docs/assets/ladder-dragon-banner-v2.svg" alt="Ladder Dragon" width="420">
</p>

> **New installation:** start with the [introduction](docs/INTRODUCTION.md).

Ladder Dragon is an open-source Python project for adaptive ladder trading on
Binance Spot. It builds BUY/SELL grids, uses ATR/EMA/VWAP/ADX regimes, manages
OCO protection, and records trading statistics in SQLite. Production secrets,
real backups, and private parameters are never committed.

Current product version: **2.10.59**. The single version source is
`product_version.py`; releases follow [Semantic Versioning](https://semver.org/).
Project contact: [LinkedIn](https://www.linkedin.com/in/ypotekhin/).

> [!WARNING]
> This software can submit real exchange orders. It is not investment advice.
> DRY is the default and Mainnet LIVE requires a separate Testnet run, limit
> review, protection verification, and explicit confirmation.

> Ladder Dragon is an independent open-source project. It is not affiliated with,
> endorsed by, sponsored by, or officially associated with Binance. Binance and
> related marks belong to their respective owners.

## Features

- adaptive percentage ladders for multiple symbols;
- market direction, ATR, EMA, VWAP, and ADX adaptation;
- optional AI recommendations for regime, ladder width, and CAP;
- per-order, per-symbol, portfolio, reserve, and correlation limits;
- OCO/STOP protection, partial-fill recovery, gap handling, and FIFO inventory;
- SQLite decision history, cash/FIFO PnL, RAG retrieval, and reports;
- FastAPI dashboard for Raspberry health, balances, positions, orders, AI, and logs;
- encrypted rotating backups and Telegram alerts for operational failures.

## Architecture

The repository root contains only stable entry points, configuration, and docs.
Reusable code lives in `ladder_dragon` and is grouped by responsibility:

| Path | Responsibility |
| --- | --- |
| `ladder_dragon/ai/` | AI advisory, context, policy, RAG, and runtime status |
| `ladder_dragon/execution/` | Binance transport, orders, OCO/STOP, recovery, fills, fees, inventory |
| `ladder_dragon/risk/` | circuit breaker, portfolio CAP, VaR/Expected Shortfall, risk gates |
| `ladder_dragon/strategy/` | ladders, indicators, simulation, and order-book replay |
| `ladder_dragon/migrations/` | versioned SQLite migrations |
| `FastAPI/pi-dashboard/` | read-only dashboard API and host telemetry |
| `FRONT/` | static dashboard and localized help |
| `deploy/` | Raspberry, systemd, nginx, backup, and deployment scripts |
| `tests/` | unit and live-regression tests |

CLI entry points are in `bin/` and run as `python -m bin.<command>`.

## Requirements and local setup

Linux or Raspberry Pi OS is the production target. Python 3.10+ is required;
the dashboard additionally uses FastAPI, Uvicorn, and psutil.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,dashboard]'
cp .env.example .env
```

Keep local runtime files in a writable directory:

```dotenv
BOT_RUN_DIR=.runtime
BOT_TESTNET_RUN_DIR=.runtime/testnet
BOT_STATS_DB=.runtime/bot_stats.db
BOT_ORDER_JOURNAL=.runtime/order_intents.sqlite3
BOT_TESTNET_STATS_DB=.runtime/testnet_bot_stats.db
BOT_TESTNET_ORDER_JOURNAL=.runtime/testnet_order_intents.sqlite3
```

Systemd uses `/run/mybot`. Testnet has separate runtime, halt state, stats DB,
and order journal.

## Configuration and AI

Start with Binance Spot Testnet and a key that cannot withdraw funds. The
dashboard must use a separate read-only key. Never commit `.env`, databases,
logs, or private keys.

AI is advisory only. It receives safe market aggregates and may recommend
`UP`, `DOWN`, or `FLAT`, a ladder-width multiplier, and a CAP multiplier. It has
no order tools and cannot bypass Risk Manager. Every response is validated
locally; errors, stale context, invalid JSON, or low confidence return to the
deterministic strategy.

```dotenv
AI_ADVISOR_ENABLE=1
AI_MODE=SHADOW
AI_PROVIDER=deepseek
AI_MODEL=deepseek-v4-flash
AI_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=your_key
AI_USAGE_LOG=.runtime/ai_usage.ndjson
AI_DECISIONS_DB=.runtime/ai_decisions.sqlite3
AI_CACHE_SEC=900
AI_DAILY_COST_LIMIT_USD=0.50
AI_DAILY_TOKEN_LIMIT=500000
AI_MAX_REQUESTS_PER_DAY=400
AI_RAG_TOP_K=3
AI_RAG_INCLUDE_VIRTUAL=1
```

`DISABLED` sends no requests, `SHADOW` records and evaluates recommendations
without changing the plan, and `APPLY` can affect the plan only after the
production gate. The dashboard switch changes only the advisory layer.

The decision store keeps feature snapshots, confidence, outcomes, and a short
validated rationale. After a position closes, verified episodes become local
RAG documents. Retrievals are linked to `decision_id`, cannot use future data,
and are disabled for incomplete or stale context. RAG never fine-tunes DeepSeek.

Daily request, token, and cost limits fail closed at the next UTC day. API keys,
raw prompts, full balances, order IDs, and full order books are not written to
the usage log.

## Verification

```bash
python3 -m compileall -q .
bash -n bin/supervisor_ctl.sh
PYTHONPATH=. pytest -q
```

Safe DRY/Testnet supervisor run:

```bash
python -m bin.ai_supervisor --testnet \
  --symbols SOLUSDT,ETHUSDT --base-script ./bin/autosize_universal.py
```

Mainnet LIVE requires `BOT_LIVE_CONFIRMED=YES`, explicit `--live`, and a passed
fail-closed preflight. Never skip the preflight or circuit breaker.

### Binance Spot Testnet smoke

Public checks require no credentials and are hard-coded to Testnet:

```bash
python -m bin.binance_testnet_smoke --mode public --symbol SOLUSDT
python -m bin.binance_testnet_smoke --mode authenticated --symbol SOLUSDT
```

The optional lifecycle test creates a minimal Testnet BUY, verifies OCO, and
cleans up the test position. It never uses existing holdings:

```bash
BOT_TESTNET_BUY_OCO_CONFIRMED=YES \
python -m bin.binance_testnet_smoke --mode buy-oco-restart --symbol SOLUSDT
```

`testnet_soak_monitor.py` can monitor a long read-only run for excess BUYs,
exposure, persistent halt, missing protection, and account/ledger drift.

## Safety and accounting

The order journal records BUY/OCO intent before a request. If an ACK is lost or
the process restarts, the executor reconciles Binance by `clientOrderId` and
exchange order ID before creating protection. An uncertain submission trips a
persistent circuit halt. Partial fills, gap-below-stop, and restart recovery
are fail-closed paths.

Money, quantities, fees, inventory, FIFO PnL, and risk metrics use `Decimal`.
Realized net PnL includes commissions, slippage, partial fills, exit reason,
duration, and exact AI attribution. Unresolved fills are excluded from AI PnL.

## Dashboard

Run locally with:

```bash
python -m bin.run_dashboard
```

The API listens on `127.0.0.1`. All `/api/*` routes require dashboard auth or
the explicitly configured trusted proxy. The UI supports 15 languages, stores
the selected language locally, and displays platform-aware telemetry. Raw logs
are disabled; sanitized logs are exposed only under Basic Auth at `/logs/`.

The Raspberry installer also exposes encrypted backup metadata and checksums at
`/backups/`; decrypted env files and keys are never public.

## Raspberry Pi installation and updates

Read [docs/RASPBERRY_PI_INSTALL.md](docs/RASPBERRY_PI_INSTALL.md) for the full
installation, migration, Testnet, backup, Telegram, and recovery runbook.

```bash
RELEASE_SHA="<40-character-reviewed-SHA>"
sudo bash deploy/install_raspberry_pi.sh install --commit "$RELEASE_SHA"
sudo bash deploy/update_raspberry_pi.sh update "$RELEASE_SHA"
```

The updater creates an encrypted backup, preserves `.env` and `.env.dashboard`,
updates only the requested fast-forward commit, validates Python/nginx, restarts
the services, and waits for a fresh heartbeat.

## Remaining engineering work

- extend event-driven replay with archived Binance depth/trade streams;
- improve matching, latency, maker/taker, and market-impact models;
- expand multi-period walk-forward and production approval statistics;
- continue reducing float arithmetic and broad exception handlers;
- run controlled long Testnet soak tests after executor or risk changes.

## Documentation and license

- [Introduction](docs/INTRODUCTION.md)
- [Raspberry Pi runbook](docs/RASPBERRY_PI_INSTALL.md)
- [Dashboard help](FRONT/help.html)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Trademark policy](TRADEMARKS.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [MIT License](LICENSE)
- [Disclaimer](DISCLAIMER.md)

Copyright: IURII Potekhin / Ladder Dragon. Public contact:
[LinkedIn profile](https://www.linkedin.com/in/ypotekhin/).
