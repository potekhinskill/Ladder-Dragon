# Implementation status

This document describes the code in version **2.20.145**.
It does not describe future plans as completed work.

An implemented function is not automatically approved for LIVE use.
The configured mode and its evidence gate remain authoritative.

## Runtime status

| Area | Implemented behavior | Default or approval state |
| --- | --- | --- |
| Execution | Binance Spot LIMIT, MARKET, OCO, OTOCO, cancel-replace, and recovery | DRY or Testnet first |
| Protection | Verified OCO legs, confirmed breakeven re-arm, gap flatten, and persistent HALT | Required for managed fills |
| Accounting | Exact FIFO lots, FIFO risk streaks, fee conversion, SELL idempotency, and cursor audits | Fail closed on incomplete evidence |
| Replay | Sequential L2 events, shared liquidity, queue state, latency, fees, and slippage | L2 model, not exact L3 |
| Prediction | 1, 5, and 15 minute SHADOW outcomes | Enabled for evidence only |
| Experiments | Versioned same-snapshot strategy candidates | SHADOW only |
| Statistical approval | Walk-forward, confidence intervals, regime checks, and Holm correction | Must pass before APPLY |
| AI advice | Validated DeepSeek, OpenAI, or compatible provider response | Disabled by default |
| RAG | Hybrid similarity, retention, bounded candidates, and real-only retrieval | Virtual records stay archived |
| Fast market data | `bookTicker`, `aggTrade`, and depth snapshots | OFF by default |
| WebSocket trading | Signed request transport and reconciliation | OFF and separately approved |
| OTOCO | Atomic BUY with symmetric ACK-loss recovery | OFF and separately approved |
| User Data Stream | Independent observer, Testnet drill, and soak evidence | Installed as a separate service |
| Dashboard | Read-only account, canonical FIFO PnL, risk, AI, positions, and host data | Private authenticated access |
| Reports | Daily trading digest, monthly prediction report, and signed soak report | Scheduled by systemd |
| Deployment | Signed fast-forward update, backup, rollback, and asset verification | Exact 40-character SHA required |

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

Future outcomes are normal pending work.
Only overdue or unrecovered expired outcomes block the backlog gate.
The soak report applies its expiration checks to the audited runtime window.

The active experiment contour compares 15 version-two candidates on one snapshot:

- RANGE-only entry;
- TP targets of 1.00%, 1.05%, and 1.10%;
- maker-only entry and TP;
- BUY lifetimes of 3, 5, and 8 minutes;
- BUY distances of 5, 8, and 10 basis points.

Three combined candidates use RANGE-only entry, a five-minute lifetime, and maker-only execution.
They pair each TP target with one fixed BUY distance.
The fourth combined candidate uses an eight-minute lifetime and a dynamic 5-to-15 basis-point BUY distance.
All candidates use the same immutable snapshot and baseline.

New plan semantics use a new experiment identifier.
Historical experiment rows remain available and never mix with the active generation.

Re-anchor is not a promotion candidate.

No candidate can set `apply_allowed=true` by itself.

## Current approval boundary

The repository does not claim general production approval or profitability.
A bounded Mainnet canary proves only its exact small acceptance lifecycle.

Promotion still requires these items:

- exact natural BUY to OCO to TP or STOP lifecycles;
- zero unresolved inventory or protection fills;
- resolved AI attribution evidence;
- a continuous authenticated User Data Stream soak;
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

See [Runtime safety and reporting](RUNTIME_SAFETY_AND_REPORTING.md) for operator actions.
