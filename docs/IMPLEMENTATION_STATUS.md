# Implementation status

This document describes the code in version **2.20.248**.
It does not describe future plans as completed work.

An implemented function is not automatically approved for LIVE use.
The configured mode and its evidence gate remain authoritative.

## Runtime status

| Area | Implemented behavior | Default or approval state |
| --- | --- | --- |
| Execution | Decimal-only Binance Spot planning, orders, cancel-replace, and recovery | DRY or Testnet first |
| Protection | Verified OCO legs, confirmed breakeven re-arm, gap flatten, and persistent HALT | Required for managed fills |
| Accounting | Exact FIFO lots, exact AI fills, fee provenance, risk streaks, and cursor audits | Fail closed on incomplete evidence |
| Replay | Separate order validation and read-only calibration cohorts with immutable fingerprints | L2 model, not exact L3 |
| Prediction | 1, 5, and 15 minute SHADOW outcomes | Enabled for evidence only |
| Market scenarios | 1-hour through monthly closed-candle outcomes | SHADOW only |
| Experiments | Diagnostic cohorts and one preregistered SOL execution-episode cohort | SHADOW only |
| CHAMPION | Append-only activation of one confirmed policy per symbol | No active policy by default |
| Statistical approval | Walk-forward, confidence intervals, regime checks, and Holm correction | Must pass before APPLY |
| AI advice | Validated DeepSeek, OpenAI, or compatible provider response | Disabled by default |
| RAG | Hybrid similarity, retention, bounded candidates, and real-only retrieval | Virtual records stay archived |
| Fast market data | `bookTicker`, `aggTrade`, and depth snapshots | OFF by default |
| WebSocket trading | Signed request transport and reconciliation | OFF and separately approved |
| OTOCO | Atomic BUY with symmetric ACK-loss recovery | OFF and separately approved |
| User Data Stream | Independent observer, reconnect-rate gate, drill, and versioned soak evidence | v4 epoch classifies reconnect causes |
| Dashboard | Read-only account, canonical FIFO PnL, risk, AI, positions, and host data | Private authenticated access |
| Reports | Daily trading digest, monthly prediction report, and signed soak report | Scheduled by systemd |
| Deployment | Signed update, atomic verified backup publication, rollback, and asset verification | Exact 40-character SHA required |

## Strategy-control defaults

The example configuration uses these modes:

| Control | Default |
| --- | --- |
| Adaptive re-anchor | `OFF`; transformed BUY ranks remain unique |
| Expectancy control | `SHADOW` |
| Maker policy | `NOT_IMPLEMENTED`; promotion requires a maker execution model |
| Regime gate | `SHADOW` |
| Inventory skew | `SHADOW` |
| Statistical regime | `SHADOW` |
| Correlation cluster gate | `SHADOW` |
| Fast market gate | `OFF` |
| OTOCO | `OFF` |
| WebSocket trading | `OFF` |
| AI advisor | disabled, with mode `SHADOW` |

`SHADOW` records evidence and does not change an order.

The scenario engine applies identical rules to each configured symbol.
It reports each symbol and timeframe separately.
Scenario weights remain uncalibrated until independent outcomes pass the statistical gate.
`APPLY` requires the applicable approval variable and statistical evidence.

## Prediction evidence

The prediction layer records these outputs for each horizon:

- probability that the proposed BUY fills;
- probability that TP occurs before STOP;
- expected net PnL after fees and slippage;
- maximum adverse movement;
- estimated time to fill;
- the result of the unchanged baseline plan.

Each settled return requires a successful historical price lookup.
A failed lookup keeps that horizon pending for the next cycle.
The diagnostic includes only the symbol, horizon, and error type.
Settlement selects bounded oldest and newest due work from the full history.
The historical price must come from the exact minute containing the horizon.

Future outcomes are normal pending work.
Only overdue or unrecovered expired outcomes block the backlog gate.
The soak report applies its expiration checks to the audited runtime window.

SOLUSDT version twenty-one uses one fixed 48-basis-point candidate and a 90-minute entry lifetime.
Its primary endpoint is 360 minutes.
The 300-minute result is diagnostic only.
The SHADOW evidence notional is fixed at 6 USDT.
CHAMPION exposure limits require a separate reviewed activation.
ETHUSDT version fifteen and BTCUSDT version fourteen remain diagnostic only.
Their evidence cannot enter confirmation.

The online episode model reads one-minute public depth and aggregate trades.
It models conservative LIMIT_MAKER queue position, partial fills, missed fills, and adverse selection.
It models the LIMIT_MAKER take-profit leg and the STOP_LOSS_LIMIT trigger separately.
It also models stop gaps, unfilled stop limits, emergency flattening, and exact account fees.
One episode can run at a time.
The next episode starts after the prior episode becomes terminal.
The database stores compact starts and terminal results.
It does not store the raw L2 stream.

Historical data selects the fixed SOL candidate and estimates variance only.
The fixed candidate does not use online training.
An operator command freezes its exact policy before live confirmation.
Confirmation accepts only episodes that start after the frozen boundary.
It also requires the frozen candidate and execution-model fingerprints.

The net-expectancy gate uses a preregistered betting e-process.
It supports continuous review without invalid repeated testing.
The one-sided confidence bound must remain positive after fees.
The gate also checks fill rate, drawdown, and regime safety.
PANIC flatten PnL enters the mean and drawdown.
PANIC vetoes are terminal unfilled attempts in the fill denominator.
RECOVERY and PANIC cannot start an entry episode.
Version twenty-one preregisters RANGE as its only executable entry regime.
RANGE requires twelve filled episodes and a positive confidence bound.
Every other regime blocks CHAMPION BUY and keeps position protection active.
Residual PANIC exposure remains a separate safety failure.
The confirmation deadline is 14 days.
The design also stops after 300 terminal episodes.
An impossible design becomes ready for REJECTED finalization before either limit.

