<h1 align="center">Ladder Dragon</h1>

<p align="center"><strong>Adaptive Binance Spot execution with exchange-side protection, exact accounting, and fail-closed operations.</strong></p>

<p align="center">
  <img src="docs/assets/ladder-dragon-banner-v2.svg" alt="Ladder Dragon" width="420">
</p>

<p align="center">
  <a href="https://github.com/potekhinskill/Ladder-Dragon/releases/latest"><img src="https://img.shields.io/github/v/release/potekhinskill/Ladder-Dragon" alt="Latest release"></a>
  <a href="https://github.com/potekhinskill/Ladder-Dragon/actions/workflows/security.yml"><img src="https://github.com/potekhinskill/Ladder-Dragon/actions/workflows/security.yml/badge.svg?branch=main" alt="Security checks"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Raspberry%20Pi-ready-C51A4A?logo=raspberrypi&logoColor=white" alt="Raspberry Pi ready">
  <a href="https://github.com/potekhinskill/Ladder-Dragon/stargazers"><img src="https://img.shields.io/github/stars/potekhinskill/Ladder-Dragon?style=flat&logo=github&label=stars" alt="GitHub stars"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#why-ladder-dragon">Why Ladder Dragon</a> ·
  <a href="#verification">Verification</a> ·
  <a href="docs/RUNTIME_SAFETY_AND_REPORTING.md">Operations</a> ·
  <a href="#star-history">Star history</a> ·
  <a href="#dashboard">Dashboard</a> ·
  <a href="docs/RASPBERRY_PI_INSTALL.md">Raspberry Pi</a>
</p>

Ladder Dragon is an open-source Python trading system for Binance Spot. It
combines adaptive ladder entries, exchange-side OCO protection, exact
fee-aware FIFO accounting, restart reconciliation, per-symbol operational
reporting, replay and walk-forward verification, and a private Raspberry Pi
operations dashboard.

