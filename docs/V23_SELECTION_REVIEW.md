# V23 selection review and next hypothesis

Review date: 2026-09-12.
Status: current selection fails; this research direction is analytically closed on 2026-09-13.

This document records an analytical conclusion, not a database lifecycle transition.
No v23 confirmation candidate was frozen by this review.
No import, experiment rejection command, bootstrap, release, or trading action is authorized by this document.

## Evidence and result

The review covers 32 immutable reports: eight policies on the same twelve paths and four chronological blocks.
These are twelve independent paths, not ninety-six independent observations.
The reviewed implementation is release `v2.20.340`.
All report hashes and embedded implementation hashes matched the installed code during the review.
Raw production evidence remains on its original protected storage.

All eight policies fail the existing selection validator.
The table gives simulated USDT totals for the twelve baseline opportunities, rounded only for presentation.

| Baseline terminal reason | Count | Gross | Fees | Net |
|---|---:|---:|---:|---:|
| TAKE_PROFIT | 2 | 0.09574000 | 0.02391018 | 0.07182982 |
| STOP_LIMIT | 2 | -0.10680000 | 0.02382600 | -0.13062600 |
| TIME_STOP | 1 | 0.00092511 | 0.01181703 | -0.01089192 |
| MISSED_FILL | 7 | 0 | 0 | 0 |
| Total | 12 | -0.01013489 | 0.05955321 | -0.06968810 |

Fees worsen an already negative gross result; removing fees would not make this baseline positive.
These values are simulated profit and loss, not changes in the real account.

Paired episodes have identical start timestamps in both arms.
Every veto policy cancels both baseline opportunities that reach TAKE_PROFIT.
Five policies retain one or two filled episodes, all ending at STOP_LIMIT.
Three policies retain no fills and return zero net, which does not prove positive expectancy.
Veto rates range from 5/12 to 12/12, above the permitted maximum of 40 percent.
Five policies also have only two stable blocks; at least three of four are required.

## What the review proves and does not prove

- Entry and exit quantities agree for every completed episode.
- No reviewed episode is censored or has a partial entry.
- Every reported net equals gross minus fees under exact Decimal arithmetic.
- Thirty-eight focused matching and historical replay tests passed during the diagnostic review.
- The report checks do not independently reconstruct every fee or prove real-exchange execution parity.
- Twelve paths do not establish that every possible veto strategy is ineffective.

The current design permits exactly one attempt per path.
A veto therefore does not earn a replacement opportunity inside this cohort.
This limit is explicit in the planner, not a replay timeout.
Changing it after observing outcomes would change the tested hypothesis.

The model uses a midpoint anchor and explicit passive-queue assumptions.
Its emergency flatten uses the observed best bid and a fixed impact allowance.
It does not prove executable liquidation quantity across the full book.
These model limits require separate review; this analysis does not attribute the selection failure to them.

## Disposition of the current selection

Keep the current hypothesis recorded as not passing selection on its fixed cohort.
Preserve its reports, requests, source references, and checkpoints under the existing retention contract.
Do not import a passing artifact, freeze v23, or bootstrap confirmation from these results.
Do not replace the frozen cohort with the planner's newer proposal.
An unchanged failed selection cannot become successful merely through repeated evaluation.
Monitoring can check host safety and evidence integrity, but must not reinterpret this conclusion as pending collection.

## Proposed next hypothesis: persistent adverse signal

This section preserves the explored hypothesis and its unsuccessful mechanism review.
It is not the active next research plan.
The [baseline entry research protocol](BASELINE_ENTRY_RESEARCH_PROTOCOL.md) defines the next proposed review boundary.

The proposed mechanism is unvalidated and is not a new approved generation.
No generation number, numerical persistence interval, or executable policy is assigned here.

Hypothesis: a short-lived adverse signal cancels recoverable passive entries too readily.
Requiring sustained adverse evidence could improve net outcome per eligible opportunity relative to immediate veto and the no-veto control.
The reviewed outcomes motivate this hypothesis but do not prove the proposed mechanism.
The reports do not contain enough signal trajectories to distinguish transient and sustained adverse signals directly.
The source reconstruction below supplies an exploratory duration check, not an approved persistence rule.

The proposed change concerns only the optional adverse-selection veto.
HALT, PANIC, protection, freshness, reserve, loss controls, and other mandatory guards retain their immediate authority.
The candidate must not delay any mandatory cancellation or protection action.

### Stage 1: exploratory mechanism review

