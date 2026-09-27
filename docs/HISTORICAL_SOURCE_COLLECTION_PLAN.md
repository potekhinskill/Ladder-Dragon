# Historical source collection plan

Prepared: 2026-09-16.
Status: local collector implementation; production collection remains unauthorized.
Current authorization covers local implementation and synthetic verification, not publication, deployment, private requests, or accounting imports.

## Local implementation: 2026-09-27

`strategy/history_pages.py` validates complete pages before cursor advancement, with exact decimals, strict identities, commissions, sequence, and receipt intervals.
`strategy/history_capture.py` connects the existing read-only signing adapter to sequential SOLUSDT requests with fixed limits.
`strategy/history_archive.py` signs source claims under a separate domain and encrypts them before any file write.
`strategy/history_capture_process.py` requires explicit caller opt-in and bounds the child process, including blocked operating-system DNS.
The default process entry returns `AUTHORIZATION_REQUIRED` without creating a process or making a request.
No CLI, service, scheduler, credential discovery, source import, or automatic production caller is added.

The implementation starts at `fromId=0` and preserves the exclusive cutoff stated below.
It does not combine `fromId` with time filters; cutoff classification occurs after complete page validation.
The current official account API documents inclusive `fromId` pagination and a maximum page size of 1000.
This collector retains the stricter 200-row page and twenty-page limits.
A short page or observed cutoff is a stopping observation, not proof of complete exchange retention or opening inventory.
Reaching twenty pages reports `LIMIT_REACHED`, even if the last page also observes the cutoff.

The process timeout is at most 150 seconds, followed by termination and reap handling.
Operating-system process creation and reaping prevent a hard real-time completion guarantee.
Cooperative response limits cannot interrupt blocked DNS alone; the process wrapper remains mandatory for any future activation.
The wrapper starts a clean isolated Python interpreter with an explicit environment and closed inherited file descriptors.
Bounded anonymous stdin carries validated private inputs; credentials never enter command arguments or temporary plaintext files.
The returned status has strict fields, value limits, and fixed failure codes; provider text is rejected.
Use a separately reviewed single-purpose launcher for production; host isolation and protected credential loading remain activation prerequisites.
This implementation does not guarantee memory erasure, disable host swap, or establish independent account ownership.

