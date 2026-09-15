# Baseline entry research protocol

Draft date: 2026-09-13.
Status: proposed research design; no candidate, observation budget, or experiment launch is approved.

## Purpose and boundary

The [v23 review](V23_SELECTION_REVIEW.md) records negative baseline gross and net results on twelve independent paths.
The reviewed veto policies also fail selection.
These observations justify a baseline review, but they do not prove that every baseline entry design fails.

This protocol separates entry opportunity quality from optional veto behavior.
The research question is whether a causally defined passive entry has positive net outcome per eligible opportunity.
An executable hypothesis must explain why its entry condition should predict subsequent price movement after costs.
Higher fill count alone is not the objective.

This document authorizes no code execution, source import, database transition, production change, or trading action.
HALT and all mandatory risk controls remain unchanged.
The protocol creates no runtime store and assigns no new generation number.

## Proposed study design

The proposed design compares one baseline candidate with the unchanged reviewed baseline on identical future opportunities.
Both arms retain identical reviewed execution assumptions and mandatory safety controls.
The optional veto is outside this study's parameter search.
Its absence in a research comparator does not authorize a production configuration change.

The primary outcome is net simulated USDT per eligible opportunity, including zero-fill attempts and all modeled costs.
The paired difference from the unchanged baseline is a separate required comparison.
A candidate must demonstrate positive absolute expectancy, not merely a smaller loss than its control.

Gross result, fees, fill rate, queue state, holding time, and exit reasons are secondary diagnostics.
Profit per filled trade cannot replace the primary outcome after results appear.
Repeated policies on one path do not increase the independent sample count.

## Stage A: mechanism and execution review

1. Document one causal entry mechanism before selecting numerical parameters.
2. Specify the signal inputs available at each decision timestamp.
3. Separate entry price reachability from queue depletion and later exit quality.
4. Review liquidation depth, impact, fees, partial fills, and replay/runtime parity.
5. Record unresolved model limits before granting any result selection authority.

The old v23 sources are development evidence only.
They can expose defects or generate hypotheses, but cannot validate a hypothesis derived from their outcomes.
A verified model defect requires a separate correction and regression tests on unchanged inputs.
Such a correction does not convert those inputs into independent confirmation.

Stage A ends with a mechanism memo, an execution-contract review, and either one candidate proposal or a documented stop decision.
No persistence interval, entry offset, or exit parameter is selected by this draft.

The [Stage A review](BASELINE_ENTRY_MECHANISM_REVIEW.md) proposes positive-flow admission and records unresolved execution limitations.
It establishes neither positive expectancy nor permission to launch Stage C.

## Stage B: preregistration and budget review

The following fields must receive review before new outcome access or experiment launch:

| Field | Required decision | Current status |
|---|---|---|
| Candidate | Exact causal rule, parameters, and implementation hash | Not selected |
| Control | Immutable baseline identity and execution assumptions | Not frozen for this study |
| Eligibility | Symbol scope, timestamp rule, overlap exclusion, and gap handling | Not approved |
| Comparison count | One proposed candidate; fixed treatment of all comparisons | Not approved |
| Evidence boundary | Future cutoff, source exclusions, and chronological allocation | Not frozen |
| Sample budget | Independent path count, blocks, precision target, and maximum duration | Not approved |
| Resource budget | Replay compute, external storage, and retention requirements | Not approved |
| Statistical rule | Estimator, uncertainty method, dependence treatment, and acceptance thresholds | Not approved |
| Attrition | Missing, censored, invalid, and incomplete path treatment | Not approved |
| Confirmation | Separate future sources, capacity, and execution validation | Not approved |

The budget review must justify sample size against the minimum relevant net effect and expected uncertainty.
Twelve paths and four blocks are not automatically sufficient for this different research question.
Existing project gates remain minimum constraints; a new protocol cannot silently replace them.
If a feasible budget cannot support the decision, the study must not start.

Unresolved or censored outcomes must not become zero-profit attempts or disappear from the denominator silently.
Their preregistered treatment must preserve conservative accounting and disclose attrition.
All existing v23 source hashes and outcome-informed development sources must be excluded from independent evaluation.

## Stage C: future evaluation and stopping rules

Future selection uses sources after the approved preregistration boundary.
Eligibility must depend only on information available at the decision timestamp.
The study must report all registered opportunities, candidates, controls, and exclusions.

- A safety or evidence-integrity violation blocks acceptance and requires investigation.
- A nonpositive estimated net outcome cannot pass positive-expectancy selection.
- Insufficient uncertainty evidence produces an inconclusive result, not a PASS.
- Failure against either absolute or paired acceptance criteria prevents advancement.
- An expired budget ends collection under the registered rule; it does not authorize extensions or replacement paths.
- Passing selection permits only a separate confirmation review, not promotion or LIVE execution.

No scheduled health check can import, freeze, bootstrap, or promote this research.
The Pi monitor checks host safety while the research remains a separate reviewed task.

## Future implementation and harness requirements

Any later implementation must prove causal replay/runtime agreement and unchanged mandatory guard authority.
Regression tests must cover partial fills, cancellation races, protection, fees, quantities, and restart idempotency.
The harness must reject changed parameters, reused development sources, overlapping paths, and outcome-selected exclusions.
It must also distinguish computational completion, statistical acceptance, and execution authorization.

These checks are planned requirements, not implemented capabilities supplied by this document.
Code verification follows [project rules](../AGENTS.md).
Evidence retention follows [historical replay](HISTORICAL_ENTRY_REPLAY.md).

## Next deliverable

The Stage A memo is complete as a source-based review, with one unvalidated candidate proposal.
The [synthetic qualification](BASELINE_EXECUTION_QUALIFICATION.md) reproduces four model limitations without changing execution code.
The next proposed task is the coordinated correction and qualification scope defined there.
Candidate parameters, the observation budget, and experiment launch remain unapproved.
Further veto tuning, a new Mainnet batch, and release or deployment are outside this boundary.