1. Reconstruct causal signal trajectories on the old cohort without changing its reports.
2. Measure signal duration, cancel timing, queue state, and later terminal outcomes separately.
3. Label every result exploratory because these outcomes already influenced the hypothesis.
4. Review flatten, fees, partial fills, and runtime parity before assigning new evidence authority.
5. Stop if the proposed transient-signal mechanism is unsupported.

The old cohort can inform development, but it cannot supply new confirmatory evidence.
A verified implementation defect requires a separately reviewed correction on the same immutable inputs.
Such a correction does not authorize new sampling or weaker acceptance rules.

### Stage 1 result: signal reconstruction

On 2026-09-12, a read-only reconstruction covered all twelve original paths and reproduced all 69 recorded veto signals.
Every source chain passed the canonical archive checks; the decoder exhausted all supplied segments.
The run used the installed signal accumulator and the original eight threshold sets.
An additional synthetic comparison matched the shared calculation with `RollingVeto` for 8,000 policy-event pairs.
No report, source, database, or runtime configuration changed.

The observation window extends five minutes after each recorded signal, within the original path boundary.
Five minutes is a descriptive measurement window, not a proposed trading delay.
Every measured run ends within this window; none is censored at its boundary.
The table measures time from the recorded signal to the first observed event where the veto condition is inactive.
The actual transition lies between the last active event and that observation.
These measurements do not establish continuous signal state between events.

| Later baseline outcome | Policy-path observations | Minimum seconds | Median seconds | Maximum seconds |
|---|---:|---:|---:|---:|
| TAKE_PROFIT | 16 | 0.019 | 23.285 | 148.597 |
| STOP_LIMIT | 9 | 0.253 | 6.894 | 81.600 |
| TIME_STOP | 8 | 0.783 | 10.456 | 11.058 |
| MISSED_FILL | 36 | 0.073 | 3.500 | 195.700 |

The TAKE_PROFIT observations reuse two paths across eight policies; they are not sixteen independent profitable examples.
Every measured active run starts at the recorded signal timestamp, consistent with immediate first-trigger veto.
That zero pre-signal duration does not itself justify a persistence filter.
Four events veto before submission; the remaining 65 have a modeled cancellation delay of one second.
Thirteen signals become inactive before that cancellation delay ends, including two TAKE_PROFIT observations and one STOP_LIMIT observation.
An inactive signal does not withdraw an already submitted cancel in the current model.
This behavior is not, by itself, an execution defect or evidence for cancel reversal.
Observed transition brackets span 3 to 794 milliseconds.
There is no exact exchange-order trajectory in this descriptive reconstruction.

The profitable-path signals are not uniformly shorter than the avoided-stop signals.
Their observed median is longer, and their ranges overlap substantially.
This small, outcome-informed sample does not support a simple duration threshold that separates recoverable entries from adverse entries.
The mechanism remains unconfirmed; no persistence interval is selected and Stage 2 does not start.

This pass does not reconstruct queue position or simulate a delayed-veto counterfactual.
A delayed cancellation could change fills, protection, fees, and subsequent exposure.
Descriptive post-signal outcomes cannot prove that any proposed delay preserves profit.
Full execution parity and the earlier flatten limitations also remain unresolved research requirements.
Those questions require a separately scoped diagnostic before any implementation proposal.

### Stage 1 result: entry-queue reconstruction

A second read-only diagnostic reproduces 108 entry phases: twelve baseline entries and ninety-six veto entries on the same twelve paths.
The baseline is identical across the eight policies and is reconstructed once per path.
The diagnostic uses the unchanged `HistoricalExecution` and `OrderBookReplay` implementations.
Historical context hashes match the saved checkpoints, and all source chains pass validation.
Each reconstructed entry matches its recorded price, requested quantity, filled quantity, entry cost, and submission flag.
Each zero-fill result also matches its recorded reason and terminal, signal, and cancellation timestamps.
A synthetic comparison with full replay passes for both arms.

| Observed entry class | Count | Reaching trade before entry termination | Fill during pending cancellation |
|---|---:|---:|---:|
| Baseline MISSED_FILL | 7 | 0 | 0 |
| Baseline filled entries | 5 | 5 | 0 |
| Veto ENTRY_VETO | 69 | 0 | 0 |
| Veto MISSED_FILL | 20 | 0 | 0 |
| Veto filled entries | 7 | 7 | 0 |

For BUY, a reaching trade means an observed SELL-aggressor trade at or below the resting limit while the order is active.
The counts refer to entries with such events, not total trade counts.
The configured entry timeout is ninety minutes, followed by the modeled cancellation delay.
All seven baseline misses have a positive public queue at arrival and at the cancellation request.
However, no reaching trade occurs during their active lifetime.
These misses therefore do not demonstrate sufficient trade volume consumed by an incorrectly retained queue.
Reducing queue-ahead alone cannot create a passive fill without a reaching trade under this matcher.