Promotion also requires strict reusable engine replay against sanitized real order reports.
The validation requires at least ten covered terminal orders.
It requires a filled LIMIT_MAKER order and a filled STOP_LOSS_LIMIT order.
The validation compares fills, ratios, prices, latency, fees, and slippage.
Readiness requires three archives spanning two days.
The archives must cover low, normal, and high volatility.
At least one archive must contain measured order latency.

The first gate evaluates the complete candidate strategy.
All active candidates use the same entry scope.
The active-entry diagnostic therefore uses the same cohort.

Diagnostic prediction cohorts retain their existing walk-forward training rules.
The SOL version-twenty-one fixed rule has no cold-start training delay.
Historical rows cannot enter its live confirmation inference.
Statistical gates stream the complete journal in append order.
Control readers retain bounded binding and non-binding evidence groups.
Classified lifecycle and execution-episode evidence remains append-only in SQLite.
Episode starts and results are derived SHADOW evidence.
Imported model validations are authoritative promotion artifacts.
Validation batch manifests and attempt ledgers are authoritative operator artifacts.
The CHAMPION probation state is authoritative safety state.
The episode store has a fixed limit of 250,000 starts.
The validation store has a fixed limit of 1,024 reports.
Automated retention does not delete this evidence.
Automated retention does not delete validation batch artifacts.
Automated retention does not delete CHAMPION probation state.
The prediction database backup includes all these records.
No scheduled maintenance changes these append-only tables.
Capacity exhaustion fails closed and requires a reviewed schema change.

New plan semantics use a new experiment identifier.
Historical experiment rows remain available and never mix with the active generation.

Control evidence records whether each control changed its baseline plan.
Binding cohorts measure control effects.
Full cohorts enforce safety and non-inferiority.
Inventory promotion requires a sequential portfolio replay.
Expectancy approval requires positive binding edge and net expectancy.
Regime approval also requires full-cohort regime coverage.
Maker promotion remains unavailable until evidence stores fills, missed fills, queue state, and adverse selection.
The runtime does not record maker evidence before that model exists.
Control metadata version four verifies candidate and baseline plan fingerprints.
Expectancy evidence uses 300-minute and 360-minute horizons.
Regime evidence uses 15-minute and 360-minute horizons.
Each control report estimates binding frequency and its evidence-ready time.
The dashboard shows readiness in days and the current waiting reason.
Observation-only inventory reports `NOT_APPLICABLE`.
An activated CHAMPION fixes entry gap, entry lifetime, target, stop, and maximum exposure.
The first CHAMPION uses one 6 USDT order and one 6 USDT managed position.
The worker verifies the active registry record before LIVE execution.
Runtime controls can only reduce risk, block BUY, cancel BUY, or flatten.
New CHALLENGER generations remain in SHADOW until independent confirmation and explicit activation.
Each activation receives a new version and fingerprint.
Activation binds the reviewed exposure limits to the policy fingerprint.
Activation requires a clean checkout at the exact published annotated release tag.
Each order intent records the active activation and policy fingerprints.
The authoritative activation registry has no automatic retention.
Each new CHAMPION starts a 24-hour probation period.
Probation limits entries, turnover, and account-equity loss.
Probation requires one exact BUY-to-protective-exit lifecycle before PASS.
An equity-loss breach creates persistent HALT.
The worker fails closed without a current probation result.

The public depth service records consecutive 55-minute sessions.
The service restarts after a recorder failure.
Seven-day rotation bounds disposable public archive growth.
Each validation drill also stores its complete order-lifecycle archive.
Replay validation matches the reusable order engine, fee schedule, and simulator domain.
Candidate gap, lifetime, target, and stop evidence remains inside SHADOW confirmation.

Attributed AI fills store monetary values as exact text.
Each fill records whether its slippage value is verified.
Unknown slippage makes financial evidence incomplete.
Incomplete evidence cannot enter readiness, RAG, or dashboard PnL totals.

Re-anchor is not a promotion candidate.

Inventory control reports `STATEFUL_MODEL_REQUIRED` for execution symbols.
Independent order outcomes cannot approve this state-dependent policy.
Maker control approval stays blocked until evidence includes real maker execution semantics.
The required semantics include fills and missed fills.

No first-gate result can set `apply_allowed=true`.
No confirmed result changes execution without a separate halted activation.

## Current approval boundary

The repository does not claim general production approval or profitability.
A bounded Mainnet canary proves only its exact small acceptance lifecycle.

Promotion still requires these items:

- exact natural BUY to OCO to TP or STOP lifecycles;
- zero unresolved inventory or protection fills;
- resolved AI attribution evidence;
- a continuous authenticated User Data Stream soak in the current v6 epoch;
- closed prediction horizons without an overdue backlog;
- positive lower confidence bounds;
- baseline improvement after Holm correction;
- acceptable fill rate and drawdown in all required regimes;
- a PASS Pi verification report for the deployed release SHA.

HALT and SHADOW can remain active together.
This state permits evidence collection without order mutation.

## Known limits

- Replay uses Binance L2 market data.
- Replay does not reconstruct private exchange L3 queue events.
- Legacy inventory stays outside bot control without an approved cost-basis import.
- Numeric FIFO PnL stays unavailable when purchase history is incomplete.
- Correlated symbols do not provide independent risk during a market panic.
- A provider response cannot replace deterministic risk or protection checks.
- Raspberry Pi network latency can remain larger than local processing latency.
- Portfolio change is unavailable when an exact historical candle is unavailable.

See [Runtime safety and reporting](RUNTIME_SAFETY_AND_REPORTING.md) for operator actions.