Storage uses one new exclusive `historical-sol-source-v1` directory on a verified external mount.
It requires an owner-controlled parent, an owner-only slot, and sufficient free space before retrieval.
An unsuccessful retrieval can leave an empty reserved slot; an interrupted write retains its ciphertext.
No retry reuses the slot, and no automatic cleanup removes it.
See [retention](DATA_RETENTION.md#historical-source-claims) for capacity and preservation requirements.

Both archive validation and returned status retain `history_complete=false`, `private_fills_authenticated=false`, and `replay_allowed=false`.
Signatures and exact hashes bind claims; they do not prove historical account association or order-level completeness.
Keys, independent registration, recovery verification, credential permissions, and shared rate-limit capacity require separate review before real collection.
The current implementation has no private-network activation in this task.

Initial collector verification: 66 new regressions and 165 focused collector and archive tests pass.
After process isolation, the full suite passes with 5137 tests and two skips.
Compilation, five safety audits, secret scanning, and Semgrep pass.
Real synthetic child-process tests verify default refusal, timeout termination, and reaping without exchange access.
Storage regressions preserve occupied slots, interrupted ciphertext, and false admission flags after signed-claim substitution attempts.
The current local artifact is `.runtime/verification-local-2.20.349-history-isolation.json`.
Its aggregate status remains BLOCKED by candidate release continuity and dependent architecture checks; it is not a release PASS.
Separate diagnostic comparison against HEAD finds no new cycles or mandatory size violations.
Production use still requires reviewed protected integration and an unchanged signed-candidate release profile.

## Protected-launch review: 2026-09-27

This review checks existing local components; it does not create credentials, enrollment records, a production launcher, or network authority.
The protected enrollment loader verifies bounded regular files, ownership, permissions, immutable metadata, and an independently supplied reference.
The account diagnostic compares the supplied key scope with that enrollment before any request.
It rejects absent permissions, missing read permission, and every supported mutation permission.
Its isolated interpreter receives credentials through anonymous stdin, with a restricted environment and a 35-second outer deadline.
The Ed25519 loader independently checks protected file access and the pinned public-key fingerprint.

Selected synthetic tests pass: 238 account-binding, diagnostic, process, and signing-credential tests.
These results do not verify the current production key, its permission set, or the existence of an approved enrollment record.
No private file values or live account responses were read for this review.

### Request budgets remain separate

| Stage | Proposed authority | Requests | Deadline |
|---|---|---|---|
| Account and key diagnostic | Separate approval; compare the independently enrolled account and current read-only key permissions | At most three GET requests: time, account, and API restrictions | 35 seconds |
| Historical source collection | Existing bounded proposal; only time and SOLUSDT trade pages | At most 22 GET requests | 150 seconds plus bounded termination handling |

The diagnostic uses `/api/v3/time`, `/api/v3/account`, and `/sapi/v1/account/apiRestrictions`.
Account and permission endpoints are outside the history collector's current allowlist and must not consume an undocumented extra budget.
Executing both stages could require 25 requests; the existing 22-request proposal does not authorize that combined operation.
Do not run collection automatically after a diagnostic match; preserve separate consent and shared rate-limit capacity checks.
The result remains `DIAGNOSTIC_MATCH_ONLY`, not historical account authentication, complete history, or replay admission.

### Clean-interpreter implementation: 2026-09-27

The isolated subprocess replaces the fork wrapper; it does not provide an operating-system sandbox or independent authority.
The operator agrees to the separate diagnostic scope of three GET requests and 35 seconds.
No request runs before verification of the exact registration, credential source, and approved code revision.
History collection does not follow a diagnostic automatically.
Focused isolation, collector, and diagnostic-process tests pass: 142 tests, with synthetic keys and no exchange access.

### Remaining protected integration

A production launcher still needs reviewed credential delivery, independent enrollment reference, registration, encrypted key recovery, and host restrictions.
Do not derive the expected account identity from the same response that is supposed to verify it.
Do not rediscover credentials by scanning environment files or silently reuse the old diagnostic registration.
Pin the reviewed code, exact external destination, current credential scope, and appropriate request budget in each activation approval.
The operator subsequently approves the [enrollment custody locations](BASELINE_ENTRY_RESEARCH_PROTOCOL.md#concrete-custody-proposal-2026-09-27).
Local creation components do not create a production trust assertion or activate collection.

## Objective and boundaries

Reconstruct SOL inventory and loss-streak provenance without changing authoritative records.
Keep HALT, execution approval, and replay admission unchanged.
Separate source comparison, inventory reconstruction, and strategy qualification; none implies completion of the others.

The initial market scope is SOLUSDT only.
The historical cutoff is 2026-09-16 00:00:00 UTC, exclusive.
Do not use the earliest local trade as proof that earlier inventory was zero.
The required lower boundary is independently supported opening inventory, or a demonstrated zero-inventory boundary before the imported history.
That lower boundary remains unknown and must be recorded before reconstruction can pass.

## Source inventory before collection

1. Pin the applied import metadata and local ledger identities through read-only SQLite queries.
2. Identify an original exchange export covering SOL trades and movements through the cutoff.
3. Record source account association separately from hashes and collector signatures.
4. Establish whether deposits, withdrawals, transfers, Convert, Earn, or other SOL markets affect the opening inventory.

The initial collector must not scan other markets or wallet endpoints automatically.
Any relevant activity outside SOLUSDT requires a reviewed extension or an operator-supplied original export.
An export alone does not authenticate its account association or prove that all movement categories are covered.
Missing source records remain an explicit blocker; no estimated purchases or zero-cost substitutions are permitted.

## Proposed bounded trade retrieval

This contract is implemented as local library components, not an available production command.
The existing private collector accepts up to eight order-bound packets, not a paginated full-history export.
Do not increase its limits or reinterpret its output as complete account history.

| Boundary | Proposed limit |
|---|---|
| Venue and market | Binance Mainnet, SOLUSDT only |
| Allowed methods | GET only |
| Allowed paths | `/api/v3/time` and `/api/v3/myTrades` only |
| Request budget | 22 total: two clock checks and at most 20 trade pages |
| Page capacity | 200 records; at most 4000 received records |
| Concurrency and retries | One sequential request; zero retries or redirects |
| HTTP response ceiling | 256 KiB encoded and decoded per trade page; 1024 bytes per clock response |
| Timing | Five seconds per complete response; 150-second outer process deadline |
| Storage ceiling | One exclusive encrypted package; at most 16 MiB including metadata |

Pagination uses an explicit trade-ID cursor, not the endpoint's default recent-history result.
Advance only after complete validation of the current page; reject duplicates, changed identities, and a non-advancing cursor.
Trade identifiers need not be consecutive; numerical gaps alone do not prove missing account fills.
Freeze all request parameters and the cutoff before collection.
Retain any beyond-cutoff boundary records as excluded evidence, without admitting them to historical calculations.
Hitting any request, byte, time, or record limit produces an incomplete result, not successful coverage.
An empty or short final page cannot independently prove that the venue retains all historical records.

Review pagination behavior and endpoint limits against the current [official REST account documentation](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/account) before implementation.
The request budget is a hard ceiling, not a claim of rate-limit availability.
Stop on authentication errors, rate limits, clock failure, malformed responses, or insufficient shared request capacity.
Do not retry automatically or change system DNS, TLS validation, service configuration, or clock thresholds.

## Trust and storage prerequisites

Use only the independently identified dashboard credential with verified read-only exchange permissions.
Do not print credentials, request signatures, raw source records, account identifiers, or provider exception text.
Bind exact response bytes, page order, request intervals, scope, reviewed collector SHA, and registration before encrypted persistence.
Preserve unknown source authentication explicitly; a signature proves collector claims, not independent account ownership.

Register trust and verify recovery before any private retrieval.
Select a new exclusive directory on the verified external disk, never the Pi system storage.
Pin its exact path and expected absence in the final collection authorization.
Preserve all existing diagnostic slots and backups; do not overwrite, relocate, or delete them.
Retain the bounded package as unresolved evidence until explicit review; no recurring collection or automatic deletion is planned.
Reject an absent external mount, unsafe permissions, symlinks, insufficient headroom, or a pre-existing destination.

## Offline acceptance and implementation checks

Compare exact timestamps, sides, quantities, prices, quote totals, and commission fields against the local ledger.
Report matched, missing, changed, and extra rows separately without rewriting legacy records.
Reconstruct inventory only after opening inventory and all relevant movements are independently supported.
Keep order-level completeness unproved until terminal orders and their complete fills are separately bound.
Historical commission valuation must satisfy its causal contract; new public observations cannot supply earlier availability.
This scope cannot recover missing Mainnet rejection codes or replace execution-type qualification.

Before implementation completion, test pagination boundaries, truncation, duplicate fields, cutoff handling, and counter exhaustion with synthetic inputs.
Also test clock and DNS deadlines, secret-safe failures, storage interruption, source substitution, and rejection of replay-authority relabeling.
Run the complete code verification and release profiles before any approved production installation of a new collector.

## Next authorization boundary

The next activation task is a protected host launcher review after complete local verification.
A later collection request must name its signed SHA, exact destination, trusted registration, credential scope, and the limits above.
Do not start collection from a general release or Pi-update authorization.
See the [readiness review](READINESS_RECOVERY_REVIEW.md) for the unresolved trading gates.
