# Historical source collection plan

Prepared: 2026-09-16.
Status: planned, not implemented or authorized for collection.
The operator authorizes preparation and release deployment, not another private request or accounting import.

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

This is a future collector specification, not an available command.
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

The next local task is the collector implementation with synthetic tests, after review of this scope.
A later collection request must name its signed SHA, exact destination, trusted registration, credential scope, and the limits above.
Do not start collection from a general release or Pi-update authorization.
See the [readiness review](READINESS_RECOVERY_REVIEW.md) for the unresolved trading gates.
