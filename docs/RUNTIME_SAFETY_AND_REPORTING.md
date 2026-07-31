# Runtime safety and reporting

This document describes the operator-visible contracts shared by execution,
accounting, the dashboard, SHADOW evidence collection, and Telegram reporting.
It is a behavior reference, not a profitability claim or permission to enable
LIVE trading.

## Filled BUY protection

A filled BUY is not considered safe merely because an OCO request was attempted.
The execution path follows these steps:

1. Persist the BUY fill and its protection intent in the durable journal.
2. Read a fresh Binance market price immediately before protection submission.
3. Require the exact SELL relationship `TP > market > STOP > STOP_LIMIT` after
   exchange tick-size normalization.
4. Submit the OCO only while that relationship remains valid.
5. Reconcile the exact order-list ID and both protective SELL legs against
   Binance.

A crossed protection plan is never submitted as an OCO that Binance must reject.
If a definitive OCO attachment failure occurs in confirmed LIVE operation, the
executor attempts an idempotent emergency MARKET SELL for the exact filled
quantity. The parent BUY is closed only when Binance returns `FILLED`, the
executed quantity covers the expected quantity, and the journal update commits.

A partial execution, lost acknowledgement, network ambiguity, or journal write
failure is not reported as a successful flatten. The symbol remains halted and
the position remains unresolved for authoritative reconciliation.

Read uncertainty does not permit a protection change.
If an order-list or leg query times out, recovery leaves the OCO or OTOCO unchanged.
Recovery enters HALT.
It does not cancel the list or classify it as absent.
Cancellation occurs only after a successful read proves a structural mismatch.

A terminal leg with a positive partial execution is a confirmed partial exit,
not an exact closed lifecycle. Its exchange order ID and quantity are recorded
idempotently, the original protection becomes terminal, and the parent returns
to `PROTECTION_PENDING`. Replacement protection is sized from the exact
residual `BUY executed quantity - confirmed partial exits`.

## Exactly-once transport boundary

The durable intent journal, not the HTTP client, owns mutation recovery.
Signed POST, DELETE, PUT, and PATCH calls therefore get one transport attempt.
A timeout, connection loss, or Binance 5xx makes the execution outcome unknown.
The caller marks the intent `UNKNOWN`.
It queries Binance with the durable `clientOrderId`.
It then recovers the exact order or enters HALT.
The transport does not repeat a mutation because its acknowledgement was lost.

A `-2010 Duplicate order` response is treated as evidence of an earlier
submission and enters the same reconciliation path. It is not a definitive
`FAILED` intent. Other confirmed business rejections remain terminal.

Signed GET and HEAD calls are bounded to three attempts so exchange degradation
cannot hold the single-threaded protection loop for the former eight-attempt
budget. HTTP 418 is never retried: its `Retry-After` value arms a process-wide
local cooldown, and every public or signed request fails locally until that
interval expires. HTTP 429 uses the same local cooldown instead of sleeping
inside the protection loop.

`-1021` is a definitive clock rejection, so no order was accepted. On its first
occurrence the transport reads `/api/v3/time`, estimates offset at the request
midpoint, and retries the rejected operation once with the corrected timestamp.
A failed synchronization or a second `-1021` is fail-closed.

## Durable lifecycle journal

Lifecycle evidence is one crash-consistent unit. Confirming protection writes
the two exchange-verified OCO legs, protection state, and parent BUY state in
one SQLite transaction. Confirming a TP or STOP writes both CLOSED states, both
metadata records, and the normalized exact-closure record in one transaction.
If any write fails, the whole transition rolls back.

A repeated `client_order_id` is idempotent only when every immutable field
matches the existing intent. Quantity and price are compared as exact
`Decimal` values rather than formatted strings. A conflicting ID blocks the
operation and its diagnostic names only the conflicting fields, never metadata
contents.

Normalized, indexed tables map exchange leg IDs to protection intents and hold
exact closure summaries and terminal partial-exit quantities. Runtime recovery
and dashboard telemetry use these tables instead of scanning historical JSON.
The journal keeps a single thread-safe connection per process and reopens it
after a fork.

Closed intents are retained indefinitely because they are accounting,
recovery, and production-approval evidence. The runtime does not delete or
automatically archive them. Any future archival policy must be an explicit
offline, checksum-verified operation that preserves normalized evidence and is
validated against the release-approval requirements.

