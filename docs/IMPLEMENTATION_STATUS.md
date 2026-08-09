# Implementation status

This document describes the code in version **2.20.182**.
It does not describe future plans as completed work.

An implemented function is not automatically approved for LIVE use.
The configured mode and its evidence gate remain authoritative.

## Runtime status

| Area | Implemented behavior | Default or approval state |
| --- | --- | --- |
| Execution | Decimal-only Binance Spot planning, orders, cancel-replace, and recovery | DRY or Testnet first |
| Protection | Verified OCO legs, confirmed breakeven re-arm, gap flatten, and persistent HALT | Required for managed fills |
| Accounting | Exact FIFO lots, exact AI fills, fee provenance, risk streaks, and cursor audits | Fail closed on incomplete evidence |
| Replay | Sequential L2 events, shared liquidity, queue state, latency, fees, and slippage | L2 model, not exact L3 |
| Prediction | 1, 5, and 15 minute SHADOW outcomes | Enabled for evidence only |
| Experiments | Versioned same-snapshot strategy candidates | SHADOW only |
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
| Maker policy | `SHADOW` |
| Regime gate | `SHADOW` |
| Inventory skew | `SHADOW` |
| Statistical regime | `SHADOW` |
| Correlation cluster gate | `SHADOW` |
| Fast market gate | `OFF` |
| OTOCO | `OFF` |
| WebSocket trading | `OFF` |
| AI advisor | disabled, with mode `SHADOW` |

`SHADOW` records evidence and does not change an order.
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

The active experiment contour compares twelve version-six candidates on one snapshot:

- maker-only entry and TP;
- always-active and RANGE-only entry scopes;
- BUY lifetimes of 30 and 60 minutes;
- outcome horizons of 30 and 60 minutes;
- explicit BUY distances of 15, 20, and 25 basis points.

All candidates use the authoritative TP floor.
Candidate prices use their explicit market gaps independently from the baseline.
All candidates use the same immutable snapshot and baseline.
Normal strategy predictions retain their 1, 5, and 15-minute horizons.

The promotion gate evaluates the complete candidate strategy.
It includes `NO_TRADE` opportunity cost against the active baseline.
The report also shows an active-entry cohort without `NO_TRADE` rows.
That cohort is diagnostic and cannot approve APPLY.

Operational analytics use the latest 1,000 decisions for each candidate.
This limit bounds Raspberry Pi memory and temporary storage use.
Raw decisions and outcomes remain append-only in SQLite.

New plan semantics use a new experiment identifier.
Historical experiment rows remain available and never mix with the active generation.

Attributed AI fills store monetary values as exact text.
Each fill records whether its slippage value is verified.
Unknown slippage makes financial evidence incomplete.
Incomplete evidence cannot enter readiness, RAG, or dashboard PnL totals.

Re-anchor is not a promotion candidate.

No candidate can set `apply_allowed=true` by itself.

## Current approval boundary

The repository does not claim general production approval or profitability.
A bounded Mainnet canary proves only its exact small acceptance lifecycle.

Promotion still requires these items:

- exact natural BUY to OCO to TP or STOP lifecycles;
- zero unresolved inventory or protection fills;
- resolved AI attribution evidence;
- a continuous authenticated User Data Stream soak in the current v4 epoch;
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
