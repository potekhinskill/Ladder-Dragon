<h1 align="center">Ladder Dragon — Binance Spot Grid Bot</h1>

<p align="center">
  <img src="docs/assets/ladder-dragon-banner-v2.svg" alt="Ladder Dragon" width="420">
</p>

<p align="center">
  <a href="https://github.com/potekhinskill/Ladder-Dragon/releases/latest"><img src="https://img.shields.io/github/v/release/potekhinskill/Ladder-Dragon" alt="Latest release"></a>
  <a href="https://github.com/potekhinskill/Ladder-Dragon/actions/workflows/security.yml"><img src="https://github.com/potekhinskill/Ladder-Dragon/actions/workflows/security.yml/badge.svg?branch=main" alt="Security checks"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
</p>

> **New installation:** start with the [introduction](docs/INTRODUCTION.md).

Ladder Dragon is an open-source Python project for adaptive ladder trading on
Binance Spot. It builds BUY/SELL grids, uses ATR/EMA/VWAP/ADX regimes, manages
OCO protection, and records trading statistics in SQLite. Production secrets,
real backups, and private parameters are never committed.

Current product version: **2.20.13**. The single version source is
`product_version.py`; releases follow [Semantic Versioning](https://semver.org/).
Project contact: [LinkedIn](https://www.linkedin.com/in/ypotekhin/).

> [!WARNING]
> This software can submit real exchange orders. It is not investment advice.
> DRY is the default and Mainnet LIVE requires a separate Testnet run, limit
> review, protection verification, and explicit confirmation.

> Ladder Dragon is an independent open-source project. It is not affiliated with,
> endorsed by, sponsored by, or officially associated with Binance. Binance and
> related marks belong to their respective owners.

## Project status

Ladder Dragon is an actively developed, experimental trading system. Version
**2.20.13** is the current prepared release. `main` is the only long-lived branch;
feature branches use the `ladderdragon/*` namespace.

DRY and Binance Spot Testnet are the supported starting modes. Mainnet LIVE is
available, but it is not a general production-readiness claim: every deployment
must pass its own account reconciliation, exchange-filter, BUY-fill,
OCO/STOP, restart-recovery, gap-watchdog, backup, and circuit-breaker checks.
No profitability is promised or implied.

The bounded Mainnet canary completed a real `BUY -> fill -> OCO TP/STOP ->
restart reconciliation -> cleanup SELL` lifecycle on `SOLUSDT`. Both OCO legs
were verified, the isolated canary position was flattened exactly, no open
orders remained, and the circuit breaker stayed clear. This validates the
bounded acceptance path; it does not establish profitability or authorize
larger exposure.

## Features

- adaptive percentage ladders for multiple symbols;
- market direction, ATR, EMA, VWAP, and ADX adaptation;
- optional AI recommendations for regime, ladder width, and CAP;
- per-order, per-symbol, portfolio, reserve, and correlation limits;
- a final LIVE BUY boundary that clamps every strategy/VWAP/BEAR/AI proposal to
  the smallest operator, Risk Manager, and per-symbol CAP; remainder allocation
  cannot bypass that boundary;
- OCO/STOP protection, partial-fill recovery, gap handling, and FIFO inventory;
- persistent PANIC state across executor restarts, immediate raw-signal BUY
  blocking in LIVE, and reconciled cancellation of remaining exposure, with
  partial fills retained for OCO/STOP protection; after a confirmed recovery
  with no tracked BUY, the observation-only worker exits so a fresh executor
  immediately re-runs every safety gate before considering replacement;
- durable order-lifetime diagnostics with TTL, limit distance, observed market
  range, execution quantity, and the exact cleanup reason;
- opt-in bounded BUY re-anchoring that refreshes only old, completely unfilled
  limits toward the current ladder, caps every price step and cancellation
  count, and never changes SELL/OCO protection or chases a falling ladder;
- SQLite decision history, cash/FIFO PnL, RAG retrieval, and reports;
- FastAPI dashboard for Raspberry health, balances, positions, orders, AI, and logs;
- separate 24-hour portfolio value change and realized FIFO net trading PnL,
  so mark-to-market movement is never presented as bot earnings;
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
validated rationale. Verified real closures and virtual SHADOW evaluations are
stored as separate evidence classes. Virtual documents may support offline
comparison but never count as real PnL or satisfy the APPLY production gate.
Retrievals are linked to `decision_id`, cannot use future data, and are disabled
for incomplete or stale context. RAG never fine-tunes DeepSeek.

Real AI readiness is intentionally data-bound. Do not enable `APPLY` until the
configured minimum of exactly linked LIVE decisions has closed, unresolved
fills are zero, the edge confidence interval excludes zero, and AI is not worse
than the baseline. Code changes and virtual documents cannot manufacture this
evidence; it must accumulate in `SHADOW` from real closed lifecycles.

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

Adaptive re-anchoring is `OFF` by default. Use `SHADOW` to record candidates
without canceling an order, then test them against archived replay and real
order-lifetime evidence before selecting `APPLY`. A refresh cancels only an old,
completely unfilled BUY when the current ladder has moved sufficiently higher;
the replacement remains below market and advances by a bounded step.
Partial BUYs, SELLs, OCO legs, panic controls, VWAP filters, CAP and the exact
fee/spread/slippage/minimum-edge sell floor remain authoritative.
The worker reads average entry only from the verified exact-lot ledger; legacy
or incomplete history cannot delay a replacement BUY or authorize panic
recovery. The dashboard reports the effective mode, trigger, cumulative shadow
candidates and applied cancellations, plus the latest proposed price change.

```dotenv
ADAPTIVE_REANCHOR_MODE=OFF
REANCHOR_MIN_AGE_SEC=120
REANCHOR_TRIGGER_PCT=0.0025
REANCHOR_MAX_STEP_PCT=0.005
REANCHOR_MAX_PER_CYCLE=1
```

For a production observation run, the operator may lower
`REANCHOR_TRIGGER_PCT` to `0.0005` while keeping `ADAPTIVE_REANCHOR_MODE=SHADOW`.
Do not promote that setting to `APPLY` until its proposals have been reviewed.

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

### Bounded Mainnet canary

The separate Mainnet canary is an operator-only acceptance test, not a trading
strategy. It is restricted to `SOLUSDT`, hard-capped at `10 USDT`, preserves
`RISK_RESERVE_USDT`, refuses existing SOL orders, reloads its durable journal,
verifies both OCO legs, cancels protection, and sells only the balance delta it
created. Before mutation it reads the account's Binance commission schedule and
refuses an estimated BUY plus cleanup-SELL commission above `0.02 USDT`; the
operator cannot raise that budget above `0.03 USDT`. Actual fees are converted
to USDT and verified after cleanup. A successful drill cannot run twice for the
same product release. A post-BUY failure or unexpected fee-budget breach creates
a persistent circuit halt. It does not use or rewrite the cost basis of
pre-existing SOL holdings.

The drill is a deliberately bounded acceptance expense, not a profit test. Its
immediate cleanup may realize spread and fees; it never waits in an exposed
position merely to manufacture earnings. Run it only after a material executor
change, not on a schedule.

The drill proves one deterministic safety lifecycle; it must not be repeated to
manufacture a performance sample. Promotion beyond the SOLUSDT canary requires
at least three naturally completed strategy lifecycles with exact evidence for
`BUY fill -> OCO confirmed -> TP or STOP fill`, followed by at least 24 hours
(48 hours preferred) with zero CAP violations, unresolved fills, unprotected
managed positions, persistent halts, or reconciliation errors. Until both gates
pass, keep `SOLUSDT`, one target BUY, the `10 USDT` operator ceiling, and AI in
`SHADOW`. Pre-existing SOL inventory is classified as `legacy_unmanaged` when
automatic holdings protection is disabled; its gap-watchdog state is explicitly
`not_applicable_legacy_inventory`, not a false protection failure.

Stop the strategy and watchdog before the test. The normal service is restarted
only after a successful result:

```bash
(
cd /home/bot/apps/binance_bot
sudo systemctl stop mybot pi-watchdog-v3.timer pi-watchdog-v3.service

set +e
sudo -u bot env \
  BOT_LIVE_CONFIRMED=YES \
  BOT_MAINNET_CANARY_CONFIRMED=YES \
  BOT_MAINNET_CANARY_CLEANUP_CONFIRMED=YES \
  PYTHONPATH=. \
  .venv/bin/python -m bin.binance_mainnet_canary \
  --symbol SOLUSDT --notional-usdt 6 \
  --max-commission-usdt 0.02
RC=$?

if [ "$RC" -eq 0 ]; then
  sudo systemctl start mybot
  sudo systemctl start pi-watchdog-v3.timer
fi
exit "$RC"
)
```

The command writes a private report to `logs/mainnet_canary.ndjson` and a
separate journal to `db/mainnet_canary_order_intents.sqlite3`. It deliberately
leaves services stopped after failure; review the exact Binance state and the
circuit halt before any manual reset.

`testnet_soak_monitor.py` can monitor a long read-only run for excess BUYs,
exposure, persistent halt, missing protection, and account/ledger drift.

## Safety and accounting

The order journal records BUY/OCO intent before a request. If an ACK is lost or
the process restarts, the executor reconciles Binance by `clientOrderId` and
exchange order ID before creating protection. An uncertain submission trips a
persistent circuit halt. Partial fills, gap-below-stop, and restart recovery
are fail-closed paths.

Critical CAP, reserve, fees, inventory, FIFO PnL, risk reconciliation, supervisor
order adapters, and position guards use `Decimal`. Compatibility floats remain
only at indicator and telemetry boundaries and must not feed an order without
exact normalization. Realized net PnL includes commissions, slippage, partial
fills, exit reason, duration, and exact AI attribution. Unresolved fills are
excluded from AI PnL.

### Legacy holdings cost basis

Pre-existing holdings remain unmanaged until an operator imports a basis that
can be reconstructed from the account's complete Binance fill history. The
importer is preview-first: it values historical commissions at their trade
time, reconstructs remaining FIFO lots, requires the reconstructed quantity to
match the current account, and writes a private hash-bound plan without touching
the statistics database. Apply requires two explicit confirmations, a stopped
service, a fresh full Binance re-read with the same plan hash, and an atomic
post-write verification. Existing lots are archived as `SUPERSEDED`, never
deleted. See the [Raspberry Pi runbook](docs/RASPBERRY_PI_INSTALL.md#8-legacy-holdings-cost-basis-import).

This workflow intentionally rejects incomplete exchange history, tradeable
transfers or deposits that cannot be explained by fills, surviving unpriced
lots, unpriced third-asset commissions, open symbol orders, and any balance
change during reconstruction or between preview and apply. An unexplained
remainder strictly below `LOT_SIZE.stepSize` is recorded as unmanaged dust and
is never assigned an invented price. Importing a basis does not automatically
enable holdings SELL or OCO management.

New statistics databases are exact-only by default and never create financial
REAL columns or synchronization triggers. Existing databases retain their
compatibility schema during normal startup and update; they must be repaired,
audited, backed up and retired explicitly. First preview exact revaluation of
every legacy or unpriced commission against the matching Binance fill:

```bash
sudo -u bot PYTHONPATH=. .venv/bin/python -m bin.revalue_legacy_commissions \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db
```

Exit status 2 means at least one row could not be proven and nothing was
written. Apply only with `mybot` stopped, after reviewing the preview:

```bash
sudo systemctl stop mybot pi-watchdog-v3.timer
sudo -u bot env \
  BOT_COMMISSION_REVALUATION_CONFIRMED=YES \
  BOT_SERVICE_STOPPED_CONFIRMED=YES \
  BOT_RUN_DIR=/run/mybot \
  PYTHONPATH=. \
  .venv/bin/python -m bin.revalue_legacy_commissions \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db \
  --backup /var/lib/ladder-dragon/backups/bot_stats-before-fee-revalue.sqlite3 \
  --apply --confirm REVALUE-LEGACY-COMMISSIONS
```

The command requires exact `(symbol, trade_id)` evidence plus matching side,
price, quantity and timestamp. It restores commission provenance and net
quantity, values third-asset fees at trade time, recalculates inventory, and
creates a mode-0600 SQLite backup before its atomic update. It never submits an
exchange order. Then run the read-only retirement audit on the deployed host:

```bash
PYTHONPATH=. .venv/bin/python -m bin.audit_legacy_compatibility \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db
```

Exit status 2 means removal is unsafe. The command never edits the database or
deletes a legacy file. The JSON report separately lists physical REAL columns,
legacy synchronization triggers and old host paths. A clean exit authorizes a
preview, not an automatic migration. After every deployed host has passed,
stop the bot, keep the updater's encrypted backup, and create an additional
local SQLite backup while applying the explicit major-version migration:

```bash
sudo systemctl stop mybot pi-watchdog-v3.timer
sudo -u bot PYTHONPATH=. .venv/bin/python -m bin.retire_legacy_accounting \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db

sudo -u bot PYTHONPATH=. .venv/bin/python -m bin.retire_legacy_accounting \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db \
  --backup /var/lib/ladder-dragon/backups/bot_stats-before-v3.sqlite3 \
  --apply --confirm DROP-LEGACY-REAL-COLUMNS
```

The retirement command refuses missing exact values, legacy/unpriced commission
provenance, old host paths, an existing backup target, or a failed integrity
check. Existing 2.x databases are not rewritten by normal startup or update.

### Archived order-book calibration

Binance's [official downloadable Spot public data](https://github.com/binance/binance-public-data)
contains trades and candles, but not historical Spot order-book depth.
`bin.record_depth_archive` therefore
captures a public REST depth snapshot followed by the official 100 ms diff-depth
and aggregate-trade streams. It requires a bridge to the snapshot update ID,
rejects every later sequence gap, writes no credentials, and publishes both the
JSONL archive and its SHA-256 metadata atomically.

`bin.calibrate_replay` consumes that archive, normalized fixtures, or archives
that also contain execution reports. The optional sanitized execution-latency
log correlates the durable pre-POST intent timestamp with the locally received
`NEW executionReport`; cancellations and later fills are never presented as
order-acknowledgement latency. It produces source-hashed estimates for
spread, slippage, participation, partial fill, latency and market impact.
Reports label latency as either `public_event_receive` or `execution_report`:
public event transit is a measurable proxy, not an order-acknowledgement latency
claim. `bin.backtest --calibration` refuses an ineligible report and verifies
the archive hash when `--archive` is supplied.

```bash
PYTHONPATH=. python -m bin.record_depth_archive \
  --symbol SOLUSDT \
  --output .runtime/SOLUSDT-depth.jsonl \
  --duration-sec 3600
PYTHONPATH=. python -m bin.calibrate_replay .runtime/SOLUSDT-depth.jsonl \
  --execution-latency-log logs/execution_latency.ndjson \
  --output .runtime/SOLUSDT-calibration.json
PYTHONPATH=. python -m bin.validate_replay_outcomes \
  .runtime/SOLUSDT-depth.jsonl \
  --execution-log logs/execution_latency.ndjson \
  --calibration .runtime/SOLUSDT-calibration.json \
  --output .runtime/SOLUSDT-validation.json
PYTHONPATH=. python -m bin.backtest data/SOLUSDT-1m.csv \
  --archive .runtime/SOLUSDT-depth.jsonl \
  --calibration .runtime/SOLUSDT-calibration.json \
  --output .runtime/SOLUSDT-backtest.json

# Locate legacy reports invalidated by the corrected bps conversion.
PYTHONPATH=. python -m bin.audit_backtest_reports .runtime

# Require several days, distinct volatility regimes and measured order latency.
PYTHONPATH=. python -m bin.audit_replay_readiness \
  --validation-report .runtime/SOLUSDT-validation.json \
  .runtime/calibrations/*.json
```

Current reports contain the engine version, complete simulation configuration,
input hashes and `market_impact_bps_divisor=10000`. The audit command exits 2
when a legacy report used non-zero market impact and therefore must be rerun.
Reports with zero impact are marked legacy but are unaffected by that specific
correction.

The replay-readiness audit exits 2 until it sees at least three unique source
archives spanning two calendar days, low/normal/high volatility regimes, no
ineligible calibration, at least ten real execution samples, and at least one
archive with measured intent-to-`executionReport` latency. It also requires a
source-hash-linked validation report comparing predicted fill direction, fill
ratio, price and latency with at least ten terminal real order outcomes. This
prevents a short smoke capture or an unvalidated model from being presented as
production-quality calibration.

On Raspberry Pi, `ladder-dragon-depth-archive.timer` records a 15-minute public
sample every hour and retains seven days by default. Optional, non-secret
overrides belong in `/etc/ladder-dragon/depth-archive.conf`; the wrapper removes
all exchange and AI credentials from its environment before starting. This
build also models the observed dynamic book spread, configurable queue progress
from depth cancellations ahead, public trades consuming queue, and volume-scaled
market impact. These remain empirical approximations, not a claim that replay
can identify other participants or predict future execution.

Replay reports identify this fidelity as `L2_PRICE_LEVEL_FIFO_ESTIMATE` with
`exact_l3=false`. Public trades have one conserved quantity and can consume a
resting local FIFO queue only at the reported price. A local order receives a
taker fill only when it reaches the venue; subsequent book movement cannot
silently reclassify it. `bin.backtest --require-l3` fails closed because public
Binance Spot depth has price levels but no individual resting-order IDs.

### User Data Stream shadow observer

Set `BOT_USER_STREAM_SHADOW=1` only after Testnet validation to add Binance Spot
User Data Stream notifications. The observer uses the current signed
`userDataStream.subscribe.signature` WebSocket API method and stores only a
sanitized health snapshot under `/run/mybot/`. An `executionReport` can wake an
order check early, but it cannot place, cancel, protect, close, or account for an
order. Authenticated REST reconciliation remains authoritative and continues on
its normal interval when events are duplicated, late, missing, or the stream is
disconnected. The dashboard shows per-symbol connection state, transport age,
order-event count, duplicate and out-of-order counts, connection attempts,
reconnects and sanitized error class. A transport heartbeat older than
`DASHBOARD_USER_STREAM_STALE_SEC` (180 seconds by default) is explicitly marked
stale even if its last stored state said `connected`. PING, PONG and data frames
update this heartbeat, so a quiet healthy account is not marked stale merely
because no order event occurred.
Sanitized counters and the first observation time survive short executor
sessions in `/run/mybot`; credentials, payloads and order details are never
restored. The subscription timestamp reuses the REST transport's Binance
server-time offset. Malformed frames are counted and discarded without
reconnecting, while
a session with no frames for `BOT_USER_STREAM_IDLE_TIMEOUT_SEC` (90 seconds by
default) is reconnected. Health snapshots are retained in memory for every
frame but written to disk no more frequently than
`BOT_USER_STREAM_STATE_WRITE_SEC` (five seconds by default), except for material
counter or connection-state changes. This avoids per-frame SD-card writes on
Raspberry Pi without weakening REST reconciliation.

After a real soak, run the read-only gate:

```bash
PYTHONPATH=. .venv/bin/python -m bin.audit_user_stream_soak \
  --minimum-hours 24 \
  /run/mybot/user_stream_SOLUSDT.json
```

The production audit requires a reconnect, an order event and proof that the
event woke an authoritative REST reconciliation. Diagnostic-only
`--allow-no-*` switches can explain incomplete evidence but cannot justify a
promotion. Exit status 2 means duration, freshness or operational drill evidence
is incomplete. Passing does not promote WebSocket data to a source of truth.

AI APPLY has a separate read-only evidence audit. Exit status 2 means the
database does not yet prove enough real closed decisions, validated real RAG
episodes, a strictly positive edge confidence interval, an acceptable stop
rate, and zero unresolved fills:

```bash
PYTHONPATH=. .venv/bin/python -m bin.audit_ai_readiness \
  --db db/ai_decisions.sqlite3 \
  --symbol SOLUSDT
```

Virtual RAG episodes remain visible for analysis but never satisfy this gate.

Existing holdings are never assigned an invented cost basis. A position without
provable exchange history stays `legacy_unmanaged` with
`unverified_legacy_history`; enabling the archive recorder or User Data Stream
does not authorize holdings SELL/OCO management.

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

Updates require a signed commit and a pinned maintainer fingerprint. See the
[Raspberry Pi runbook](docs/RASPBERRY_PI_INSTALL.md) before the first update.
Maintainers must follow the [signed release procedure](docs/RELEASING.md).

The current release-signing fingerprint is:

```text
808B9F52CB6C08901703EF7C113144122F1830A0
```

Normal updates read this trust anchor only from root-owned
`/etc/ladder-dragon/update-trust.conf`. Environment variables cannot disable
signature verification. Unsigned recovery requires the separate interactive,
journaled, one-use break-glass procedure described in the runbook.

The updater creates an encrypted backup, preserves `.env` and `.env.dashboard`,
updates only the requested fast-forward commit, validates Python/nginx, restarts
the services, and waits for a fresh heartbeat.

## Remaining engineering work

- run the bounded Mainnet canary on each materially changed executor release;
- collect at least three natural, exactly linked BUY/OCO/TP-or-STOP lifecycles
  and a clean 24–48 hour SOLUSDT soak before increasing LIVE scope;
- keep collecting exchange archives until the replay-readiness audit passes,
  including source-linked validation against exact live lifecycle outcomes;
- validate the existing dynamic-spread, queue-progress and volume-impact models
  against multi-regime archives and measured `executionReport` latency;
- expand multi-period walk-forward and production approval statistics;
- keep the single finite-only numeric compatibility boundary isolated from
  financial state. Supervisor, worker, AI context, order and OCO/protection
  modules contain no direct binary-float conversion calls; indicator and legacy
  JSON consumers must use the audited boundary explicitly;
- retain only the four tested broad exception boundaries: panic fail-closed,
  gap-watchdog fail-closed, filled-BUY protection, and post-mutation Mainnet
  canary containment;
- run `bin.audit_legacy_compatibility` on every deployed host before proposing a
  major release that removes REAL accounting columns or legacy configuration;
- keep AI in SHADOW until both realized lifecycle statistics and at least five
  validated real RAG episodes pass the production policy gate;
- run controlled long Testnet soak tests after executor or risk changes.

The local gap-watchdog drill is network-free and never creates an exchange
order. It covers full and partial STOP residuals, uncertain OCO-cancel
acknowledgement, persistent halt state, and restart survival:

```bash
PYTHONPATH=. .venv/bin/python -m bin.binance_testnet_smoke \
  --mode gap-drill --symbol SOLUSDT
```

The dashboard and `/api/trading/overview` expose exact natural lifecycle
evidence as `closed_exact / required`. Only an exchange-verified OCO leg with a
terminal `FILLED` status can increment it; partial and unresolved fills do not.

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
