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

## HALT and SHADOW are separate states

`HALT` blocks trading mutations. It stops new BUY workers and cannot be bypassed
by AI, a strategy proposal, or a manual fallback.

When authenticated account reconciliation is healthy, the supervisor may still
calculate non-executing SHADOW candidates while HALT is active. This preserves
counterfactual evidence needed to study BUY distance, re-anchoring, regimes, and
expectancy without starting a worker or changing an order.

SHADOW evidence:

- cannot submit or cancel an order;
- cannot change BUY, TP, STOP, CAP, or Risk Manager output;
- is not a real closure and cannot enter real-only RAG;
- cannot satisfy production approval by itself.

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

The service opens the trade database read-only and replays each symbol
independently. A symbol with incomplete FIFO history, unpriced commission, an
unsupported quote asset, or invalid exact data is listed under
`Excluded symbols`. Eligible symbols still produce exact fills, fees, cash flow,
and realized FIFO net PnL. The service never invents an opening BUY or assumes a
zero cost basis.

Successful delivery is idempotent per local report date. A report-build failure
after the database is opened can send one deduplicated `BLOCKED` warning for
that date; the warning contains no financial figures. A missing database blocks
the service before report construction and is recorded in the systemd journal.

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
[release procedure](RELEASING.md), and the project [README](../README.md).