Four veto events reject before submission.
The other 65 veto cancellations have positive queue-ahead at the request and no reaching trade before cancellation takes effect.
The model clears or transfers queue state during cancellation; a zero post-cancel queue does not prove earlier exhaustion.
No observed entry fills during pending cancellation, and no partial entry is lost in these reconstructed phases.
The sample therefore contains no demonstrated cancellation race or queue-accounting mismatch that explains selection failure.

The following intervals compare the baseline's first fill with the veto arm's recorded effective cancellation timestamp.
They are paired descriptive comparisons, not results from a delayed-veto strategy.

| Later baseline outcome | Policy-path comparisons | Minimum seconds | Median seconds | Maximum seconds |
|---|---:|---:|---:|---:|
| TAKE_PROFIT | 16 | 710.944 | 1596.824 | 1880.886 |
| STOP_LIMIT | 9 | 1111.475 | 1867.492 | 3428.421 |
| TIME_STOP | 8 | 2721.884 | 2722.185 | 3333.496 |

The sixteen TAKE_PROFIT comparisons still represent only two independent profitable paths.
Their baseline fills occur roughly twelve to thirty-one minutes after veto cancellation, not inside the one-second cancellation delay.
This timing does not establish that a short persistence filter would recover them.
Later veto signals, queue changes, fees, and protection could change a delayed strategy's result.

This reconstruction ends simulation after the entry phase and checks it against the existing full report.
It does not independently validate the later exit model or establish real-exchange queue parity.
No alternative delay, queue rule, or trading candidate is selected.

### Stage 2: complete a preregistration before new outcome access

The following fields must be fixed before the new study can start:

| Required field | Current state |
|---|---|
| Candidate implementation and single persistence interval | Not selected |
| Signal continuity, gap, reset, and reconnect semantics | Not specified |
| Pre-submit and post-submit behavior, including latency ties | Not specified |
| Fixed controls and total number of candidate comparisons | Not approved |
| Exact source-selection rule and future cutoff | Not frozen |
| Path count, block allocation, precision justification, and deadline | Not approved |
| Primary estimand and multiplicity treatment | Not approved |
| Rejection, inconclusive, missing-data, and attrition rules | Not approved |
| Independent confirmation boundary and capacity assessment | Not approved |

The proposed primary estimand is net outcome per eligible opportunity, including zero-fill attempts and all modeled costs.
Fill-only profit must not replace it after outcomes appear.
The no-veto control is a research comparator, not permission to disable a production guard.
Existing financial and execution safety requirements remain minimum constraints.
A different study design requires explicit review rather than silent changes to v23 gates.

### Stage 3: independent future evaluation

Use new sources collected after the approved preregistration boundary.
Exclude all sources whose outcomes informed development and all current selection archive hashes.
Choose paths chronologically through fixed causal eligibility rules, never through future fills or profit.
Do not extend the deadline or replace losing paths after results appear.
Report all registered candidates and controls, including rejected and inconclusive results.
If selection passes, require disjoint confirmation and the existing execution validation before any promotion request.

## Implementation checks required later

This draft does not implement a candidate or weaken the harness.
Any implementation must add checks for these contracts:

- Identical causal signal behavior in replay and the affected runtime path.
- No future-event influence on earlier veto decisions.
- Correct resets across gaps and reconnects.
- Unchanged immediate mandatory guards and cancel-time tie rules.
- Exact partial-fill, fee, position-protection, and quantity accounting.
- Frozen parameters, candidate count, cutoff, source exclusion, and observation budget.
- Rejection of old development evidence as independent confirmation.

Code changes require the complete verification profile under [project rules](../AGENTS.md).
Retention follows [historical replay](HISTORICAL_ENTRY_REPLAY.md); this document creates no new runtime store.

## Next authorized boundary

This document records the diagnostic disposition and the completed exploratory signal-duration and entry-queue reconstructions.
The simple transient-signal explanation is not established by the observed results.
No candidate implementation or numerical persistence threshold is recommended from this cohort.
No demonstrated entry-queue defect justifies a model correction based on this sample.
Further execution-counterfactual work requires a separate scope; it cannot turn these old sources into independent evidence.
Stages 2 and 3 remain blocked until a supported mechanism and the listed design decisions receive review.
The current research direction is analytically closed without a database lifecycle transition.
The next task is baseline protocol review, not further veto parameter selection on these sources.
HALT remains active throughout this research work.