Current product version: **2.20.78**. The single version source is
`product_version.py`; releases follow [Semantic Versioning](https://semver.org/).
Project contact: [LinkedIn](https://www.linkedin.com/in/ypotekhin/).

> [!WARNING]
> This software can submit real exchange orders. It is not investment advice.
> DRY is the default and Mainnet LIVE requires a separate Testnet run, limit
> review, protection verification, and explicit confirmation.

> Ladder Dragon is an independent open-source project. It is not affiliated with,
> endorsed by, sponsored by, or officially associated with Binance. Binance and
> related marks belong to their respective owners.

## Why Ladder Dragon

| Problem | Ladder Dragon response |
| --- | --- |
| A fill can arrive while the process restarts | Durable intent journal and authoritative Binance reconciliation |
| A BUY without protection creates open-ended risk | Exchange OCO/STOP verification and fail-closed recovery |
| Cash spent can look like a trading loss | Separate cash flow, portfolio movement, and realized FIFO net PnL |
| A backtest can accidentally use future information | Sequential replay, walk-forward validation, and approval gates |
| AI can overstep deterministic limits | Advisory-only SHADOW/APPLY policy behind the same Risk Manager |
| A small server is hard to supervise | Read-only dashboard, encrypted backups, health checks, and Telegram summaries |

The objective is not to predict every tick. It is to make every decision
bounded, explainable, recoverable, and measurable before exposure is increased.

## How it works

1. Real-time market data updates deterministic indicators and the current
   trend/range/panic regime.
2. The strategy proposes a ladder; Risk Manager applies reserve, exposure,
   loss, freshness, spread, and gap constraints.
3. An order intent is persisted before submission. Exchange acknowledgements,
   fills, partial fills, and restarts reconcile against Binance.
4. Filled BUY quantity must receive verified exchange-side protection. A
   crossed OCO plan is rejected locally; a definitive LIVE attachment failure
   attempts a confirmed exact emergency flatten, while partial or uncertain
   outcomes remain halted.
5. Exact fills, commissions, slippage, lifecycle outcomes, latency, and SHADOW
   predictions feed reports, replay validation, and production approval.

## Built for observable operations

- **Start safely:** DRY and Testnet are the default path; LIVE needs explicit
  confirmation and reviewed exposure.
- **Know what happened:** the ledger keeps exact quantities, fees, realized PnL,
  open inventory, and unresolved evidence separate.
- **Recover deliberately:** restart, partial-fill, lost-ACK, OCO/STOP, and gap
  paths have fail-closed regression tests.
- **See the whole system:** the private dashboard combines host health, account
  state, orders, positions, risk, AI quality, logs, backups, and version drift.
  Windowed FIFO PnL is withheld when its required symbol history is incomplete,
  while cash flow and portfolio valuation remain explicitly separate.
- **Receive useful summaries:** an English Telegram digest reports yesterday,
  the last 7 complete days, and the last 30 complete days every morning.
  Symbols with incomplete FIFO history are explicitly excluded instead of
  contaminating exact totals; structural report failures send a deduplicated
  warning without financial figures.
- **Promote evidence, not optimism:** replay, walk-forward, Holm correction,
  release artifacts, and Pi verification gate deployment decisions.

## Project status

Ladder Dragon is an actively developed, experimental trading system. Version
**2.20.78** is the current source release. `main` is the only long-lived branch;
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
- durable BUY-lot and SELL-consumption idempotency keyed by exact Binance trade
  ID; a cursor replay cannot consume FIFO twice, and conflicting repeat payloads
  fail closed;
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
- fail-closed trade accounting: unknown commission value is never treated as
  zero, strict consumers reject SELL quantity beyond recorded inventory, and
  Binance quote assets are normalized before FIFO attribution;
- portfolio VaR based on timestamp-aligned 15-minute natural-log returns and
  Expected Shortfall based on explicit non-negative scenario losses; both
  gates remain disabled until an operator reviews a positive USDT limit;
- encrypted rotating backups and Telegram alerts for operational failures;
- an idempotent English morning digest with exact per-symbol FIFO accounting,
  explicit exclusions, and deduplicated fail-closed warnings.

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

## Quick start

> **New installation:** read the [introduction](docs/INTRODUCTION.md) before
> configuring exchange access.

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
AI_NEGATIVE_CACHE_SEC=30
AI_BLOCKED_SHADOW_INTERVAL_SEC=60
AI_DAILY_COST_LIMIT_USD=0.50
AI_DAILY_TOKEN_LIMIT=500000
AI_MAX_REQUESTS_PER_DAY=400
AI_RAG_TOP_K=3
AI_RAG_MIN_SCORE=0.75
AI_RAG_RETENTION_DAYS=365
AI_RAG_CANDIDATE_LIMIT=1000
AI_RAG_INCLUDE_VIRTUAL=0
```

`DISABLED` sends no requests, `SHADOW` records and evaluates recommendations
without changing the plan, and `APPLY` can affect the plan only after the
production gate. The dashboard switch changes only the advisory layer.
When Risk Manager blocks BUY but the authenticated snapshot remains healthy,
the supervisor stops every execution worker and continues a rate-limited,
read-only SHADOW plan. This preserves feature, forecast, usage, and
counterfactual evidence without starting a worker or placing, replacing,
cancelling, protecting, or flattening an order.

The decision store keeps feature snapshots, confidence, outcomes, and a short
validated rationale. Verified real closures and virtual SHADOW evaluations are
stored as separate evidence classes. Virtual documents are archived for
offline comparison and never enter retrieval, count as real PnL, or satisfy
the APPLY production gate. Retrievals are linked to `decision_id`, cannot use
future data, and are disabled for incomplete or stale context. RAG never
fine-tunes DeepSeek.

Real AI readiness is intentionally data-bound. Do not enable `APPLY` until the
configured minimum of exactly linked LIVE decisions has closed, unresolved
fills are zero, the edge confidence interval excludes zero, and AI is not worse
than the baseline. Code changes and virtual documents cannot manufacture this
evidence; it must accumulate in `SHADOW` from real closed lifecycles.
An unresolved AI attribution remains excluded from RAG and blocks readiness,
but it is distinct from unresolved inventory. Only an inventory/protection
uncertainty blocks execution after authoritative journal-to-Binance
reconciliation; unknown or legacy scope is treated as inventory fail-closed.

Daily request, token, and cost limits fail closed at the next UTC day. API keys,
raw prompts, full balances, order IDs, and full order books are not written to
the usage log.

## Verification

The unified verification harness runs the same fail-closed profiles locally, in
GitHub Actions and on a deployed Raspberry Pi. It composes the existing tools;
it does not duplicate trading or risk logic.

In a local checkout, the harness enters the repository `.venv` before importing
project dependencies even when it was accidentally started with host
`python3`. CI environments without a repository-local `.venv` continue with
their explicitly provisioned matrix interpreter.

```bash
python -m bin.verification_harness --profile local
python -m bin.verification_harness --profile release \
  --replay-validation .runtime/SOLUSDT-validation.json \
  --latency-log logs/execution_latency.ndjson
```

`local` runs release continuity, source compilation, the complete pytest suite,
the exact-numeric boundary audit and the tracked-secret scan. `release` adds replay,
walk-forward/approval, recovery, migration and deployment regressions.
Every run writes an owner-only JSON artifact under `.runtime` by default. The
versioned schema is `schemas/verification-report-v1.json`. Reports contain the
commit SHA, product version, checks, source hashes, allowlisted test totals,
replay errors, latency p50/p95, unresolved-fill count and exact lifecycle
evidence. Child stdout/stderr, environment variables, signed URLs and `.env`
contents are never copied into the artifact.

The mandatory `release_continuity` check uses the signed baseline in
`.release-lineage.json`. It rejects a skipped next version, multiple version
bumps before a tag, commits after a release tag without a new version,
non-annotated tags and nonlinear tag ancestry. Its allowlisted metrics form the
release manifest: previous/current version and SHA plus every included commit.

Exit status is `0` for `PASS`, `2` for a safely `BLOCKED` gate and `1` for
`FAILED`. An unknown profile or a missing mandatory executable is `BLOCKED`.

Testnet authenticated reads and mutations are separate approvals:

```bash
python -m bin.verification_harness --profile testnet \
  --confirm-authenticated-testnet

BOT_TESTNET_BUY_OCO_CONFIRMED=YES \
python -m bin.verification_harness --profile testnet \
  --confirm-authenticated-testnet \
  --confirm-testnet-mutation
```

The `testnet` profile always runs the public smoke, offline safety regressions
and network-free gap drill. The authenticated smoke remains blocked without
`--confirm-authenticated-testnet`; BUY/OCO/restart remains blocked unless both
the mutation flag and its existing exact environment confirmation are present.

After deploying an already tested 40-character commit, run the read-only Pi
profile on that host:

```bash
python -m bin.verification_harness --profile pi \
  --expected-sha 0123456789abcdef0123456789abcdef01234567 \
  --github-sha 0123456789abcdef0123456789abcdef01234567 \
  --release-report /home/bot/verification/verification-release.json \
  --runtime-status /run/mybot/ai_status.json \
  --user-stream-status /run/mybot/user_stream_SOLUSDT.json \
  --order-journal /home/bot/apps/binance_bot/db/order_intents.sqlite3 \
  --prediction-db /home/bot/apps/binance_bot/db/prediction_shadow.sqlite3 \
  --ai-decisions-db /home/bot/apps/binance_bot/db/ai_decisions.sqlite3
```

It requires an owner-provided `PASS` release artifact whose 40-character commit
matches `--expected-sha`, `--github-sha`, fetched upstream and deployed HEAD.
It then verifies services,
heartbeat, authenticated recovery, risk/journal reconciliation, user-stream
soak and the production-soak gate without changing orders, services, HALT
state or configuration. A Mainnet drill is a separate `mainnet-canary` profile
and remains blocked without its CLI flag and all existing exact environment
confirmations; it is never part of `local`, `release`, `testnet`, `pi` or CI.

The Pi profile is a production-approval gate, not merely a deployment smoke
test. A correctly deployed and safely running host can therefore report
`BLOCKED` rather than `FAILED` while evidence is incomplete. In particular,
an attribution-only unresolved fill leaves reconciled deterministic execution
available but still blocks RAG/approval; inventory/protection uncertainty
blocks execution as well. User-stream soak requires 24 hours plus a reconnect,
an order event and event-triggered authoritative REST reconciliation.
Production soak also requires three exact closed lifecycles, a fresh runtime,
no prediction backlog and a passing statistical gate.

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
REANCHOR_MAX_MARKET_GAP_PCT=0.0015
REANCHOR_MAX_PER_CYCLE=1
DEV_BUY_PCT=0.004
AUTO_ADAPT_ENABLE=1
ADAPT_DEV_BUY_COEF=0.6
ADAPT_MIN_PROFIT_COEF=0.6
ADAPT_MIN_FLOOR=0.0025
ADAPT_MAX_ENTRY_GAP_PCT=0.02
DIR_UP_DEV_MULT=0.80
DIR_DOWN_DEV_MULT=1.50
DIR_UP_TP1_MULT=1.00
DIR_DOWN_TP1_MULT=1.00
```

The deterministic ladder always receives an exact adaptive closest BUY. An
`UP` regime narrows the configured gap while keeping the order strictly below
market; a `DOWN` regime widens it. ATR adaptation may widen the gap and the
minimum-profit guard, but TP must still cover that guard within the configured
TP ceiling or the cycle fails closed. Eligible BUY levels are ranked from the
highest maker price downward before the target-count limit is applied, so the
adaptive closest BUY cannot be hidden behind deeper ladder levels. This initial
placement does not depend on prediction APPLY or a later re-anchor.

For a production observation run, the operator may lower
`REANCHOR_TRIGGER_PCT` to `0.0005` while keeping `ADAPTIVE_REANCHOR_MODE=SHADOW`.
The best candidate targets a 0.15% market gap, subject to the stricter age,
trigger, per-cycle step and count bounds. Do not promote that setting to
`APPLY` until its net expectancy gate passes.

### Technical prediction SHADOW

The supervisor records a separate observation-only prediction snapshot after
the deterministic worker has been launched. It uses only fully closed one-minute
bars and sanitized public L2/aggregate-trade data. Features include EMA slope
and distance, ADX/DI, ATR level and change, VWAP deviation, RSI, MACD histogram,
volume, taker-flow and order-book imbalance, spread, depth, acceleration and the
`TREND_UP`, `TREND_DOWN`, `RANGE` or `PANIC` regime.
The sanitized executor PANIC state and debounce-hit count are attached to the
same decision, allowing its later counterfactual outcome to measure whether the
current 1-minute trigger was protective or unnecessarily early.

For 1, 5 and 15 minute horizons the journal stores BUY-fill probability,
TP-before-STOP probability, expected net PnL after configured fee/slippage,
maximum adverse movement and estimated fill time. Every adaptive re-anchor
candidate stores both the proposed BUY and the original untouched BUY. Outcomes
are resolved only after the horizon closes; if TP and STOP occur in one OHLC
bar, STOP wins conservatively. A horizon whose required first bar has already
fallen outside retained history terminates as `INSUFFICIENT_HISTORY`; it is not
reported as a fill failure and does not remain pending forever. Public
`aggTrade` archives may recover such rows with
`bin.backfill_prediction_archive`, but only when companion metadata matches the
archive SHA-256 and every required one-minute interval is present. Each
recovered outcome retains that source hash and remains counterfactual SHADOW
evidence. Runtime telemetry also groups PANIC state, BUY distance, fill rate,
TP rate, net edge and adverse movement by regime and decision kind; this
reporting path always returns `apply_allowed=false`. Historical
candidates created before 2.20.14 do not contain immutable old/new plans and
are not reconstructed. Runtime telemetry includes the proposed-versus-original
fill count, TP count, net PnL edge and mean entry gap for re-anchor candidates.

The statistical gate remains reporting-only. It requires at least 120
independent timestamps, positive lower confidence bounds for both net expectancy
and paired baseline edge, Holm-corrected horizon/regime hypotheses, coverage of
all four regimes, acceptable drawdown and fill rate. Validation uses an
expanding walk-forward sequence: only older resolved samples may train a later
forecast. A passing report says `APPLY` is statistically eligible; it does not
enable anything automatically. Re-anchor still requires an explicit configured
`APPLY`; without a passing gate that setting is forced back to SHADOW. The
prediction layer itself cannot change CAP, BUY distance, TTL, TP or STOP.

#### Defensive prediction research contour

Prediction quality is measured in quote currency, not by direction accuracy
alone. The decision-value report compares the gate with the unchanged
`always trade` counterfactual and includes movement-weighted confusion plus the
capture rate for large DOWN moves.

Historical Binance one-minute archives can seed the research dataset:

```bash
python -m bin.prediction_history_backfill \
  --binance-klines-jsonl db/archives/multi-symbol-klines.jsonl \
  --output db/prediction-monthly-evidence.jsonl
```

Each input line contains `symbol` and the standard seven-field Binance `kline`.
Optional timestamped `agg_trade_imbalance`, `funding_rate` and `open_interest`
fields are accepted, but values after the snapshot are never used. Output rows
retain the source SHA-256. Features add short/long realized volatility and its
ratio, VWAP deviation/slope, cyclical hour/week fields, aggressive trade
imbalance, funding and open-interest change. Missing external evidence remains
explicitly unavailable rather than becoming a plausible zero. The public depth
recorder already captures a 1,000-level snapshot, contiguous `depth@100ms`
updates and `aggTrade` events.

The logistic challenger calibrates confidence on its latest chronological
holdout. Shallow gradient boosting and a three-state HMM run as transparent
offline challengers. Deterministic, statistical and LLM decisions are compared
on identical windows. LLM can add a veto but cannot override another veto;
predictor disagreement blocks BUY in the defensive ensemble.

```bash
python -m bin.monthly_prediction_report \
  --evidence-jsonl db/prediction-monthly-evidence.jsonl \
  --output db/prediction-monthly-report.json
```

The default cutoff is the end of the previous full Asia/Almaty month.
Walk-forward training requires every training label to predate the test
snapshot. The SHA-256-bound report remains `SHADOW` and cannot change
execution. `ladder-dragon-monthly-prediction.timer` runs only when its
sanitized evidence file exists and sends Telegram only when compact status
changes. Retraining produces an artifact only; APPLY or any risk expansion
still requires the statistical gate and separate operator approval.

### Net-expectancy strategy controls

The next-generation controls are implemented as independent `SHADOW` layers.
They cannot submit, cancel or resize an order until the same chronological
`STRATEGY` evidence passes the positive lower-CI, baseline, Holm, regime,
drawdown and fill-rate gate and the operator separately sets
`BOT_STRATEGY_CONTROLS_APPROVED=YES`.

- `bin.regime_pnl_report` attributes exact realized FIFO PnL to the regime
  known at BUY time and compares it with buy-and-hold and unchanged USDT.
  Missing lots, future/stale regime context or a missing end price block the
  report instead of inventing a result.
- The expectancy floor reads the authenticated Binance symbol commission
  schedule and covers BUY fee, SELL fee, both slippage estimates and a safety
  margin. It does not rely on a BNB discount remaining available at fill time.
- The execution state machine uses confirmed `RANGE`, `TREND_UP`,
  `TREND_DOWN`, `PANIC` and `RECOVERY` states. Hysteresis prevents threshold
  chatter; downtrend, panic and recovery preserve SELL/OCO protection while
  disabling new BUYs in `APPLY`.
- Inventory skew reduces only new managed BUY size as
  `1 - utilization^gamma`. The hard portfolio/symbol CAP, exchange filters,
  reserve and complete future OCO exposure remain absolute checks.
- The calibrated logistic, shallow boosting and three-state HMM models remain
  SHADOW challengers to the deterministic baseline and DeepSeek. Training rows
  are historical only; DeepSeek is never placed in the low-latency execution
  path.
- Dynamic multi-window correlation clusters and L2 spread/depth checks cap
  correlated symbols together. Adding symbols is an operator decision and
  does not happen automatically; a panic correlation cluster is treated as
  one exposure.

Example exact regime report:

```bash
python -m bin.regime_pnl_report \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db \
  --prediction-db /home/bot/apps/binance_bot/db/prediction_shadow.sqlite3 \
  --start-ms 1784937600000 --end-ms 1785024000000 \
  --benchmark-exit-fee-pct 0.001
```

The JSON output provides, for every regime, strategy net PnL, buy-and-hold,
USDT, realized drawdown, fill rate and sample counts. A zero-sample row is
explicitly retained so missing regime coverage is visible.

```dotenv
PREDICTION_SHADOW_ENABLED=1
PREDICTION_SHADOW_INTERVAL_SEC=60
PREDICTION_SHADOW_DB=/home/bot/apps/binance_bot/db/prediction_shadow.sqlite3
PREDICTION_FEE_PCT=0.00075
PREDICTION_SLIPPAGE_PCT=0.0005
BOT_STRATEGY_CONTROLS_APPROVED=NO
BOT_EXPECTANCY_MODE=SHADOW
BOT_MAKER_POLICY_MODE=SHADOW
BOT_REGIME_GATE_MODE=SHADOW
BOT_INVENTORY_SKEW_MODE=SHADOW
RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT=30
BUY_VWAP_HYSTERESIS_PCT=0.0002
BOT_STATISTICAL_REGIME_MODE=SHADOW
RISK_CLUSTER_GATE_MODE=SHADOW
```

`RISK_MANAGED_INVENTORY_HARD_CAP_<SYMBOL>` is mandatory before inventory
skew can enter APPLY; it never inherits the portfolio CAP. STRATEGY approval
compares the candidate with an explicit `NO_TRADE`/USDT baseline, while
REANCHOR approval requires the actual original order as its baseline. A
configured minimum net edge or TP below the authoritative round-trip cost
floor blocks APPLY instead of being silently widened. VWAP uses separate
entry and exit thresholds so boundary noise does not repeatedly toggle BUY.
Authoritative `BOT_BUY_FEE_PCT` and `BOT_SELL_FEE_PCT` reach the worker in
every mode for exact accounting; the execution-changing
`BOT_REQUIRED_EDGE_PCT` is exported only in APPLY and never in SHADOW.
`BOT_REGIME_MIN_HOLD_SEC` starts when each in-memory regime machine is created,
not at host boot, so restarting the supervisor cannot bypass recovery hold.
If inventory/regime scaling is enabled without a positive per-order CAP, the
supervisor emits `CAP-SCALING-INACTIVE` instead of silently pretending that
sizing controls are active.

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

A timeout while reading an existing OCO/OTOCO never authorizes cancellation:
the exchange-side protection is left unchanged and the symbol halts for later
authoritative reconciliation. A terminal partial TP/STOP is recorded once by
exchange order ID, excluded from exact lifecycle approval, and only the
remaining BUY quantity is eligible for replacement protection.

Signed POST/DELETE requests are never retried blindly by the HTTP transport.
A network loss or Binance 5xx after a mutation is one `UNKNOWN` attempt and is
resolved only through the durable intent and authoritative `clientOrderId`
reconciliation. Read-only signed requests have a bounded three-attempt budget.
HTTP 418 arms a process-wide local cooldown for Binance `Retry-After`; `-1021`
performs one server-time synchronization before a safe retry of the
definitively rejected request.

The complete operator-visible contract for protection, HALT versus SHADOW,
managed versus legacy inventory, dashboard PnL availability, Telegram digest
exclusions, and stable-log suppression is documented in
[Runtime safety and reporting](docs/RUNTIME_SAFETY_AND_REPORTING.md).
Package ownership, dependency direction, runtime entry points and the
remaining monolith register are documented in
[Architecture](docs/ARCHITECTURE.md).

Gap flatten first derives the exact residual from both OCO legs, cancels every
breached list, and polls Binance until those lists disappear and the required
base quantity is free. It reports success only after a `FILLED` MARKET response
covers that complete residual; timeout, partial execution or an unknown result
creates a persistent halt. Quantity is floored once to `stepSize` without
subtracting an extra `minQty`, so protection and emergency exits leave only
unavoidable sub-step exchange dust.

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
post-write verification. The library mutation boundary independently requires
and invokes that live revalidation; a caller cannot apply a stored plan by hash
alone. Existing lots are archived as `SUPERSEDED`, never deleted. See the
[Raspberry Pi runbook](docs/RASPBERRY_PI_INSTALL.md#8-legacy-holdings-cost-basis-import).

This workflow intentionally rejects incomplete exchange history, tradeable
transfers or deposits that cannot be explained by fills, surviving unpriced
lots, unpriced third-asset commissions, open symbol orders, and any balance
change during reconstruction or between preview and apply. An unexplained
remainder strictly below `LOT_SIZE.stepSize` is recorded as unmanaged dust and
is never assigned an invented price. Importing a basis does not automatically
enable holdings SELL or OCO management. If the plan reaches beyond the newest
trade persisted in the statistics database, apply records the exact cursor-gap
range in its audit row and returns a warning; historical reports for that range
remain explicitly incomplete rather than silently appearing exact.

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
ratio, price, exact quote-valued fees, slippage and latency with at least ten
terminal real order outcomes. Queue accuracy is explicitly labelled an
`L2_PRICE_LEVEL_FIFO_PROXY`, never exact L3. This
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

The notification-only Binance Spot User Data Stream observer is enabled by
default in LIVE after the same authenticated preflight; set
`BOT_USER_STREAM_SHADOW=0` for an explicit operational opt-out. Validate it on
Testnet before the first LIVE deployment. The observer uses the current signed
`userDataStream.subscribe.signature` WebSocket API method and stores only a
sanitized health snapshot under `/run/mybot/`. An `executionReport` can wake an
order check early, but it cannot place, cancel, protect, close, or account for an
order. Authenticated REST reconciliation remains authoritative and continues on
its normal interval when events are duplicated, late, missing, or the stream is
disconnected. The dashboard shows per-symbol connection state, transport age,
order-event count, duplicate and out-of-order counts, connection attempts,
reconnects and sanitized error class. It labels time since the first observation
as cumulative observation and reports the current WebSocket session duration
separately; planned executor rotations are not presented as one continuous
socket session. A transport heartbeat older than
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

### Low-latency execution modes

The executor has three independently gated acceleration layers. All default to
`OFF`, so upgrading cannot silently change the active canary:

- `BOT_FAST_MARKET_MODE=SHADOW` starts public `bookTicker`, `aggTrade`,
  `depth20@100ms` and closed `kline_1m` streams. It maintains an immutable
  Decimal snapshot with incremental EMA20, ATR14, VWAP, depth imbalance and
  signed trade flow. `APPLY` rejects a BUY when the snapshot is stale, the
  spread or market move is excessive, depth sequence regresses, or estimated
  net edge no longer covers fees and execution costs.
- `BOT_OTOCO_MODE=SHADOW` records the exact BUY/TP/STOP list that would be
  submitted. `APPLY` sends one Binance OTOCO order list, journals the working
  BUY and both pending SELL legs before mutation, and verifies all three exact
  exchange orders. A cancelled partial fill may receive a separate OCO only
  after Binance confirms that the original OTOCO list is fully terminated.
- `BOT_WS_TRADING_MODE=APPLY` routes supported submit/cancel/order-list
  mutations through one persistent Binance WebSocket API connection. It never
  retries an unknown mutation; the existing client/list identity recovery runs
  before any further action. REST remains authoritative for reconciliation.

LIVE `APPLY` additionally requires `BOT_FAST_MARKET_APPROVED=YES`,
`BOT_OTOCO_APPROVED=YES`, or `BOT_WS_TRADING_APPROVED=YES` for the corresponding
layer. HMAC remains supported. `BINANCE_KEY_TYPE=ED25519` accepts only an
absolute owner-only PEM path in `BINANCE_ED25519_PRIVATE_KEY_FILE`.

Adaptive re-anchor `APPLY` uses Binance `cancelReplace` with
`STOP_ON_FAILURE` and `ONLY_NEW`, after stopping the symbol worker and
committing the replacement intent. It rejects partial fills and any target
whose notional exceeds the hard CAP. A structured Binance
`FAILURE/NOT_ATTEMPTED` response is recorded as an exact no-op without a
symbol HALT. A lost acknowledgement runs bounded authoritative reconciliation;
the replacement is accepted in `NEW`, `PARTIALLY_FILLED`, or `FILLED` state.
If the exchange outcome remains uncertain, the intent stays `UNKNOWN` and
further mutations halt. Set `BOT_REANCHOR_CANCEL_REPLACE=0` only as an explicit
rollback to the legacy cancel/restart path.

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

<p align="center">
  <img src="docs/assets/dashboard-overview-sanitized.png" alt="Sanitized Ladder Dragon operations dashboard" width="1100">
</p>

<p align="center"><sub>Sanitized demonstration data. The image contains no live balances, account identifiers, orders, process identifiers, credentials, or operational timestamps.</sub></p>

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

Position protection is scoped explicitly: a confirmed OCO applies only to the
managed quantity covered by its verified SELL legs. Legacy account quantity is
shown separately. The 24-hour FIFO PnL card is unavailable, with affected
symbols named, whenever exact history cannot support the calculation.

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

Preserving `.env` is intentional: an update never imports new example values or
changes reviewed exposure automatically. After every release, compare the
names in `.env.example` with the installed `.env` without printing values.
Add new non-secret controls only after review. For example, inventory skew
requires an explicit positive
`RISK_MANAGED_INVENTORY_HARD_CAP_<SYMBOL>`; its absence is diagnostic in
SHADOW and fail-closed in APPLY.

Definitive Binance authentication rejections (`401`, `403`, `-2014`, `-2015`
or `-1022`) keep the supervisor alive in `AUTH_BACKOFF` with BUY blocked. Retry
intervals grow from 60 to 120, 240, 480 and at most 900 seconds; the watchdog
recognizes the fresh fail-closed heartbeat and does not reset that delay.
`BINANCE_AUTH_BACKOFF_INITIAL_SEC` and `BINANCE_AUTH_BACKOFF_MAX_SEC` may be
configured within the validated 30–3600 second safety bounds.
Retry state is stored in `BINANCE_AUTH_STATE_FILE`, so a process or host restart
does not reset the schedule. `BINANCE_PUBLIC_IP_ENDPOINTS` must contain at
least two independent HTTPS hosts; a local fingerprint is accepted only when
two sources agree, and only a SHA-256 fingerprint is retained. A changed
fingerprint enters
`IP_BLOCKED`; update the Binance whitelist first, then explicitly accept the
current fingerprint without displaying the address:

```bash
sudo -u bot env PYTHONPATH=/home/bot/apps/binance_bot \
  /home/bot/apps/binance_bot/.venv/bin/python \
  /home/bot/apps/binance_bot/bin/ip_guard.py accept-current
```

Temporary Binance time RTT, network and `-1021` clock-window failures keep the
supervisor alive in `PREFLIGHT_BACKOFF`, with BUY blocked and heartbeat
updates throughout the bounded delay. A signed read rejected with `-1021`
performs one authoritative server-time resynchronization and one newly signed
retry. `BINANCE_PREFLIGHT_BACKOFF_INITIAL_SEC` and
`BINANCE_PREFLIGHT_BACKOFF_MAX_SEC` default to 30 and 300 seconds. Repeated
CONFIG, filters, persistent-HALT and unchanged recovery diagnostics are emitted
at most once per hour while runtime JSON remains current every cycle.

LIVE also reconciles durable nonterminal order IDs before `RUNNING`. Every
durably protected BUY is checked against the exact Binance OCO order-list ID,
client ID, symbol, both SELL legs, leg types and active statuses. A mismatch or
an executed BUY without verified protection creates a manual HALT and remains
`RECOVERY_BLOCKED`. The same authoritative check runs continuously. Generic
ladder TTL/off-ladder cleanup owns BUY orders only and can never cancel a
protective SELL/OCO leg. An unresolved inventory/protection fill blocks new BUY
orders; a verified protected lot with missing `decision_id` blocks AI
attribution, RAG, and approval without indefinitely blocking deterministic
execution. The dashboard reports both categories separately.

An operator who intentionally stops trading can publish an explicit state:

```bash
sudo env PYTHONPATH=/home/bot/apps/binance_bot \
  /home/bot/apps/binance_bot/.venv/bin/python \
  -m bin.maintenance_state set --reason "Scheduled maintenance"
sudo env PYTHONPATH=/home/bot/apps/binance_bot \
  /home/bot/apps/binance_bot/.venv/bin/python \
  -m bin.maintenance_state clear
```

The dashboard then shows `INTENTIONALLY_STOPPED`, and the watchdog suppresses
restart alerts. A malformed marker fails closed. Updates preserve the previous
service state and create or clear this marker accordingly.

Generate a read-only soak verdict after the observation period:

```bash
PYTHONPATH=. .venv/bin/python -m bin.production_soak_report \
  --required-hours 24 --required-lifecycles 3 --required-predictions 100 \
  --output db/production-soak-report.json
```

The command returns exit status `2` until every requirement is genuinely met.
On Raspberry Pi, `ladder-dragon-soak-audit.timer` repeats the audit every 15
minutes, creates a host-local Ed25519 detached signature and sends Telegram
only when the approval/check state changes. Approval additionally requires LIVE
Mainnet and the prediction statistical gate; the timer cannot enable APPLY.

## Remaining engineering work

- run the bounded Mainnet canary on each materially changed executor release;
- collect at least three natural, exactly linked BUY/OCO/TP-or-STOP lifecycles
  and a clean 24–48 hour SOLUSDT soak before increasing LIVE scope;
- keep collecting exchange archives until the replay-readiness audit passes,
  including source-linked validation against exact live lifecycle outcomes;
- validate the existing dynamic-spread, queue-progress and volume-impact models
  against multi-regime archives and measured `executionReport` latency;
- collect enough exact out-of-sample decision-value evidence to compare every
  prediction challenger across all market regimes;
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
order. It covers full and partial STOP residuals, bounded OCO release polling,
confirmed complete MARKET quantity, uncertain OCO-cancel acknowledgement,
persistent halt state, and restart survival:

```bash
PYTHONPATH=. .venv/bin/python -m bin.binance_testnet_smoke \
  --mode gap-drill --symbol SOLUSDT
```

The dashboard and `/api/trading/overview` expose exact natural lifecycle
evidence as `closed_exact / required`. Only an exchange-verified OCO leg with a
terminal `FILLED` status can increment it; partial and unresolved fills do not.
Open canary lots are shown separately from legacy inventory, including an
explicit journal-versus-Binance protection mismatch. Historical virtual RAG
documents are labeled archived and are not included in retrieval.
For mixed inventory, confirmed protection is scoped only to the managed lot;
legacy quantity is explicitly marked unmanaged and outside that OCO. Average
entry, unrealized PnL and drawdown remain unavailable until sourced exact lots
cover the full Binance account quantity.

## Star history

<p align="center">
  <a href="https://github.com/potekhinskill/Ladder-Dragon/stargazers">
    <img src="https://potekhinskill.github.io/Ladder-Dragon/star-history.svg" alt="Ladder Dragon GitHub star history" width="960">
  </a>
</p>

The chart is rebuilt daily from the official GitHub Stargazers API and
published through GitHub Pages without creating a metrics branch. It contains
only dates and cumulative counts; account names are never published. The stars
badge at the top remains the live count between chart updates.

## Documentation and license

- [Introduction](docs/INTRODUCTION.md)
- [Raspberry Pi runbook](docs/RASPBERRY_PI_INSTALL.md)
- [Runtime safety and reporting](docs/RUNTIME_SAFETY_AND_REPORTING.md)
- [Validated engineering decisions](DECISIONS.md)
- [Engineering mistakes and root causes](MISTAKES.md)
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
