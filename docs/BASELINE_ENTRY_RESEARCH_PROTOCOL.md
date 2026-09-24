# Baseline entry research protocol

Draft date: 2026-09-24.
Status: proposed research design; no candidate, observation budget, or experiment launch is approved.

## Protocol review boundary: 2026-09-24

The operator requests protocol agreement and a qualification closure plan.
This request permits local design review and synthetic verification, not study execution or production changes.
The following proposal is ready for review, but it is not a frozen preregistration.

### Proposed scope

- Use SOLUSDT only, with one positive-flow admission candidate and one unchanged baseline control.
- Require a ready shared signal, positive signed trade flow, and positive order-flow imbalance at the predetermined opportunity timestamp.
- Reuse the signal owner and preserve its causal window semantics; do not search thresholds or persistence delays.
- Use identical opportunities, execution assumptions, sizing, and mandatory safety controls in both arms.
- Record rejected admissions as zero-fill skips; permit no replacement opportunity or second attempt.
- Measure absolute net outcome per eligible opportunity and the paired difference from control.
- Exclude v23 and all outcome-informed development sources from independent selection and confirmation.

An admission skip is not an unresolved exit.
Never assign zero profit to an unresolved position or silently remove it from the denominator.
Do not select a signal window, sample count, or deadline merely to make the study start sooner.

### Qualification closure package

