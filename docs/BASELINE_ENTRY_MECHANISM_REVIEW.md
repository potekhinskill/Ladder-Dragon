# Baseline entry mechanism and execution review

Review date: 2026-09-13.
Status: Stage A documentation complete; candidate hypothesis proposed, empirical support and execution qualification incomplete.

This review implements the documentation boundary of the [baseline protocol](BASELINE_ENTRY_RESEARCH_PROTOCOL.md).
It changes no trading rule, replay implementation, or evidence artifact.
The findings describe local source inspection, not a fresh production audit.

## Proposed hypothesis: positive-flow entry admission

The proposed candidate admits a passive BUY only when observed trade flow and best-level order flow both point upward.
The mechanism hypothesis is temporary buying pressure before submission, followed by a recoverable price retracement to the resting entry.
This mechanism is plausible but unproven; positive flow could instead move price away and reduce fills.
The old v23 result supplies no evidence that this condition predicts profitable entries.

The proposed rule uses the existing shared signal snapshot at the control's first eligible opportunity:

- The signal must be ready under its complete trailing-window contract.
- Normalized signed trade flow must be strictly greater than zero.
- Normalized order-flow imbalance must be strictly greater than zero.
- All existing opportunity eligibility and mandatory safety conditions must remain satisfied.

Zero is a proposed directional boundary, not an outcome-fitted threshold or approved trading parameter.
No magnitude search, persistence delay, second attempt, or post-submit optional veto is proposed.
The signal window and every execution parameter must receive an exact identity before preregistration.

Both arms use the same predetermined opportunity timestamp and denominator.
If the candidate rejects an opportunity, it records an explicit zero-fill skip and cannot wait for a favorable replacement.
The unchanged baseline still runs that opportunity as the paired control.
This design tests initial admission, not delayed entry or cancellation reversal.

The proposed implementation must reuse `EntryVetoSignalAccumulator`, not copy its formulas.
Signed trade flow measures BUY quantity minus SELL quantity, divided by total observed trade quantity.
Order-flow imbalance measures accumulated best-level increments, divided by their accumulated absolute magnitude.
Neither metric proves individual queue position or future returns.
See the [signal owner](../ladder_dragon/strategy/entry_veto_signal.py).

## Strongest counterargument and falsification

The existing planner uses a 48-basis-point entry gap and a ninety-minute entry lifetime.
A short signal at submission can expire long before a passive fill arrives.
Conditioning on a later fill can also select adverse reversals despite initially positive flow.
Therefore, immediate upward movement or improved fill-only profit cannot establish this hypothesis.

The primary test must retain zero-fill skips and measure net outcome on every registered opportunity.
Signal-to-fill delay and signal state at fill are secondary diagnostics, never retroactive admission criteria.
If positive-flow admission only removes opportunities without establishing positive absolute expectancy, it must not advance.
If its apparent benefit depends on post-outcome parameter selection, the mechanism remains unsupported.

The [planner policy](../ladder_dragon/strategy/prediction/historical_replay_planner.py) defines the existing numbers, not a newly approved candidate.
No shorter lifetime or nearer entry is bundled into this hypothesis.
Such changes would test another mechanism and require another reviewed scope.

## Execution-contract inspection

| Boundary | Observed implementation | Qualification still required |
|---|---|---|
| Entry anchor | Midpoint minus the policy gap, with tick and quantity rounding | This is explicitly selection-only, not a LIVE champion fingerprint |
| Arrival | First observed arrival book; post-only crossings reject entry or flatten rejected protection | Actual exchange timing and acceptance parity |
| Passive queue | Public quantity at arrival; no cancellation-ahead credit in historical execution | Individual queue priority remains unobservable from aggregate depth |
| Fill matching | Reaching aggressor volume consumes queue before local quantity | Real-exchange fill calibration, including adverse selection |
| Cancellation | Entry remains fillable before effective cancellation; a timestamp tie favors the fill | Venue timing qualification, not just synthetic tie consistency |
| Partial entry | Quantity survives cancellation; protection starts after the entry fills completely or its remainder cancels | Exposure during an unfinished partial entry and runtime protection parity |
| Stop | A qualifying trade triggers atomic target removal and a separately submitted stop | Exchange conditional activation timing and sibling semantics |
| Emergency exit | All residual quantity exits at best bid minus fixed impact, without depth consumption | Executable liquidation capacity and latency |
| Fees | Context rates apply to fill notional; fees accumulate in quote currency | Fee-asset quantity effects and exact execution accounting parity |
| Holding limit | Deadline starts at episode submission, not the first fill | Explicit agreement with the intended runtime holding rule |

The principal owner is [HistoricalExecution](../ladder_dragon/strategy/prediction/historical_execution.py).
The shared matching owner is [OrderBookReplay](../ladder_dragon/strategy/market_replay.py).
The [paired runner](../ladder_dragon/strategy/prediction/historical_entry_replay.py) currently implements baseline versus veto, not this admission candidate.

Emergency flatten bypasses the matcher's displayed-depth consumption.
The fixed impact allowance is therefore not a demonstrated worst-case liquidation bound.
The stop path uses normal submission latency after its trigger rather than proving exchange-native conditional activation timing.
These observations identify model limitations; they do not establish an actual LIVE protection defect.

Historical execution does not reproduce the complete production portfolio, reserve, or account-authority workflow.
Its report explicitly leaves runtime parity and independent confirmation unresolved.
Retaining research PANIC handling does not prove that every mandatory LIVE guard has been simulated.

## Verification and evidence limits

The existing historical-entry and market-matching test modules pass: 28 tests on 2026-09-13.
They exercise arrival rejection, cancellation ties, partial-fill retention, source gaps, context causality, and shared signal behavior.
They do not validate the proposed admission rule, real-exchange parity, or positive expectancy.
No old reports were recomputed and no new source outcomes were inspected during this review.

## Decision and next boundary

Keep this as one candidate proposal, not an approved or profitable strategy.
Stage B can receive design work, but experiment launch remains blocked.
The [synthetic qualification review](BASELINE_EXECUTION_QUALIFICATION.md) now records all four execution scenarios.
Execution qualification remains incomplete; the review defines the proposed correction boundary.
Each case must separate expected venue behavior, current model behavior, and missing evidence.
Confirmed implementation defects then require a separately bounded correction with regression tests.

After qualification, freeze the candidate identity, source boundary, statistical method, and feasible observation budget together.
If qualification fails or no defensible budget exists, stop without a new study.
Do not compensate for execution uncertainty with a more favorable signal threshold.
HALT, Pi configuration, production code, and immutable v23 evidence remain unchanged.