## HALT and SHADOW are separate states

`HALT` blocks trading mutations. It stops new BUY workers and cannot be bypassed
by AI, a strategy proposal, or a manual fallback.

The authoritative marker, risk snapshot and alert stream are stored below
`/var/lib/ladder-dragon/control`. They must survive service stop and host
reboot; `/run/mybot` contains only disposable process-lifetime files. On LIVE
startup the supervisor publishes `RISK_PENDING` with BUY blocked until the
first authenticated risk snapshot completes. A pre-existing marker remains
visible as halted throughout that interval.

When authenticated account reconciliation is healthy, the supervisor may still
calculate non-executing SHADOW candidates while HALT is active. This preserves
counterfactual evidence needed to study BUY distance, re-anchoring, regimes, and
expectancy without starting a worker or changing an order.

The experiment contour evaluates five candidates against the untouched current
strategy plan on identical feature timestamps and 1/5/15-minute candles. All
candidates use a TP above the authoritative cost floor; individual variants
isolate BUY distance, five-minute TTL, bounded re-anchor and DOWN/PANIC veto
effects. Recording is limited to one candidate set per five minutes, while
expensive gates refresh at most every 15 minutes. Selection requires both the
ordinary horizon/regime Holm gate and a configuration-level Holm correction
using a distinct paired-edge p-value for every candidate. Even a passing
candidate remains `apply_allowed=false` until a separate reviewed release and
operator approval.

Authenticated User Data Stream soak is also independent from execution. The
`ladder-dragon-user-stream-shadow` service has no POST, DELETE, placement or
cancel path; each accepted order notification can only wake an authoritative
GET reconciliation. Its sanitized state persists below
`/var/lib/ladder-dragon/user-stream`. This avoids the unsafe circular
requirement to clear HALT merely to collect stream-readiness evidence.

SHADOW evidence:

- cannot submit or cancel an order;
- cannot change BUY, TP, STOP, CAP, or Risk Manager output;
- is not a real closure and cannot enter real-only RAG;
- cannot satisfy production approval by itself.

## Strategy approval and execution cost

The system reads authoritative account commission rates before it calculates the required edge.
The required edge includes both fees, both slippage estimates, and a safety margin.

The example configuration keeps these controls in SHADOW:

- expectancy;
- maker policy;
- regime gate;
- inventory skew;
- statistical regime;
- correlation-cluster gate.

SHADOW fee values can improve exact accounting.
SHADOW does not export the execution-changing required edge to a worker.

APPLY requires `BOT_STRATEGY_CONTROLS_APPROVED=YES` and valid chronological evidence.
It also requires an explicit managed-inventory hard CAP for each symbol.
The portfolio CAP is not a substitute for this limit.

## Prediction outcomes and provider failures

Prediction horizons are 1, 5, and 15 minutes.
An unresolved future horizon is normal pending work.
An overdue horizon or unrecovered expired outcome blocks the prediction backlog gate.

The soak report checks expirations from its current audited runtime window.
It still reports lifetime expiration totals as historical evidence.

AI provider failures select the deterministic strategy.
Consecutive failures use exponential negative-cache backoff up to the normal cache time.
One valid response resets this backoff.

Identical provider and low-confidence diagnostics are limited to one each hour.
The bounded usage and decision stores still record each result.
Provider error text, response bodies, and endpoint URLs do not enter operator logs.

## Low-latency modes

Fast market data, OTOCO, and WebSocket trading are separate modes.
The example configuration keeps all three modes OFF.

Each LIVE APPLY mode requires its matching `YES` approval.
These modes cannot bypass the normal LIVE confirmation or Risk Manager.

The fast-market gate rejects an expired snapshot.
It also rejects excessive spread, price movement, sequence regression, or insufficient net edge.

OTOCO can submit a BUY with its future protection list.
WebSocket trading uses server-adjusted timestamps and one bounded response deadline.
REST remains the authoritative reconciliation path.

## Managed and legacy inventory

The dashboard deliberately separates two scopes:

- **Managed inventory** consists of exact bot lots linked to exchange fills and
  durable journal evidence. Protection is reported only for the quantity covered
  by confirmed Binance OCO legs.
- **Legacy inventory** is account quantity outside complete managed provenance.
  It remains unmanaged and unprotected by the managed OCO unless a separate,
  reviewed cost-basis import proves its history and an operator explicitly
  enables holdings management.