Use the [qualification checklist](BASELINE_EXECUTION_QUALIFICATION.md#qualification-closure-checklist-2026-09-24) before freezing the study.
Each closure requires a reproducible check, an exact implementation identity, a result, and an explicit limitation statement.
Synthetic regression success cannot substitute for authenticated sources or venue execution evidence.
Close the source and temporal contracts separately; archive integrity alone establishes neither.
Historical loss-streak reconstruction remains a separate LIVE gate, even if research qualification later passes.

### Required preregistration deliverable

Before requesting study authorization, produce one reviewed package with these fields:

1. Exact candidate and control identities, including signal window, sizing, execution parameters, and implementation hashes.
2. A future cutoff and chronological eligibility rule with source exclusions, non-overlap, gap, and reconnect semantics.
3. A minimum relevant net effect and a justified independent sample size, block allocation, and maximum duration.
4. A bounded compute and external-storage budget with preservation requirements and an insufficient-capacity stop rule.
5. Fixed absolute and paired acceptance criteria, uncertainty estimation, dependence treatment, and comparison-count control.
6. Fixed rules for missing, invalid, censored, and incomplete paths; prohibit outcome-based replacement and optional stopping.
7. A disjoint confirmation design and explicit rejection, inconclusive, and safety-stop outcomes.

Acceptance must establish positive absolute expectancy and the registered paired improvement, with uncertainty controlled under the reviewed method.
Current project thresholds remain minimum constraints; this proposal supplies no substitute numeric thresholds.
If qualification or a defensible sample budget is unavailable, record BLOCKED instead of starting an underpowered study.

### Authority checkpoints

| Action | Current authority |
|---|---|
| Local protocol review and synthetic checks | Requested for this task |
| Candidate implementation or accounting correction | Requires a bounded implementation scope after the review |
| Private collection, key registration, or archive decryption | Requires separate exact source and custody approval |
| Future study launch or new outcome access | Requires the completed preregistration and explicit approval |
| Paid Mainnet validation | Requires separate attempt, exposure, and turnover limits |
| Promotion, HALT reset, or LIVE orders | Not authorized by research approval |

No new generation number is assigned, and no cohort is imported, replaced, or frozen by this document.

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

### Source and time contract for the proposed study

This review retains the existing causal contract; it does not introduce retrospective availability assumptions.
Use independently qualified future observations for the proposed study.
Existing outcome-informed data remain development evidence, even after an implementation correction.

Keep three evidence tracks separate:

| Track | Permitted conclusion | Cannot establish |
|---|---|---|
| Historical account reconstruction | Supported opening inventory, movements, fills, and loss-streak provenance | Independent strategy performance or earlier local market-data receipt |
| Execution qualification | Order-bound quantity, fee, protection, and timing evidence | Positive strategy expectancy or permission to trade |
| Future strategy evaluation | Registered candidate and control outcomes on qualified future opportunities | Complete account history or independent confirmation from reused paths |

For public observations, require a pinned manifest, complete archive verification, independently registered signer, reviewed collector identity, and bounded clock evidence.
Sequence gaps, changed bytes, stale observations, and invalid clock intervals block the affected evidence.
A collector signature authenticates collector claims; it is not an exchange signature or independent proof of source truth.

For private fills, require independently verified account association, approved credential scope, exact timestamped response bytes, and complete terminal-order binding.
Keep account association evidence protected; public reports contain only safe verification results and opaque references.
Do not accept a caller-supplied account label, encrypted package, or journal agreement as independent account verification.
The account-verification design below is proposed; its implementation and production activation remain separate approval boundaries.
Current private packages remain claims with both admission flags false.

The existing BNB converter requires `market_time_ms <= available_at_ms < fill_time_ms`.
It also requires `fill_time_ms - market_time_ms < max_age_ms`.
The signed reader uses the conservative upper receipt bound, rounded upward to milliseconds.
Same-millisecond availability does not establish ordering and remains rejected.
Pin the maximum age and clock limits before collection; do not relax them after observing rejection.
No candle close, later download, inverse-price fallback, or current price can replace missing causal evidence under this contract.

Fee valuation availability and candidate-signal availability are separate checks.
A valid commission reference does not prove that every signal input was available before its decision.
Neither check independently authenticates the private fill timestamp.

The retained September public diagnostic cannot qualify the earlier historical fills through relabeling or another signature.
Do not generate real trades to manufacture missing qualification evidence under this research approval.
If existing sources cannot close the contract, record the specific missing input and request a separate bounded source scope.

### Proposed independent account binding

The official [Spot account contract](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#account-information-user_data) documents `uid` in `GET /api/v3/account`.
The [API permission contract](https://developers.binance.com/en/docs/catalog/core-trading-wallet/api/rest-api/account) documents `GET /sapi/v1/account/apiRestrictions`.
These references were checked on 2026-09-24; no authenticated request was made.

Proposed trust root: the operator independently verifies the intended account UID in an authenticated exchange session before the diagnostic.
For a subaccount, establish the exact account context; a parent account identity must not substitute for it.
Do not derive the expected UID from the same API response that the verifier must check.
Pass the expected identity through a protected local channel, never chat, command arguments, logs, or repository content.
This is operator-attested identity enrollment, not exchange-signed evidence or proof against a compromised operator session.

The future diagnostic must use one frozen read-only credential pair for the account and permission checks.
Bind its existing credential-scope fingerprint to the reviewed collector and independently enrolled expected identity.
Compare the returned UID exactly; absent, malformed, or mismatched identity blocks qualification.
Check key permissions independently; account-level `canTrade` and `canWithdraw` do not prove the API key's permissions.
Require reading permission and reject enabled trading, withdrawal, transfer, or other mutation capabilities under the reviewed schema.
Missing required permission fields or unknown capability fields require review, not default acceptance.
Do not enable permissions, rotate credentials, or switch keys to make the diagnostic pass.

The account response also contains balances.
A future authorized implementation must bound the response in memory and exclude balances from output and plaintext persistence.
Any retained identity response must be encrypted under a separately approved retention scope.
Public results contain a random opaque enrollment reference and match status, not a UID or an unkeyed hash of it.
An unkeyed hash of a small identifier space does not provide reliable privacy.
Keep enrollment, credential binding, permission proof, capture identity, and observation times together in the protected evidence chain.

The current collector permits only time, order, and fill GET requests.
It does not implement these two additional endpoints or independently verify account identity.
Do not expand its allowlist during an audit or run its network path merely to test this proposal.

### Existing-package treatment and missing inputs

Current identity verification cannot retroactively prove historical API permissions or account association at the original capture time.
An old package keeps its original bytes, flags, timestamps, and qualification status.
Any later assessment must be a separate source-bound record, never an edited archive or renamed success status.
If historical association remains unsupported, qualify a separately authorized fresh retrieval instead of certifying the old package.
Neither route repairs missing before-fill public observations or establishes complete account history.

| Missing input | How to establish it | Present status |
|---|---|---|
| Expected account identity | Operator enrollment from an independently authenticated account session | Not enrolled for this proposed verifier |
| Key-to-account binding | Exact UID match under the pinned credential | Verifier not implemented or run |
| Key permission proof | Reviewed permission schema and bounded authenticated response | Not collected by this task |
| Complete source binding | Same reviewed credential, collector, order scope, timestamps, and encrypted response evidence | Existing packages remain claims |
| Historical identity continuity | Independently supported association at capture time | Not proved by a current UID response |
| Causal price availability | Qualified observations before each selected fill | Existing late public diagnostic is insufficient |

The local [claim validator](../ladder_dragon/strategy/account_binding.py) implements bounded parsing and structural comparisons without external capabilities.
It requires exact UID and credential-scope matches, a complete permission profile, reading permission, and no mutation permissions.
New permission fields fail closed until schema review.
Successful checks return `CLAIMS_MATCH_ONLY`; authentication and replay flags remain false.
Account bodies are limited to 1 MiB and permission bodies to 16 KiB before JSON parsing.
These limits do not replace streamed transport limits in a future collector.
The helper creates no persistent record and does not validate enrollment, HTTP status, request timing, clock evidence, or source signatures.
It cannot prevent a caller from supplying fabricated matching claims; an authenticated transport and enrollment verifier remain necessary.

The local [diagnostic adapter](../ladder_dragon/strategy/account_diagnostic.py) now connects the validator to bounded authenticated GET transport.
The [enrollment loader](../ladder_dragon/strategy/account_enrollment.py) reads a protected operator claim without creating or independently attesting it.
Required regressions cover foreign accounts, absent UID, mixed credentials, permission changes, missing fields, clock failures, and secret-safe rejection.
Also test oversized bodies, network failures, immutable old packages, and rejection of automatic replay admission.
Before production activation, separately approve the exact SHA, enrollment channel, credential scope, endpoints, request budget, storage, and retention.
No account identifier or credential must be pasted into this conversation to approve the design.

### Local diagnostic implementation boundary

The enrollment schema is `account_enrollment_claim_v1`, with exactly `schema`, `reference`, `uid`, and `credential_scope` fields.
The reference is a separately supplied 32-character lowercase hexadecimal value; independent enrollment must generate it randomly.
The loader validates its form and match, not its randomness or the operator's identity review.
It reads at most 4096 bytes from an absolute path through symlink-free directory descriptors.
The immediate directory must be owner-only; the regular file must have mode `0400` or `0600` and one hardlink.
Allowed owners are root and the effective user; changed file metadata blocks loading.
The returned record is private in-memory input and must not enter logs or public results.

The adapter accepts credentials in memory and validates their scope before any network request.
It permits three sequential GET requests: time, account, and key permissions.
It disables redirects, retries, environment proxies, and certificate-verification overrides.
Time responses have a 1024-byte ceiling; account and permission responses retain the validator's respective limits.
Streamed reads enforce byte ceilings before parsing; each response closes even when validation fails.
The session has a 30-second budget and at most five seconds per transport timeout.
The adapter checks clock safety before private requests and compares wall and monotonic elapsed times after responses.
An external process deadline remains mandatory because operating-system DNS can exceed these in-process limits.

Successful comparison returns `DIAGNOSTIC_MATCH_ONLY`, with all authentication and replay flags still false.
Errors return bounded stage and reason fields, never bodies, balances, identifiers, credentials, or provider exception text.
No CLI, enrollment writer, production caller, archive writer, or old-package modification is added.
Synthetic tests exercise the adapter; no real enrollment or network diagnostic is performed for this implementation.

### Isolated process boundary

The local [process wrapper](../ladder_dragon/strategy/account_diagnostic_process.py) runs the diagnostic in a disposable interpreter with `-I`.
Its default and maximum process-wait limit is 35 seconds; smaller integer limits remain available for synthetic checks.
On timeout, the subprocess runner kills and reaps the direct child; it never retries the diagnostic.
Process creation and kernel termination are not hard real-time operations, so the limit is not a guaranteed wall-clock bound.
The trusted worker starts no descendants.
Interpreter isolation is not an operating-system sandbox or a production service configuration.

Credentials, the enrollment path, and its reference cross an anonymous stdin pipe, never command arguments or inherited environment variables.
The child receives only the dotenv-disable environment setting and closes unrelated file descriptors.
The worker bounds its input before parsing and emits only a revalidated fixed result.
The parent discards stderr, rejects nonzero exits, and revalidates the result schema and all false admission flags.
Only trusted repository worker code can produce stdout; provider response bodies never reach that stream.
Timeout reports discard partial child output and contain no credentials or provider error text.

The wrapper requires `confirmed=True`; the default makes no process or network request.
This Boolean is a caller interlock, not a substitute for explicit operator authorization.
No production caller, scheduled task, or CLI invokes the wrapper.
Real process tests use synthetic sleep or a missing enrollment path; they make no exchange requests.

### Proposed enrollment custody procedure

WARNING: Do not submit UID, keys, secret values, or enrollment contents in chat or command arguments.
This procedure is planned; no production enrollment is created by this change.

1. Review the intended account context in an independently authenticated exchange session.
2. Select the existing read-only credential through the separately approved protected credential channel.
3. Verify the intended credential association without deriving the expected UID from the diagnostic response.
4. Generate a random enrollment reference locally before preparing the protected record.
5. Record the expected UID, credential scope, schema, and reference in the approved protected location.
6. Review ownership, directory permissions, file mode, and exact contents through the protected operator channel.
7. Preserve an encrypted recovery copy under the approved backup policy before production use.
8. Approve one exact diagnostic SHA, enrollment reference, credential scope, and bounded invocation separately.

Production enrollment requires an explicit storage and custody decision; this guide selects no private filesystem destination.
The loader accepts only owner-only directories and regular files with mode `0400` or `0600`.
The assertion is authoritative only for the operator's intended account, not exchange ownership, historical identity continuity, or account completeness.
Credential changes require a new reviewed enrollment reference; do not silently reuse the old binding.
Revocation must prevent future use without deleting the previous evidence.
An eventual enrollment manager must enforce that revocation; the current loader has no registry or revocation mechanism.

Proposed capacity is eight immutable enrollment assertions, each at most 4096 bytes, before a separate capacity review.
Preserve superseded assertions as encrypted evidence until explicit review; no automatic deletion or rotation is proposed.
Do not include plaintext enrollment records in backups, Git, status pages, or general logs.
Approve encrypted retention, recovery verification, and audit ownership before creating the first production record.

A future enrolled identity is an authoritative operator assertion of intended account scope, not proof of exchange ownership.
This implementation creates no persistent record or maintenance job.
Before production enrollment, approve protected storage, encrypted recovery, revocation, retention, and audit ownership for that assertion.
Do not place real enrollment files in Git or ordinary plaintext backups.

### Budget derivation before launch

This review does not assign an arbitrary path count or deadline.
The budget must be a feasibility result, not a target copied from v23.

1. Fix the candidate, control, execution contract, and minimum relevant absolute and paired net effects.
2. Select the uncertainty method, error limits, target power, and dependence assumptions before accessing future study outcomes.
3. Use disclosed development evidence or conservative synthetic assumptions to assess variance, dependence, zero fills, and censoring.
4. Evaluate sample-size sensitivity across those assumptions without treating reused paths as independent observations.
5. Specify independent blocks and a disjoint confirmation budget under the same capacity constraints.
6. Measure compute and archive growth using synthetic inputs or separately authorized metadata-only measurements.
7. Freeze maximum paths, duration, storage, and stopping rules before requesting launch authority.

Do not estimate precision solely from the few profitable v23 fills or only from completed positions.
Retain all registered opportunities in the estimand and apply the reviewed incomplete-outcome rule.
Non-overlapping paths do not automatically prove independence; the method must address remaining temporal dependence.
Evaluate both absolute expectancy and paired improvement; a smaller expected loss is not sufficient.

The latest observed external capacity is approximately 11 GiB free; this is not an approved research allocation.
Reserve space for normal archives, verified backups, database growth, and maintenance before assigning any study capacity.
Do not delete evidence or reduce existing backup guarantees to fit the study.
If the required precision exceeds approved capacity or duration, stop with an infeasible-budget result.

The resulting budget memo must disclose its assumptions, sensitivity results, exact method, implementation identity, and unresolved evidence limits.
Numeric budgets and acceptance thresholds remain unapproved until that memo exists.

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
The [qualification checklist](BASELINE_EXECUTION_QUALIFICATION.md#qualification-closure-checklist-2026-09-24) separates implemented synthetic protections from missing empirical evidence.
The causal time contract is retained; retrospective relabeling is excluded from this proposal.
The account-binding design and input-gap inventory are now documented; no account association has been verified by this task.
The claim validator, protected loader, and bounded diagnostic adapter are implemented locally and tested with synthetic inputs.
The isolated process wrapper and proposed custody procedure are now documented and tested locally without real enrollment.
The next decision is the protected production enrollment channel, custody owner, and exact one-shot diagnostic authorization.
Production identity enrollment and network diagnostics require separate authorization.
Then prepare the sensitivity-based budget memo and complete preregistration package after the qualification inputs are established.
Candidate parameters, the observation budget, and experiment launch remain unapproved.
Further veto tuning, a new Mainnet batch, and release or deployment are outside this boundary.