An OCO for a managed lot must never be presented as protection for the entire
account balance. Average entry, unrealized PnL, and drawdown remain unavailable
when exact lots do not cover the quantity being described.

## Exact PnL and dashboard availability

Cash flow, portfolio value movement, and realized FIFO net PnL are different
metrics:

- cash flow records quote currency entering or leaving through trades;
- portfolio movement includes mark-to-market changes;
- realized FIFO net PnL requires valued commissions and sufficient historical
  BUY lots for every SELL quantity in the reporting window.

The dashboard withholds numeric 24-hour FIFO PnL when a symbol sold during the
window has incomplete FIFO history or unpriced commission provenance. It shows
the metric as unavailable and names the affected symbols. Cash flow and
portfolio valuation remain visible under their own labels and are never used as
a substitute for realized profit.

## Daily Telegram digest

`ladder-dragon-daily-digest.timer` runs at 08:00 `Asia/Almaty` and reports three
complete periods ending at local midnight:

- yesterday;
- the last 7 complete days;
- the last 30 complete days.

The service opens the trade database with SQLite `mode=ro` and replays each
symbol independently. Its systemd sandbox permits the database directory only
for WAL shared-memory coordination; the application connection cannot mutate
the ledger. A symbol with incomplete FIFO history, unpriced commission, an
unsupported quote asset, or invalid exact data is listed under `Excluded symbols`.
Eligible symbols still produce exact fills, fees, cash flow, and realized FIFO
net PnL. The service never invents an opening BUY or assumes a zero cost basis.
The report displays fees with a negative sign because they reduce net PnL.

Successful delivery is idempotent per local report date. A report-build failure
sends one deduplicated `BLOCKED` warning for that date; the warning contains no
financial figures. Systemd retries a failed run twice at five-minute intervals,
so a transient database or Telegram failure does not postpone the report by a
full day.

Private operator checks:

```bash
sudo systemctl status ladder-dragon-daily-digest.timer --no-pager
sudo systemctl list-timers ladder-dragon-daily-digest.timer --no-pager
sudo journalctl -u ladder-dragon-daily-digest.service -n 50 --no-pager
sudo -u bot env PYTHONPATH=/home/bot/apps/binance_bot \
  /home/bot/apps/binance_bot/.venv/bin/python \
  -m bin.daily_trading_digest --dry-run
```

The dry-run prints private financial data to the terminal. Do not paste its
output into issues, chats, or public logs.

## Operational log policy

State changes, unresolved fills, protection failures, authentication failures,
and emergency actions remain visible. Stable no-op messages are suppressed:

- an open-BUY cancellation pass that canceled zero orders is silent;
- repeated diagnostics for an explicitly allowlisted unvalued asset are
  rate-limited by `RISK_STABLE_INFO_LOG_INTERVAL_SEC` (default: 3600 seconds).

Rate limiting never suppresses a transition into a different risk state.
Identical AI provider diagnostics are also limited to one each hour.
Evidence persistence is not rate-limited.

## Operator decision table

| Observation | Meaning | Safe response |
| --- | --- | --- |
| Managed quantity is fully OCO protected | Exact managed lot protection is confirmed | Continue monitoring reconciliation |
| Managed quantity exceeds protected quantity | Some bot inventory lacks confirmed protection | Keep HALT; inspect Binance and journal |
| Legacy quantity is shown separately | The balance is outside managed provenance | Do not assume the managed OCO covers it |
| FIFO PnL is unavailable | Exact historical basis is incomplete for a sold symbol | Use the named exclusion; do not infer profit from cash flow |
| Digest lists an excluded symbol | Other eligible symbols remain exact | Repair or import provenance separately |
| Digest is `BLOCKED` | No trustworthy report could be built | Inspect the service journal and database health |
| HALT with continuing SHADOW samples | Execution is blocked; advisory evidence is still collected | Do not interpret samples as applied trades |

## Deployment boundary

These contracts take effect only after the exact signed release SHA is deployed.
The Raspberry updater preserves `.env` and does not import new defaults. Review
new non-secret settings explicitly, copy the matching PASS release manifest,
and run the Pi verification profile before treating the deployment as current.

See the [Raspberry Pi runbook](RASPBERRY_PI_INSTALL.md), the
[release procedure](RELEASING.md), and the [configuration reference](CONFIGURATION.md).
The [command reference](COMMAND_REFERENCE.md) lists each installed service.
