# Baseline execution qualification

Review date: 2026-09-13.
Status: four synthetic characterizations reproduced; execution qualification remains incomplete.

## Qualification closure checklist: 2026-09-24

This checklist supersedes historical next-step statements below; it does not rewrite their evidence or recorded results.
The operator requests a closure plan, not permission to declare incomplete evidence qualified.
The deployed reference is `2.20.345`; current readiness is recorded in the [recovery review](READINESS_RECOVERY_REVIEW.md).

| Boundary | Established evidence | Evidence required for closure |
|---|---|---|
| Partial entry and protection | Runtime and replay preserve partial quantity and settle cancellation in synthetic regressions | Exact current execution identities and supported venue timing; retain HALT for uncertain cancellation |
| STOP and emergency exit | Synthetic checks cover conditional activation and depth-limited liquidation | Source-bound execution calibration; incomplete exits remain censored |
| Commission quantity | Shared accounting and journal settlement validate complete order-bound quantities | Authenticated timestamped fills and supported fee-asset valuation |
| Private-source provenance | Encrypted collector claims and package recovery exist | Independent account binding and an approved composed attestation verifier |
| Causal BNB valuation | The converter rejects late or stale observations | Authenticated observations available before each selected fill |
| Dust and residuals | Full-coverage rejection remains the safe behavior | Prove supported sizing avoids residuals, or separately review explicit residual ownership and protection |
| Replay admission | Scenario reports cannot become selection evidence | Complete qualified inputs, unchanged mandatory guards, and paired runtime/replay review |
| Selection and confirmation | No accepted artifact or active CHAMPION exists | A separately authorized future study and disjoint confirmation |

The public diagnostic archive was observed after the historical fills discussed in the provenance review.
Authenticating those fills cannot repair this temporal mismatch.
Do not repeat current price collection or paid trading merely to relabel historical availability.
A retrospective data contract would require separate review; it cannot silently replace the existing causal contract.

The reported Apple Passwords recovery result is `APPLE_COPY_RECOVERY_VERIFIED`.
It supersedes the historical pending-copy note, but preserves `private_fills_authenticated=false` and `replay_allowed=false`.
This task does not repeat recovery, decrypt archives, or access credentials.

### Closure order

The [source and time contract](BASELINE_ENTRY_RESEARCH_PROTOCOL.md#source-and-time-contract-for-the-proposed-study) retains causal admission and separates three evidence tracks.
Its budget procedure requires feasibility evidence before selecting a path count or study deadline.
Account-association verification remains a design blocker; the current encrypted claims cannot close it automatically.
The [proposed account binding](BASELINE_ENTRY_RESEARCH_PROTOCOL.md#proposed-independent-account-binding) now defines independent identity enrollment and separate key-permission verification.
The pure validator, protected loader, and bounded authenticated adapter are implemented locally with synthetic tests.
The isolated process wrapper now bounds the diagnostic wait and kills and reaps a timed-out child in synthetic tests.
Actual independent enrollment, protected production integration, and production verification remain absent.
A present-day identity match cannot certify the old package's historical account association.

1. Fix the proposed source-authentication and temporal contract before requesting additional collection.
2. Identify required missing inputs without changing occupied archive slots or historical reports.
3. Obtain separate bounded collection authority if existing inputs cannot satisfy the contract.
4. Verify complete fill identity, quantity, commission assets, and causal valuation under that contract.
5. Verify runtime and replay behavior together, including cancellation, protection, restart, residuals, and incomplete exits.
6. Record each boundary as qualified, blocked, or unsupported with exact evidence references.
7. Request protocol freeze only after the required research boundaries are qualified.

The final review must distinguish research qualification from LIVE readiness.
Loss-streak completeness, reviewed CAPs, accepted CHAMPION authority, and operator approval remain independent LIVE requirements.
No document update, hash check, or passing synthetic test clears those gates.

### Local verification for this review

The selected settlement, historical execution, commission, signed-capture, and private-capture tests pass on 2026-09-24.
These are focused synthetic checks, not a complete release profile or fresh production-source qualification.
That readiness review changes only documentation; the later pure claim validator is a separate local implementation.
The validator does not change execution, accounting, or admission authority.

## Local implementation progress

The unpublished 2.20.341 candidate adds partial-entry settlement in both runtime and historical replay.
Runtime cancels the verified BUY remainder and rereads the terminal order before protection.
An uncertain or non-monotonic result preserves tracking and triggers HALT.
Replay requests cancellation after its first partial fill and retains additional fills until cancellation becomes effective.
The current model identifier is `historical_net_inventory_scenarios_v4`.
Old artifacts remain unchanged and cannot silently acquire this model identity.

Fifteen settlement regressions, the full suite, compilation, and five safety audits pass locally.
The cancellation interval still contains exposure; this change does not claim instantaneous protection.
STOP activation now uses the existing exchange-conditional matcher interface without a second client transport delay.
The model waits for protection arrival and excludes reuse of the trigger timestamp.
Emergency exits consume available bid depth and retain unresolved quantity when capacity is insufficient.
Same-event taker fills and SELL-aggressor trades reduce the remaining capacity.
Unresolved exits have no final net PnL and cannot qualify as complete selection evidence.
Runtime already rejects incomplete MARKET flatten acknowledgements; its protection regressions remain part of the paired review.
Exact venue timing and fee-asset qualification remain unfinished.
The updated full suite passes with 2663 passed and 2 skipped.
Ten new exit regressions cover activation timing, capacity, residuals, repeated calls, and invalid depth.
No publication or deployment has occurred.

### Remaining commission boundary

Legacy parents without settlement still use gross `executed_qty` for coverage.
Parents with verified settlement now use net inventory in protection validation and the final exit writer.
The worker now produces settlement before protection and sizes SELL from the verified net residual.
See [quantity validation](../ladder_dragon/execution/protection_quantity.py) and [the final writer](../ladder_dragon/execution/journal/exit_evidence.py).

The remaining correction must bind exact fills to their BUY order and verify their gross sum against its terminal execution.
It must propagate net acquired quantity through protection, partial exits, final closure, and replay.
Unknown fee assets cannot become inferred base or quote fees.
Existing immutable rate-only context cannot retroactively attest the asset actually charged.
No fee-settlement correction is included in the completed STOP and depth changes.

### Settlement validator preparation

The local candidate now contains a pure [BUY settlement validator](../ladder_dragon/execution/buy_settlement.py).
It binds unique fill identities and exact gross totals to a terminal BUY order.
It derives net inventory through `TradeExecution`, without treating quote valuation as a base-asset deduction.
Supported fee assets are the market's base asset, its quote asset, and BNB; other assets fail closed.
BNB quantity handling does not establish its quote valuation or final profit.

Inputs require bounded plain decimal strings.
A separate 512-digit arithmetic context preserves deductions and coverage checks independently of ambient precision.
Twenty-two regressions cover identities, completeness, duplicate fills, fee assets, small commissions, and order-independent aggregation.
The final validator candidate passes the full suite: 2685 passed and 2 skipped.
Compilation and all five safety audits also pass.

The validator has no exchange interface, persistent store, or execution authority.
The journal now persists immutable order-bound evidence and revalidates it for protection coverage and exact closure.
Runtime now produces these records; historical replay still lacks fee-asset settlement.
Its result must not become trusted authority through generic metadata updates.
Integration must validate the underlying order-bound evidence at the final writer, including after restart.
Thus the complete commission correction remains unfinished despite the passing validator tests.

### Journal integration

Generic metadata updates cannot insert or replace settlement evidence.
The dedicated writer checks complete fills against durable order quantities before its atomic write.
Coverage and final closure revalidate those fills after restart instead of trusting a stored net total.
Independent decimal contexts preserve small fees through residual arithmetic.
Legacy records do not receive inferred zero-fee attestations.
See the [retention contract](DATA_RETENTION.md) for evidence capacity and preservation rules.
Seven journal regressions pass, including restart, replacement rejection, capacity, net closure, and low ambient decimal precision.
The integrated local candidate passes 2692 tests, with 2 skipped; compilation and five safety audits pass.
These results do not complete runtime or historical commission qualification.

### Runtime inventory integration

The worker requests BUY fills by symbol and order ID, starting at trade cursor zero.
It reads at most ten pages of 1,000 fills through the existing signed transport.
Each response is streamed with a 2 MiB decoded-byte ceiling before JSON parsing.
The adapter requires monotonic unique trade IDs and validates complete gross and quote totals before journal persistence.
See the [Binance account trade contract](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/account).

Verified journal evidence avoids another network request after restart.
New and replacement protection use net acquired quantity minus confirmed partial exits.
The account balance can restrict availability but cannot increase this order's inventory.
Missing fills, transport failures, and residuals that exchange quantity normalization cannot cover preserve tracking and trigger HALT.
This change does not invent a dust write-off or grant permission to cancel existing protection after an uncertain read.

The runtime adapter is connected; observed fee-asset qualification, dust disposition, and full execution qualification remain unfinished.
Legacy journal consumers still retain gross coverage until order-specific settlement is available.
Nineteen new regressions cover bounded transport, pagination, fee assets, missing evidence, restart, partial-exit replacement, and worker wiring.
The paired runtime group passes 93 tests; the full suite passes 2711 tests, with 2 skipped.
Compilation, five safety audits, and 20 architecture and documentation tests pass.

### Explicit commission scenarios

Historical policy can specify `commission_asset_scenario` as `QUOTE` or `BASE_BUY_QUOTE_SELL`.
These values are assumptions, not proof of the commission asset charged by the exchange.
Legacy policies without this field use `UNSPECIFIED`.
An executed BUY with unspecified fee assets preserves gross exposure but reports no exact net inventory or final PnL.
BNB scenarios remain unsupported without an explicit valuation contract; runtime BNB quantity handling does not supply that historical evidence.

Base-paid BUY commissions reduce modeled SELL quantity through the same `TradeExecution` owner as runtime settlement.
Their quote value remains in total fees but is added back before the final fee subtraction.
Thus net PnL equals exit proceeds minus gross entry cost minus fees paid outside purchased inventory.
The added-back amount appears as `base_paid_fee_quote`; `gross_pnl_quote` is the corresponding before-fee scenario value.
This calculation does not establish actual cycle ownership or portfolio PnL.

Runtime and replay share the strict full-inventory coverage check after quantity normalization.
An unrepresentable residual remains censored; neither path invents a dust write-off.
A censored replay episode blocks further BUY opportunities for that arm through the rest of its path.
This mirrors the unresolved runtime HALT instead of freeing the slot for another position.

Completed scenario reports use `COMPLETE_COMMISSION_SCENARIO`, not `COMPLETE_SELECTION_REPLAY`.
Their episodes cannot qualify for promotion, and existing selection checkpoints reject these reports.
The CLI can write the diagnostic artifact but returns BLOCKED until qualification is established.
New source fingerprints include commission arithmetic and its canonical accounting dependencies.
Old reports and checkpoints are not modified.
Eleven scenario regressions and 60 paired runtime and replay tests pass locally.
The full suite passes 2722 tests, with 2 skipped; compilation and all five safety audits pass.
These checks establish the local scenario behavior, not empirical fee-asset qualification or trading readiness.

### Scenario acceptance boundaries

Combined path reports preserve `COMPLETE_COMMISSION_SCENARIO` when all paths finish without a missing-history result.
An incomplete path still makes the combined report incomplete.
Selection validation, checkpoint reads, checkpoint writes, and complete-path aggregation reject declared commission scenario fields independently of the status string.
This check also rejects a renamed status with recomputed content hashes.
Content hashes establish integrity, not the truth of a financial assumption.
This targeted check does not independently reconstruct exchange provenance when report fields have been removed or fabricated.
Nine new boundary regressions and 50 related tests pass.
The full suite passes 2731 tests, with 2 skipped; compilation and five safety audits pass.

### Causal BNB valuation prerequisite

A pure [reference converter](../ladder_dragon/strategy/prediction/causal_commission.py) now checks exact BNB units against a direct BNB-to-quote price.
It requires market time, availability time, a source reference, and an explicit maximum age.
Availability must precede the fill; same-millisecond ordering remains unproven and is rejected.
Freshness starts at market time, with an exclusive expiry boundary.
Invalid or missing prices return unknown valuation, including when the supplied commission is zero.
The converter uses bounded decimal strings and does not fetch replacement prices.
Twenty-nine regressions cover temporal boundaries, market identity, precision, malformed inputs, and unchanged source data.
The full suite passes 2760 tests, with 2 skipped; compilation, five safety audits, and 20 architecture and documentation tests pass.

This helper is not yet connected to the historical execution model or a production evidence importer.
Its source reference does not authenticate a source or bind commission units to an exchange fill.
Its result is a causal reference value, not an accepted accounting commission status.
BNB scenarios and selection evidence remain blocked until source provenance and fill ownership are established.
Existing retrospective accounting conversion and immutable reports remain unchanged.

### Read-only settlement binding

The [commission evidence adapter](../ladder_dragon/strategy/prediction/commission_evidence.py) connects the causal helper to a durable BUY settlement.
It requires a complete timestamped fill collection that matches the stored settlement projection exactly.
The selected trade must pay its commission in BNB.
The adapter obtains fee units and fill time from that selected row, not separate caller estimates.
Legacy parents without settlement and changed durable quantities are rejected.

Callers provide separately pinned SHA-256 hashes for the fill collection and one recorded public `aggTrade` row.
The parser checks byte limits, hashes, duplicate JSON fields, market identity, and event and receipt times.
Receipt time determines availability; market time determines freshness.
Hashes pin exact bytes but do not authenticate their exchange origin.
The adapter requires external source authentication before its results can become qualified evidence.
The price hash covers one supplied record, not the complete depth archive or its manifest.

Thirty-three new regressions and 69 related tests pass with synthetic data and real temporary journals.
The full suite passes 2793 tests, with 2 skipped; compilation, five safety audits, and 20 architecture and documentation tests pass.
These tests include restart, fill substitution, timestamp changes, bounded parsing, and safe error messages.
The adapter creates only an in-memory derived result; it adds no persistent record, network request, or maintenance job.
It does not change FIFO, protection quantities, replay policy admission, or selection authority.
Source authentication and replay integration remain incomplete.

### Complete archive membership

The [archive adapter](../ladder_dragon/strategy/prediction/commission_archive.py) extracts one exact recorded price row from a caller-owned binary stream.
It checks the pinned manifest, complete archive digest, market identity, event counts, unique selected trade, and explicit byte limits.
It reads the archive once and returns only after the complete digest matches.
The result retains the archive hash, manifest hash, and selected line number beside the fill-bound valuation.
The selected row remains byte-identical to its archive representation.
The adapter creates only in-memory derived results and introduces no persistent storage or retention job.

Twenty new regressions and 82 related tests pass.
The full suite passes 2813 tests, with 2 skipped; compilation, five safety audits, and 20 architecture and documentation tests pass.
Tests include the actual recorder format with synthetic transport, duplicate selection, changed tails, capacity boundaries, and the complete valuation chain.
This proves membership in pinned bytes, not source authenticity, depth continuity, or financial execution qualification.
Manifest authentication, timestamped fill-source authentication, and replay admission remain separate requirements.
The historical execution model still rejects BNB scenarios; this adapter does not weaken that boundary.

### Remaining implementation prerequisites

The [BNB fill verifier](../bin/verify_bnb_fills.py) compares local BNB commission rows with authenticated exchange history.
It opens SQLite with `mode=ro` and `query_only`, then closes the connection before network access.
It requests one candidate fill per local trade identity and compares time, side, price, quantity, commission asset, and commission units.
An exchange response must also contain a valid order identity.
This comparison does not prove the complete fill set of that order or authenticate an older archive.

The command accepts `--stats-db`, `--maximum-rows`, `--maximum-requests`, and `--verify-orders`.
Both limits default to 100; the row limit cannot exceed 100.
Order verification permits an explicit HTTP limit up to 300; ordinary fill comparison retains the 100-request ceiling.
The transport counts clock reads and retries within the HTTP request limit.
Only the fixed Mainnet time and trade-history GET endpoints are allowed; redirects and environment proxies are disabled.
Order verification additionally permits the fixed order-query GET endpoint, never its mutation methods.
Responses have a 64 KiB ceiling, with time budgets checked between requests and body reads.
The host supplies dedicated dashboard credentials through its environment; the command never loads dotenv files.
Output contains aggregate counts and safe failure types, not rows, credentials, order identities, or signed URLs.
The diagnostic creates no persistent record and cannot write accounting or selection state.
Nineteen synthetic regressions pass; successful comparison still reports `replay_allowed=false`.
After command registration, 57 related integration tests and the full suite pass: 2832 passed, with 2 skipped.
Compilation and all five safety audits pass.

On 2026-09-13, a one-shot read-only Pi run compares 87 selected BNB commission rows with current authenticated exchange responses.
All 87 rows match; none are missing or mismatched. The run uses 88 HTTP attempts.
Its result is `MATCHED_NOT_REPLAY_READY`, with `database_written=false` and `replay_allowed=false`.
This aggregate result is not an immutable fill export, an order-completeness proof, or a historical BNB price archive.
The run uses the unchanged deployed client dependencies and does not publish or install the local candidate.

With `--verify-orders`, the verifier checks each distinct terminal order once and collects up to 1000 order-specific fills.
It rejects active orders, duplicate or foreign fills, and invalid or incomplete executed quantity and quote totals.
The selected BNB fill must match its order-specific counterpart, including commission fields and timestamp.
The existing response byte ceiling remains active; oversized evidence fails closed instead of bypassing completeness checks.
Twenty-one new regressions and 40 verifier tests pass with synthetic data.
Successful order verification reports `COMPLETE_ORDERS_NOT_REPLAY_READY`; it creates no durable settlement or imported evidence.
The updated full suite passes 2853 tests, with 2 skipped; compilation and all five safety audits pass.

On 2026-09-13, the order-completeness run matches all 87 selected BNB fills and verifies complete executed totals for 78 distinct terminal orders.
It reports no missing or mismatched selected fills and uses 245 HTTP attempts.
The result is `COMPLETE_ORDERS_NOT_REPLAY_READY`, with `database_written=false` and `replay_allowed=false`.
An initial attempt stops on SQLite `OperationalError` before HTTP access.
A separate read-only database check succeeds, followed by one successful verifier retry; the initial failure cause remains unresolved.
No historical BNB price archive, durable fill export, or settlement record is created by this run.

BNB qualification requires exact fee units, an identified conversion source, and a valuation timestamp valid for the fill.
The converter must reject future or stale prices and preserve unknown quote valuation instead of inserting zero.
The existing accounting converter uses the fill-minute candle close, which can occur after the fill timestamp.
See [commission valuation](../ladder_dragon/execution/executor_stats.py).
That retrospective conversion must not become causal replay evidence without a separate temporal contract.
Existing fills can supply evidence only after their order identities and complete quantities are verified.
A new paid Mainnet batch is not implied by this requirement.

Dust handling needs a reviewed contract for partial coverage, residual ownership, reconciliation, and final closure.
Protecting only the rounded quantity must not mark the entire parent protected or closed.
The residual must remain authoritative inventory with HALT and no automatic write-off.
That behavior is not yet implemented; the current full-coverage gate remains unchanged.

## Official historical-source review

Review date: 2026-09-13. This review changes documentation only, not replay admission or production collection.

The [official public-data guide](https://github.com/binance/binance-public-data/blob/master/README.md) describes daily and monthly Spot archives.
Trade archives contain exchange trade timestamps; aggregate archives also identify their constituent trade range.
Neither documented archive schema contains this bot's historical receipt timestamp.
Spot archive timestamps from January 2025 use microseconds, unlike the current causal adapter's millisecond inputs.
The guide provides checksum verification and states that published archives can receive corrections.

The [REST specification](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md) describes historical trade and aggregate-trade responses.
These responses do not establish when this bot received an earlier market observation.
The [WebSocket specification](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md) distinguishes exchange event time from trade time.
Neither exchange timestamp substitutes for a locally observed receipt timestamp.

The resulting project inference is narrow: official historical prices can support retrospective valuation, but cannot reconstruct missing local receipt evidence.
This does not make historical market data unusable for research.
A model with assumed data availability needs a separately reviewed temporal contract and explicit assumptions.
It must not silently satisfy the current observed-availability gate.

No archive files are downloaded during this review.
Archive row coverage for the exact fill timestamps remains unverified.
Documentation of an archive service does not establish complete coverage of those fills.
Old evidence remains diagnostic; the existing `replay_allowed=false` result remains unchanged.

### Archive availability check

On 2026-09-13, a read-only database query groups the 87 BNB commission rows by market and UTC date.
All rows concern SOLUSDT or ETHUSDT, so the direct commission conversion market is BNBUSDT.
This database grouping selects candidate dates; it is not an authenticated immutable fill export.

Eighteen public HTTPS HEAD requests check daily BNBUSDT aggregate archives and their checksum files.
All requests return HTTP 200 without redirects; certificate verification remains enabled.
No archive or checksum body is downloaded, parsed, or verified.

| UTC date | Selected fills | Archive bytes reported by HEAD | Archive / checksum status |
|---|---:|---:|---|
| 2026-07-18 | 2 | 1980168 | 200 / 200 |
| 2026-07-19 | 2 | 2054023 | 200 / 200 |
| 2026-07-23 | 1 | 2106357 | 200 / 200 |
| 2026-07-27 | 6 | 2506471 | 200 / 200 |
| 2026-07-29 | 1 | 2476552 | 200 / 200 |
| 2026-08-21 | 2 | 8416084 | 200 / 200 |
| 2026-09-01 | 5 | 2760572 | 200 / 200 |
| 2026-09-02 | 10 | 2945712 | 200 / 200 |
| 2026-09-03 | 58 | 4696817 | 200 / 200 |

The source is the [official BNBUSDT daily directory](https://data.binance.vision/?prefix=data/spot/daily/aggTrades/BNBUSDT/).
Object names follow `BNBUSDT-aggTrades-YYYY-MM-DD.zip`, with `.CHECKSUM` appended for the checksum object.
These results establish object availability only, not archive integrity, event completeness, freshness, or local receipt evidence.
Any later download must independently verify its bytes and the required observations around each fill.
Prices before a UTC day boundary can require the preceding daily archive; those additional files are not checked here.

### Planned collection and acceptance checks

This plan is not an installed collector and does not authorize new trades or a Pi restart.

1. Derive required conversion markets and UTC periods from a bounded, authenticated immutable fill export.
2. Check official archive coverage before any bounded download.
3. Preserve downloaded bytes, checksums, retrieval time, source origin, and timestamp units as retrospective evidence.
4. Never synthesize a historical receipt timestamp from a trade timestamp or download time.
5. Design passive collection for the required public BNB conversion streams without order permissions.
6. Preserve raw observations, exchange timestamps, local receipt timestamps, and clock-health evidence.
7. Record reconnect gaps and reject observations with unresolved temporal ordering.
8. Bind immutable manifests to an explicitly trusted collector identity and reviewed authentication mechanism.
9. Preserve timestamped private fills separately, with exact commissions and complete order-bound quantities.
10. Store archives only on the external disk, with explicit capacity, retention, and verified-backup requirements.
11. Test timestamp-unit conversion, clock uncertainty, gaps, altered manifests, restart recovery, and runtime/replay consistency.

Future capture cannot repair missing historical receipt evidence.
A collector signature proves the configured collector's attestation, not an exchange signature or proof of truthful timestamps.
The trust model must document that distinction before replay integration.
No collector, evidence import, or replay-gate change is implemented by this plan.

### Local bounded collector and remaining stages

### Public network smoke check

On 2026-09-14, a one-shot Pi process executes the unchanged local collector through standard input, without installation.
The shared bounded-body dependency matches the local SHA-256 before execution.
The process receives no account credentials and permits writes only on the selected external mount.
Limits are five public requests, 20 seconds of collection, and a 30-second process lifetime.

The run saves five responses and 114 aggregate trades in 17,180 archive bytes.
The interval between first and last response receipt is 4,958 milliseconds.
A separate bounded read verifies the manifest hash, byte count, event count, market binding, sequence continuity, and timestamp ordering.
The artifact remains on the external exFAT disk under `bnb-public-capture`; nothing is copied onto root storage.
The existing directory prevents an automatic repeat capture and remains preserved.

Observed trade age ranges from 194 to 69,314 milliseconds relative to the unverified local clock.
The initial recent-trades request includes older events; these figures do not establish causal freshness or exchange clock accuracy.
The status remains `DIAGNOSTIC_ONLY`, with no signature, unverified clock quality, and `replay_allowed=false`.

After capture, all four monitored services remain active with zero recorded automatic restarts.
HALT remains present and the deployed Git SHA remains unchanged.
The external disk has approximately 1.28 GB free and reports 98 percent utilization before capture.
Continuous collection requires a reviewed capacity and retention plan; this smoke check installs no recurring process.

Next work concerns trusted clock evidence and collector authentication, not additional trades or replay admission from this unsigned artifact.

### Local implementation details

The local [attestation boundary](../ladder_dragon/strategy/capture_attestation.py) signs exact manifest hashes and supplied clock claims with domain-separated Ed25519 signatures.
Verification requires an independently supplied public key and expected collector identity; it never enrolls a key from the artifact.
The caller also supplies maximum uncertainty, lifetime, and drift limits independently of the signed claims.
Receipt ordering uses the complete uncertainty interval, with integer drift expansion and exclusive expiry.
An interval that touches the fill timestamp cannot establish prior availability.
Existing LIVE clock admission remains unchanged; its safety flag is not a substitute for this uncertainty model.

The attestation primitive validates supplied clock claims; the integrated path below also verifies retained measurements and archive membership.
The source label `collector-clock-v1` identifies a claim schema, not an authenticated time provider.
A reviewed caller must establish clock measurements, capture-session identity, archive membership, and complete fill ownership before composition.
The old unsigned artifact cannot gain historical clock evidence from a later signature.
Both signed payloads and original manifests retain `replay_allowed=false`.
The implementation neither creates nor loads production keys and adds no persistent store.

Synthetic tests cover changed manifests, wrong keys, altered signatures, domain mismatch, clock jumps, expired evidence, and ambiguous fill ordering.
A converter integration test uses the conservative upper receipt bound; it does not prove runtime/replay admission consistency.
Production signed collection, key enrollment, authenticated private-fill export, and execution admission remain unfinished.
The local attestation stage passes 31 new regressions and 91 related tests.
On 2026-09-14, its full suite passes 2915 tests, with 2 skipped; compilation and all five safety audits pass.

The local candidate now includes [a standalone REST collector](../bin/record_bnb_public.py) and its [bounded implementation](../ladder_dragon/strategy/bnb_capture.py).
It polls only public BNBUSDT aggregate trades; it opens no WebSocket or private exchange connection.
The command remains unsigned by default; programmatic callers can select the integrated signer described below.
All manifests remain `DIAGNOSTIC_ONLY`, with `replay_allowed=false`, `clock_verified=false`, and no signature.
REST observations preserve response bytes as UTF-8 text, receipt nanoseconds, monotonic time, and unknown clock uncertainty.
They never invent a WebSocket event time or historical availability timestamp.

The command requires `--external-mount`; optional limits are `--requests-limit` and `--duration-sec`.
Defaults are 10 requests and 30 seconds; hard limits are 100 requests and 300 seconds.
Each request uses at most five seconds, with remaining budgets checked between reads; operating-system delays are not hard-cancellable.
The first request selects recent trades; later requests continue from the next aggregate identity.
Duplicate identities, sequence gaps, backward market time, future trades, and local clock divergence above 100 milliseconds stop collection.
Local clock consistency does not prove exchange clock synchronization.
Interrupted capture remains without a completed manifest; signature-stage failure can leave an unsigned diagnostic manifest.
Existing run directories block repeat execution without deleting prior observations.
See [retention and storage limits](DATA_RETENTION.md#existing-bounded-stores).

Thirty-one synthetic tests pass, including transport limits, gzip expansion, clock jumps, storage loss, restart preservation, and replay rejection.
On 2026-09-14, the full suite passes 2884 tests, with 2 skipped; compilation and all five safety audits pass.
Combined collector and deployment checks pass 117 tests after adding required production-file purpose comments.
No live capture, deployment, or service change occurs during this implementation.

Keep future collector extensions separate from the active SOL depth service until deployment receives explicit authorization.
Use only public market endpoints; no account credentials, order methods, or trading imports belong in its transport.
Keep authenticated private-fill export separate from this public collector.

The [existing depth recorder](../ladder_dragon/strategy/depth_archive.py) supplies useful format conventions, but is not sufficient without further checks.
Its manifest contains hashes and source labels, not a trusted signature or clock-health evidence.
Its current REST snapshot uses `response.json()` without a preceding streamed decoded-byte ceiling.
Its WebSocket path parses received JSON without an explicit application byte check in this module.
Do not copy those transport paths unchanged into the new collector.

The local stage needs bounded HTTP bodies and WebSocket frames before parsing, plus explicit event, byte, duration, and disk limits.
Capture receipt time before JSON parsing and preserve clock uncertainty alongside exchange time and monotonic ordering.
Do not invent exchange event fields or silently convert uncertain timestamps into valid observations.
Missing authentication or clock evidence must leave the archive diagnostic and ineligible for replay.
Production key enrollment, disk allocation, and service activation remain separate deployment decisions.

Completion checks include synthetic oversized input, clock jumps, reconnect gaps, interrupted writes, duplicate events, and invalid signatures.
Also verify no private requests, no trading-state writes, external-disk failure behavior, and rejection by current replay admission.
Repeat full verification after future extensions; current results do not qualify production key enrollment or WebSocket transport.

### Integrated signed capture path

### Deployment preparation: keys and storage

The 2026-09-14 read-only check confirms approximately 1.28 GB free on the external disk, with 98 percent utilization.
Its exFAT mount uses `fmask=0022,dmask=0022`; the existing capture directory reports mode `0755`.
The requested directory mode does not provide owner-only access on this mount.
Public market observations can remain there; private signing keys and plaintext private-fill exports must not rely on these permissions.
The root filesystem reports approximately 23.7 GB available.
No backup contents, key values, or environment files are inspected.

Proposed placement, not implemented:

- Keep a dedicated capture key at `/etc/ladder-dragon/capture-signing-v1.pem`, owned by root with mode `0600`.
- Keep its parent directory root-owned with mode `0700` on the native filesystem.
- Do not reuse the existing soak-report key or any Binance authentication key.
- Pin the public key and collector identity in a separately reviewed verifier trust store, outside the evidence directory.
- Confirm the public-key fingerprint during enrollment; never accept a replacement key supplied by an archive.
- Pass key material through a protected process credential mechanism, never through arguments, environment values, or logs.
- Store public archives and detached attestations only on the external disk.
- Encrypt private-fill exports before external-disk persistence; do not create plaintext staging copies there or on root storage.

The signing key is an operational credential, not an archive or backup.
Its placement on native storage does not move evidence archives onto the Pi system disk.
Key enrollment, replacement, revocation, and encrypted recovery require a reviewed operational procedure before activation.

The existing `bnb-public-capture` directory already contains the preserved unsigned smoke-check archive.
Current code rejects another run in that slot; neither deletion nor a mount-check bypass is an acceptable workaround.
Local implementation now provides the preserved slot and one new signed-test slot, within a combined 128 MiB logical-file ceiling.
Accounting and private-fill retention remain separate; no automatic cleanup is proposed.

After local storage and credential-loader tests pass, propose one signed smoke run with five total public requests and a 20-second collection limit.
This includes the clock request and does not require a new trade, service restart, continuous collector, or removal of HALT.
The read-only preparation observes active `mybot` and `pi-healthd` services and a present HALT file.
No key, directory, export, or new archive is created during this preparation.

### Signed smoke activation boundary

The 2026-09-14 readiness check confirms an available second slot and 858652672 free bytes on the mounted external filesystem.
The original slot remains present; no archive contents or credentials are read during this check.
All four monitored services remain active without restarts; HALT and BUY blocking remain active.
The deployed checkout remains version 2.20.340; the signed collector remains a local candidate, not an installed command.

Credential loading does not implement key enrollment, revocation, recovery, or an approved deployment procedure.
Choose the credential lifetime before creating a key or activating the signed collector.
The proposed smoke scope uses a dedicated single-run diagnostic key, not a permanent production trust key.
Its signature must never grant replay admission or authenticate private fills.
A permanent key instead requires separately reviewed encrypted recovery and rotation procedures.

The proposed single-run procedure requires these controls before execution:

- Generate the private key inside protected native temporary storage, without exporting its value.
- Register the public key and fingerprint outside the capture directory before any network collection.
- Bind registration to the collector identity, reviewed code hashes, clock policy, and one authorized run.
- Deliver the private key through protected process credentials, without changing existing service configuration.
- Preserve the public registration for later verification; do not infer trust from the resulting archive.
- Remove the temporary private credential after the run, including failure, only within separately approved cleanup scope.
- Treat key loss before signing as a failed run; never replace the key or repeat collection automatically.
- Retain a failed slot unchanged; another slot or cleanup requires a new decision.
- Keep public registration and capture evidence until an explicit retention review; do not schedule automatic deletion.

The proposed test permits five total public requests, including the clock sample, and a 20-second collection limit.
An isolated execution wrapper must enforce a 30-second outer deadline and must not install or restart trading services.
Independent clock uncertainty, lifetime, and drift limits still need review before activation; fixture values are not production defaults.
Verification must check the signature, exact manifest and archive hashes, complete counters, and clock derivation against the prior registration.
Post-run checks must confirm unchanged deployed SHA, service restart counters, HALT, BUY blocking, and preservation of the original slot.

This section records a proposed procedure, not completed enrollment or approval of a permanent key.
No credential, trust registration, transient service, or second capture is created by the readiness check.

### Authorized single-run diagnostic outcome

On 2026-09-14, the operator authorizes a single-use diagnostic key, prior public registration, one bounded capture, and temporary private-key removal.
The isolated process uses five total public requests, a 20-second collection budget, and a 30-second systemd deadline.
Its diagnostic clock policy permits 500 milliseconds of uncertainty, a 20-second lifetime, and 100 parts per million of drift.
These limits do not change trading configuration or authorize replay.

The public registration precedes capture and binds the public key, collector identity, source hashes, budgets, and clock policy.
The registration SHA-256 is `5387c8f56c0c71f456149a78945426b7f9ad9d93fb27ca68da0d26fee6785c7d`.
The raw public-key SHA-256 is `da0f8a47bbb74a9c3345b1bdc460ae71569f799d5f79c0cf4c4a3b043fad5bdf`.
The registration remains outside the capture slot, in `bnb-public-capture-registration-v1` on the external disk.

The process exits with code `2`, status `BLOCKED`, and error type `ValueError`.
The second slot contains only a zero-byte `observations.jsonl`; no completed manifest or detached signature exists.
Slot creation proves that credential loading returned successfully; it does not identify the subsequent failing validation.
The generic command error does not preserve a reason code or failed-stage clock measurement.
Do not infer clock drift, network latency, or exchange-response failure from this result alone.

The temporary private key and its runtime directory are removed after the isolated service stops.
The original archive and manifest hashes remain unchanged; the failed second slot and public registration remain preserved.
No retry, replacement key, deployment, trading-service restart, or replay admission occurs.
All four monitored services remain active with zero restart counters; HALT and BUY blocking remain active.

Before another authorized attempt, add secret-safe stage and reason diagnostics and test their failure paths locally.
Do not reuse the occupied slot or reconstruct missing observations from the public registration.

### Safe failure diagnostics

The local command now reports fixed `stage` and `reason` fields beside `BLOCKED`, `error_type`, and `replay_allowed=false`.
Stages distinguish credentials, storage, clock request, body validation, receipt validation, observation writes, and attestation publication.
Exact internal validation tokens retain their reason codes; arbitrary exception text never enters the report.
Transport, filesystem, JSON, encoding, and unknown validation failures use fixed fallback categories.
Malformed arguments also return safe JSON without repeating supplied argument values.
Each command invocation creates fresh diagnostic state; a failed run cannot reuse an earlier stage.

The diagnostics do not save failed clock responses or add files, retries, requests, cleanup, or new trust authority.
Existing manifests, signatures, retention rules, and execution gates remain unchanged.
The previous smoke failure remains unexplained; new instrumentation cannot recover its missing reason retroactively.
On 2026-09-14, 135 focused tests pass, including 34 new diagnostic regressions.
The full suite passes 3019 tests, with 2 skipped; compilation and all five safety audits pass.
No new Pi collection or deployment occurs during this diagnostic implementation.

### Authorized diagnostic retry outcome

On 2026-09-14, the operator authorizes preservation of the failed slot by relocation and one new attempt with unchanged limits.
The zero-byte failed observation moves to `bnb-public-capture-failed-v1` on the same external filesystem; nothing is deleted.
The first registration and original unsigned archive retain their previously verified hashes.
The second public registration precedes collection and binds the updated diagnostic source hashes and a new single-use public key.
Its SHA-256 is `8871c754ba19436c6e8b04f21013856ad7c01449c609ce28b0b0f30ca6e01b81`.
The public-key SHA-256 is `9257f1a1a48ec6a45012ca74a4428b779863a7c7dd0cb723fa0a4f181455f662`.

This attempt exits with code `2`, status `BLOCKED`, stage `clock_request`, and reason `TIMEOUT`.
The timeout occurs before the clock response body stage; no market observations, manifest, or signature are produced.
The result does not distinguish connection, TLS, or response-header waiting, and does not establish the previous attempt's cause.
No automatic retry, relaxed timeout, private exchange request, or replay admission follows.
The temporary private credential is removed after the isolated process stops.

Both public registrations remain preserved and match their pre-capture hashes.
The second slot again contains only a zero-byte observation file; the original archive remains unchanged.
The deployed SHA and all four service restart counters remain unchanged; HALT and BUY blocking remain active.
External free capacity remains approximately 18.28 GB.

### Read-only network diagnosis after the retry

On 2026-09-14, bounded public network probes run without credentials, capture writes, or persistent configuration changes.
An ordinary IPv4 curl request returns HTTP 200 in 1.06 seconds.
The isolated curl profile times out after five seconds, before DNS completion; TCP and TLS timings remain zero.
A diagnostic-only address override then returns HTTP 200 in 0.95 seconds with hostname certificate verification enabled.
No permanent address override or TLS bypass is installed.

DNS-only checks do not identify a consistently failing isolation option.
The complete isolation profile resolves successfully in a later check.
The same Python requests configuration later records these outcomes:

- Ordinary process: DNS takes 5.103 seconds; HTTP 200 arrives after 6.073 seconds.
- Isolated process: DNS takes 0.116 seconds; HTTP 200 arrives after 1.150 seconds.

This confirms intermittent resolver delay, not a deterministic isolation failure.
One configured resolver answers bounded A and AAAA probes in 0.183 and 0.110 seconds during the later check.
The underlying cause of intermittent DNS latency remains unknown.
The Python socket timeout does not impose a five-second total budget on DNS plus connection and response handling.
The collector's clock-order checks remain necessary; a slow measurement must not gain qualification through a larger timeout.

The diagnosis uses eight public HTTP probes, five bounded resolver-profile checks, and two direct DNS queries.
No signing key, new archive, private exchange request, trading-service restart, or configuration change occurs.
Do not disable isolation or replace configured DNS based only on these observations.
The next local stage adds separate resolver measurements while retaining existing capture and clock-admission checks.

### Local capture network measurements

The local collector now records a bounded diagnostic entry for each public clock or market request.
Each entry has DNS time, request-to-headers time, a non-DNS remainder, DNS call count, stage, phase, and outcome.
The remainder includes TCP, TLS, server wait, and client overhead. It is not a pure transport measurement.
The fields `dns_ns`, `request_headers_ns`, and `non_dns_headers_ns` use integer nanoseconds and exclude response-body reads.
Zero DNS calls mean no resolver call occurred during that request; this can reflect connection reuse.

The collector uses a private HTTP pool. It does not change global resolver functions, shared HTTP sessions, TLS validation, request limits, or clock admission.
The command emits the entries only as diagnostic output. It does not add them to an archive, manifest, attestation, signature, replay input, or persistent store.
These disposable entries remain in memory for one invocation, with a maximum of 100 entries.
They require no archive, backup, or scheduled retention job.

The resolver now runs in a disposable isolated Python process with closed inherited descriptors.
Its explicit environment contains only `RES_OPTIONS=use-vc`, which selects TCP with the Pi's libc resolver; it inherits no parent environment values.
It resolves only the fixed public capture host and returns at most 32 validated numeric addresses.
The parent kills and reaps a resolver that exceeds the remaining connection budget, then reports a DNS-phase timeout.
No blocking resolver fallback runs after failure.
TCP attempts and TLS receive the remaining connection time; the HTTP read timeout also subtracts elapsed connection time.
The existing body deadlines, capture duration checks, and strict clock admission remain active.
The `dns_ns` field now includes child startup, resolver execution, and cleanup overhead.
The child creates no files and requires no backup or retention job.
Process creation, kernel scheduling, and process cleanup are not real-time guarantees; retain the outer service lifetime limit as defense in depth.

On 2026-09-15, 109 focused tests pass, including ten new network diagnostic regressions.
The full suite passes 3029 tests, with 2 skipped; compilation and all five safety audits pass.
This local stage performs no Pi collection or deployment and establishes no measured speed improvement.

The subsequent resolver deadline change passes 124 focused tests on 2026-09-15, including fifteen new regressions.
A real child configured to sleep for 60 seconds is killed and reaped under a 150-millisecond resolver budget.
The full suite passes 3044 tests, with 2 skipped; compilation and all five safety audits pass.
The cause of intermittent DNS latency remains unresolved. The local verification above excludes Pi performance measurements.

### Pi resolver deadline probe

On 2026-09-15, reviewed source bytes run from standard input in one bounded Pi process without installation.
The process uses the deployed interpreter with requests 2.33.0 and urllib3 2.7.0.
The source hashes cover the bounded body reader, resolver, diagnostics, and capture transport.
An artificial 60-second resolver stall returns `TIMEOUT` after 151.030 milliseconds under a 150-millisecond budget.

Three fresh sessions then request public `/time`, with five-second budgets and bounded response reads.
Each response returns HTTP 200 and a valid server-time object.

| Attempt | DNS phase, including child overhead | Non-DNS request-to-headers time | Complete probe request |
|---|---|---|---|
| 1 | 207.571 ms | 1032.888 ms | 1241.617 ms |
| 2 | 132.670 ms | 997.688 ms | 1132.255 ms |
| 3 | 138.871 ms | 1020.121 ms | 1160.902 ms |

These samples demonstrate deadline handling and successful public transport; they do not establish stable resolver latency or signed clock admission.
The probe creates no signing key or capture artifact and sends no private exchange requests.
All four monitored services remain active with zero recorded automatic restarts before and after the probe.
The deployed SHA remains unchanged; HALT and the BUY block remain active, with no reconciliation differences.
The external disk remains mounted with 17,761,435,648 bytes available.

### Pi clock admission probe

On 2026-09-15, four public `/time` requests test the unchanged `derive_clock` function through reviewed in-memory sources.
The independent policy remains 500 milliseconds maximum uncertainty, 20 seconds maximum lifetime, and 100 parts per million maximum drift.
Requests one and four use fresh sessions; requests two and three reuse the first session after its bounded body read.

| Attempt | Connection | Complete clock request | Uncertainty | Clock result |
|---|---|---|---|---|
| 1 | Fresh | 1248.373 ms | 624.690 ms | `ATTESTATION_CLOCK_LIMIT` |
| 2 | Reused | 241.523 ms | 121.262 ms | Accepted |
| 3 | Reused | 244.636 ms | 122.818 ms | Accepted |
| 4 | Fresh | 1119.016 ms | 560.008 ms | `ATTESTATION_CLOCK_LIMIT` |

All four responses return HTTP 200. The unchanged clock function rejects both fresh-connection measurements and accepts both reused-connection measurements.
DNS takes 240.000 and 145.865 milliseconds on fresh connections; reused connections make no DNS calls.
Fresh non-DNS request-to-headers time remains 971.700–1007.836 milliseconds; these metrics do not separately identify TCP, TLS, and server wait.
The wall/monotonic interval difference remains below three microseconds in every measurement.
Rejected uncertainty values are diagnostic calculations from the measured intervals; only successful `derive_clock` results establish clock admission.

The observations support a bounded connection warm-up before the qualifying clock request as the next implementation candidate.
Any warm-up must consume the existing total request and duration budgets, discard its clock sample, and preserve strict admission for the subsequent measurement.
Do not introduce unlimited retries or select the best sample from an unbounded sequence.
No warm-up behavior is installed by this probe, and accepted clock samples do not grant replay or trading authority.

The probe creates no key, signature, or archive. All four monitored services remain active with zero recorded automatic restarts.
The deployed SHA, HALT, BUY block, empty reconciliation result, and available external-disk space remain unchanged.

### Integrated signed capture implementation

The optional [CaptureSigner](../ladder_dragon/strategy/capture_clock.py) connects to the existing collector through its `attestor` argument.
It receives an in-memory Ed25519 private key, collector identity, and independently reviewed clock policy.
It never discovers or generates a production key; explicit command-line signing uses the protected credential loader described below.
Before market reads, it performs one bounded public `/time` warm-up and one qualifying `/time` measurement on the same session.
Both requests consume the existing request and duration budgets; signed capture requires at least three total requests, including one market read.
The warm-up response is read within a 1024-byte ceiling, closed, and discarded; its clock sample cannot qualify or enter an attestation.
Clock measurement begins after warm-up completion. A failed warm-up or qualifying measurement blocks collection without another attempt.
Reconnection during measurement remains subject to the same strict clock checks.
The capture deadline starts before session creation and does not restart after warm-up.
On 2026-09-15, 134 focused tests and 3054 full-suite tests pass, with 2 skipped; compilation and five safety audits pass.
Nine new warm-up regressions and an additional minimum-request case cover discarded samples, budgets, failure cleanup, and refusal to retry.
The response has a 1024-byte ceiling and a five-second maximum request interval.
It retains exact response text, endpoint identity, and wall/monotonic request boundaries in `clock.json`.

The clock calculation brackets exchange time across the complete request interval and includes millisecond timestamp quantization.
Wall/monotonic interval disagreement above one millisecond rejects the sample.
Independent uncertainty, lifetime, and drift limits reject unsafe measurements and later observations.
This is a relative exchange-time estimate, not proof that the operating system has synchronized through NTP.
It assumes the authenticated endpoint reports a server timestamp generated inside that request interval.
TLS authenticates the endpoint connection; the collector signature attests retained bytes, not an exchange signature.

After capture, the signer writes `attestation.json` and `attestation.sig` beside the immutable diagnostic manifest.
The signed clock claims bind the measurement hash; the signed manifest hash binds the complete archive hash and counts.
Neither file replaces earlier evidence or changes diagnostic admission flags.

### Integrated warm-up probe on Pi

On 2026-09-15, the reviewed `CaptureSigner.warmup` and `CaptureSigner.start` methods run from memory with keyless diagnostic state.
The harness supplies the same clock policy and session but does not construct a signing-capable instance or invoke artifact publication.
The attempt stops with `stage=clock_warmup_request`, `reason=TIMEOUT`, and network phase `dns`.
DNS takes 5004.145 milliseconds; the complete attempt takes 5005.530 milliseconds.
The qualifying clock request never starts, and no retry occurs.
This outcome verifies the bounded failure path; successful integrated warm-up remains unconfirmed on Pi.
Earlier reused-session measurements do not replace this failed attempt or establish signed collection readiness.
The probe creates no key or archive and does not install the candidate.
All four monitored services remain active without recorded automatic restarts; deployed SHA, HALT, and the BUY block remain unchanged.
Reconciliation remains empty, and the external disk retains 17,761,435,648 available bytes.

### Resolver transport diagnosis

On 2026-09-15, bounded read-only probes compare UDP, TCP, A, AAAA, and system resolution against the configured DNS server.
The Pi uses one non-loopback IPv4 resolver; NetworkManager is active, and systemd-resolved is inactive.
No resolver options are present, and no IPv6 default route exists.
AAAA queries return `NOERROR` with zero answers; this is not a timeout or evidence of an IPv6 network fault.
The system `ahostsv6` result does not prove native IPv6 connectivity because it can contain mapped IPv4 addresses.

The first two rounds return UDP query times of 104–504 milliseconds and TCP query times of 4–12 milliseconds.
Control rounds alternate TCP-first and UDP-first order with EDNS disabled.
TCP returns in 4–84 milliseconds; successful UDP queries take 124–144 milliseconds.
One direct UDP query then times out after 2021.411 milliseconds, while the adjacent TCP query succeeds.
This reproduces a failure outside the collector and its process isolation.

Three paired system-resolver checks compare an empty environment with process-local `RES_OPTIONS=use-vc`.
The TCP diagnostic processes finish in 34.457–43.976 milliseconds; default-mode processes finish in 139.290–159.388 milliseconds.
Every successful resolution returns five IPv4 addresses and no native IPv6 addresses.
These samples support a UDP-path or UDP-server-handling problem; they do not locate the exact packet loss or prove permanent TCP reliability.

Receive errors, receive drops, and transmit errors remain zero on inspected interfaces before and after the initial matrix.
The preceding hour of available NetworkManager logs contains no matched timeout, failure, DNS, or error text.
These counters do not exclude upstream packet loss or server-side faults.
The investigation performs fourteen direct DNS probe commands and twelve system-resolution probe commands.
No persistent DNS, network, isolation, or service configuration changes occur.

The local correction selects TCP only inside the disposable public capture resolver process through the fixed `RES_OPTIONS=use-vc` option.
It preserves the deadline, fixed target, excluded parent environment, numeric-result validation, and strict clock policy.
An error returns through the existing failure path without a second resolver process or application-level UDP fallback.
System DNS configuration and the parent process environment remain unchanged.
Global resolver replacement and isolation changes are not supported by this evidence.

### TCP resolver and warm-up verification on Pi

On 2026-09-15, the keyless in-memory probe runs the corrected resolver and unchanged warm-up and clock methods once.
It performs two public time requests without retries, artifact publication, service restarts, or installation.
Warm-up DNS takes 150.117 milliseconds, including child-process overhead; warm-up request-to-headers time is 1169.028 milliseconds.
The qualifying request reuses the connection, performs no DNS resolution, and receives headers after 242.467 milliseconds.
The unchanged clock policy accepts 122.054 milliseconds uncertainty against its 500-millisecond limit.
The complete probe takes 1415.848 milliseconds.

This confirms one successful integrated warm-up and clock check, not sustained latency improvement or completed signed collection.
The underlying UDP fault remains unresolved. TCP selection avoids that observed path only within the collector's resolver process.
The probe creates no key, signature, or archive; replay remains prohibited.
All four monitored services remain active with zero recorded automatic restarts; deployed SHA, HALT, BUY block, and empty reconciliation remain unchanged.
The external disk remains mounted with 17,761,435,648 available bytes.

### Authorized signed diagnostic v3

On 2026-09-15, the operator authorizes one new signed diagnostic and preservation of the previous failed slot by relocation.
An exclusive rename moves the second failed slot to `bnb-public-capture-failed-v2`; its single empty observation file remains unchanged.
The original unsigned archive, first failed slot, and both earlier public registrations retain their verified hashes.

The run creates one Ed25519 credential in a protected native runtime directory, never in the repository or external archive.
Public registration precedes every collection request and binds the key fingerprint, source hashes, wrapper hash, collector identity, budgets, and clock policy.
The external registration directory is `bnb-public-capture-registration-v3`; its single JSON file remains below 16 KiB.
The collector identity is `pi-bnb-diagnostic-v3`.

| Evidence | SHA-256 |
|---|---|
| Public registration | `0787cee3a906ec4b11666c338dc98dec007232c9e14979b8c4f60086097428b2` |
| Public-key fingerprint | `7145b2188281d084e814871d28feadd186a6011a411179cb9eab7c79b0df090d` |
| Manifest | `581bc1153e628ed1891f809a3ebe9139d04be87036b8965c1bdfeaf261fa57bb` |
| Observation archive | `ee1755cddecb3d4062f6ab7d52211cddaf992b245fa9a6d984da7763b6dedf6d` |

The isolated child permits five total public requests, 20 seconds of collection, and a 30-second outer process deadline.
It performs one warm-up, one qualifying clock request, and three market requests without retries.
The archive contains 104 aggregate-trade events across three observation records, totaling 15,247 bytes.
The collector completes and writes the manifest, clock measurement, attestation, and detached signature.

Read-only verification confirms the signature against the prior registered key, clock rederivation, archive hash, byte count, and event count.
All receipt intervals satisfy the registered policy, and every market timestamp precedes its receipt interval's conservative lower bound.
Clock uncertainty is 128.313 milliseconds under the unchanged 500-millisecond ceiling; lifetime and drift limits remain 20 seconds and 100 ppm.
The verified public observations do not establish private-fill provenance or entry-to-exit ownership; replay remains prohibited.

After the child exits, the wrapper removes only its temporary private credential and empty runtime directory.
The private credential is not recoverable through this procedure; the public registration and signed evidence remain on the external disk.
All four monitored services remain active with zero recorded automatic restarts.
The deployed SHA, HALT, BUY block, and empty reconciliation result remain unchanged; no candidate installation occurs.
The external disk remains mounted with 17,760,387,072 available bytes after the run.
Before execution, 111 focused credential, storage, attestation, clock, and command tests pass on unchanged source.
The preceding complete verification remains 3057 passed and 2 skipped; this operational run does not constitute a release profile.

### Private-fill provenance readiness after diagnostic v3

On 2026-09-15, read-only SQLite checks find 87 BNB commission fills, spanning 2026-07-18 through 2026-09-03 UTC.
The last fill timestamp is `2026-09-03T15:35:10.129Z`.
The signed public archive retains its previously verified manifest and archive hashes.
Its observation receipt interval spans `2026-09-15T17:16:37.188Z` through `2026-09-15T17:16:39.700Z`.
No selected fill occurs at or after the first observation receipt.
These observations cannot satisfy the existing before-fill availability contract for any of the 87 historical fills.
Authentication of those fills cannot repair this separate temporal incompatibility.

The earlier authenticated REST comparison establishes matching fields and complete terminal orders at its verification time.
The aggregate-only verifier discards responses; its report does not preserve independently verifiable timestamped source bytes.
Durable BUY settlement projects quantity and commission fields without timestamps; it does not replace a timestamped source collection.
The inspected user-stream path persists health state and forwards order signals, not an immutable signed raw-fill archive.
These code findings do not assert that every possible external source has been searched.

The next local implementation can prepare a separate private-source export boundary without contacting an account:

1. Use the existing bounded read-only verifier to establish terminal order identity and complete fills.
2. Retain exact bounded response bodies and request identity without credentials, headers, request authentication values, or signed URLs.
3. Bind response hashes, code identity, observation times, and completeness checks to an independently registered diagnostic collector.
4. Describe the result as collector-attested authenticated retrieval, never an exchange-signed statement or proof of historical local receipt.
5. Encrypt private records before persistence on the external disk; prohibit plaintext staging and accounting writes.
6. Define a fixed capacity, indefinite evidence preservation, and explicit key and backup responsibilities before activation.
7. Test changed timestamps, mixed accounts, foreign orders, missing fills, changed bytes, and interrupted encryption.
8. Preserve `private_fills_authenticated=false` until the composed reader verifies an explicitly approved source-attestation contract.
9. Preserve `replay_allowed=false` independently of successful private-source verification.

Private export activation requires separate approval of the exact source scope, encryption recipient, trust registration, and retention procedure.
Do not generate another paid batch or collect more current prices to resolve the historical timestamp mismatch.
A retrospective historical-data model requires its own reviewed temporal assumptions; it must not relabel later receipt as earlier availability.
This readiness check performs no exchange requests, private export, credential access, database writes, or replay admission.
The existing signed-capture, fill-binding, and order-verifier group passes 102 tests; 17 documentation checks and the Technical English check pass.

### Local encrypted private-source claims

The [offline export boundary](../ladder_dragon/strategy/private_fill_export.py) validates, signs, encrypts, and stores caller-supplied bounded response bytes.
It does not perform authenticated retrieval, load credentials, query SQLite, import accounting records, or connect to replay.
The existing verifier and exporter share [terminal order completeness](../ladder_dragon/execution/order_fill_evidence.py), including exact totals, side, identities, duplicates, and commission validation.
The verifier still rejects an invalid terminal order before requesting its fills.

Each package permits up to eight distinct orders, with two response bodies of at most 64 KiB per order.
Raw bytes remain exact inside the encrypted package, together with their SHA-256 hashes and caller-supplied retrieval intervals.
Intervals must be sequential, positive, and at most 30 seconds long; fill timestamps cannot exceed the corresponding completion timestamp.
These checks validate consistency, not clock accuracy or historical local receipt.

Independent bindings identify the source scope, collector, reviewed code, registration, signing public key, and encryption key by bounded identifiers or hashes.
Different scope labels are rejected; matching labels alone do not establish that responses came from the same real account.
The caller must provide both keys in memory and retain an independently approved trust record.
The module creates no key, key file, enrollment, network request, or production activation.

An Ed25519 signature covers the complete claim body with a private-source-specific signature domain.
The signed envelope is encrypted in memory with [Fernet authenticated encryption](https://cryptography.io/en/latest/fernet/) before any output file is opened.
Fernet uses a symmetric secret key; this local interface does not implement an asymmetric recipient workflow or approved production key recovery.
Fernet exposes token creation time and approximate payload size; response contents and inner bindings remain encrypted.
Plaintext and keys exist in process memory; this module does not guarantee memory erasure or protect against process inspection, dumps, or swap.

The reader checks decryption, independent bindings, signature, raw response hashes, and complete-order validation again before returning claims.
Even a correctly signed malformed claim is rejected.
Both `private_fills_authenticated` and `replay_allowed` must remain false in the signed body and returned result.
Successful storage reports `ENCRYPTED_CLAIMS_ONLY`, never authenticated exchange provenance.

One exclusive `private-fill-export` directory holds only `bundle.fernet` on the selected external mount.
Existing directories or symlinks block another export; interrupted ciphertext remains preserved and cannot be resumed or overwritten.
No plaintext staging file, cleanup routine, scheduler, or new command is introduced.
See [retention](DATA_RETENTION.md#offline-private-source-export) for bounds and activation prerequisites.
This offline module does not implement production retrieval, account identity verification, key custody, encrypted recovery, or command integration.
On 2026-09-15, 50 new regressions and 119 related checks pass; the full suite passes 3107 tests, with 2 skipped.
Compilation, five safety audits, and 25 documentation and workflow checks pass.
No real private records, production keys, Pi services, or replay state are accessed by these synthetic checks.

### Local credential-pinned private retrieval

The [private response collector](../ladder_dragon/strategy/private_fill_capture.py) connects bounded GET retrieval to the existing encrypted export boundary.
It accepts one frozen credential pair and an independently supplied credential-scope fingerprint before any network request.
The fingerprint derives from the API key with a Mainnet-specific domain; it never includes a raw credential in exported records.
Changing the selected API key fails the preflight comparison; credentials are not refreshed through a mutable callback during collection.

This proves use of one pinned credential within the reviewed collector, not ownership of an independently confirmed account UID.
Real activation must separately establish the selected dashboard key's provenance, account association, and read-only permissions.
Transport restrictions alone do not prove the exchange-side permissions assigned to that key.

The collector permits one clock request and two reads per selected order, with at most eight distinct orders and seventeen total requests.
The shared dashboard client supplies request authentication; the private session allows only fixed Mainnet GET paths for time, order, and trade history.
Redirects, environment proxies, and transport retries are disabled; TLS certificate verification remains enabled.
Clock responses have a 1024-byte ceiling; order and fill responses retain the 64 KiB decoded and encoded ceilings.
The collector rejects non-200 responses and provider error objects before inherited timestamp retry logic can run.
An invalid terminal order stops collection before the corresponding fill request.

The clock check covers the complete response read and validates round-trip time, offset, and wall/monotonic interval consistency.
Each order packet records its retrieval interval and exact order-specific response bytes; completeness uses the shared order validator.
The total request budget is 30 seconds, and each request receives at most five seconds of remaining time.
These cooperative limits do not terminate blocked operating-system DNS; a separately reviewed outer process deadline remains mandatory before real activation.

The combined entry point validates export-key fingerprints and rejects an occupied output slot before private retrieval.
It writes only after every selected order passes validation, through the existing encrypt-before-write function.
Network errors produce a fixed failure code without provider text, signed URLs, raw response bodies, or credentials.
Partial in-memory retrieval creates no archive; an interrupted ciphertext write remains governed by the existing preservation policy.

Results remain `ENCRYPTED_CLAIMS_ONLY`, with `private_fills_authenticated=false` and `replay_allowed=false`.
No command, credential discovery, trust enrollment, production collector, or service installation is added.
Tests exercise the actual signing adapter through synthetic HTTP responses; they do not contact a real account.
Independent trust registration, account association, key recovery, and an authorized bounded host wrapper remain activation prerequisites.
On 2026-09-15, 49 new collector regressions and 126 focused tests pass; the full suite passes 3156 tests, with 2 skipped.
Compilation, five safety audits, and 25 documentation and workflow checks pass.
Pi, production credentials, private account data, and replay state remain untouched during this local implementation.

### One-order private diagnostic and recovery boundary

On 2026-09-15, the authorized diagnostic uses the dashboard credential and one existing order, with at most three GET requests.
A synthetic age round trip on Pi succeeds entirely in memory, without private-key files.
This validates the recovery mechanism, not custody or decryption with the operator's actual private identity.

Before retrieval, the runner preserves public registration and an age-encrypted export key on the external disk.
The exclusive directory is `/mnt/usb1/private-fill-registration-v1`.
The registration SHA-256 is `6fc4dfe04f0884ef8a3bcbc1d3fe776a877ade7dcd79816c60d997a01666704b`.
The 244-byte recovery ciphertext SHA-256 is `0fc01860448f0eef8264734bac10c3a22c28ac5c2d7122b3d25a45ad7f08ab1d`.
Neither file grants account authentication or replay admission.

The initial service launch fails before Python because a combined environment-file property names a nonexistent path.
Separate properties pass a variable-presence check without printing credentials or making exchange requests.
The subsequent diagnostic stops at `clock`, before order and fill requests.
It reports `PRIVATE_CAPTURE_FAILED_CLOSED`; no private-fill export is created.
The retained stage does not distinguish DNS, TLS, HTTP failure, or invalid clock measurements.
The precise cause remains unknown; no further collection attempt occurs.

The runner creates no plaintext private-key file; signing and export keys remain in the terminated process's memory.
Public registration and encrypted recovery remain preserved even though capture fails.
All four monitored services remain active without automatic restarts; HALT and the BUY block remain active.
The deployed checkout is unchanged, and replay remains prohibited.

The local collector now retains fixed reason categories and bounded numeric HTTP status metadata.
Regressions cover HTTP rejection, unsafe clocks, TLS failure, and timeout without provider-text disclosure.
The local `failure_report` function revalidates metadata and returns only fixed fields, numeric HTTP status, and false authentication and replay flags.
The prepared temporary runner uses this function; synthetic collection failures exercise JSON output without export or request retries.
Tests reject altered metadata, invalid HTTP status values, and exception text disclosure.
This reporter change does not launch another Pi diagnostic or replace the existing registration.
New instrumentation cannot reconstruct the previous missing cause.

### Public clock probes and prepared private retry

Two separately authorized one-request probes pass clock admission on Pi without credentials or private requests.
The isolated Python probe takes 711 milliseconds, including 181 milliseconds of DNS; its estimated offset is +189 milliseconds.
The systemd probe takes 808 milliseconds, including 273 milliseconds of DNS; its estimated offset is +228 milliseconds.
The latter preserves the previous isolation properties, omits credential environment files, and applies a 15-second outer request-process limit.
The transient unit disappears after completion; services remain active, HALT remains enabled, and reconciliation has no differences.
These successful samples do not establish the previous failure's cause or eliminate intermittent network behavior.

The preparation stage produces a temporary second private runner without executing it on Pi.
Its default mode checks preparation without starting subprocesses or making network requests.
It pins the reviewed runner template and preserves the previous registration and encrypted recovery through exact hashes.
It also compares the credential scope, encryption recipient, and selected order against the preserved registration before new enrollment.
Changed or missing prior evidence blocks collection; an occupied new registration or encrypted-export slot also blocks collection.

The proposed scope permits one existing order, at most three GET requests, and a 45-second process limit.
It creates only the exclusive external `private-fill-registration-v2` registration and the existing exclusive `private-fill-export` slot after successful retrieval.
The new registration and recovery precede private retrieval; plaintext signing and export keys remain in memory.
Safe failure reports retain their stage, reason, and bounded HTTP status; no automatic retry or cleanup occurs.
Execution requires separate current operator authorization; preparation does not grant it.
The previous registration remains intact, and replay remains prohibited even if collection succeeds.

### Authorized private diagnostic v2 outcome

On 2026-09-16, the operator authorizes one read-only collection with new registration and encrypted external storage.
The reviewed runner completes one order and one fill, including one BNB-paid commission, within the three-GET request contract.
It verifies the signature, decrypts the package in memory, and compares order identity and exact totals with the journal.
No accounting import, order mutation, replay admission, or service restart occurs.

The result is `ENCRYPTED_CLAIMS_ONLY`, with `private_fills_authenticated=false` and `replay_allowed=false`.
Account UID verification remains absent; successful retrieval and journal agreement do not establish that independent identity check.
The previous clock failure remains unexplained; this successful attempt does not prove that intermittent delays are fixed.

The external registration is `private-fill-registration-v2/registration.json`, with SHA-256 `d5bda63289e5a933e9b982fc873a6e84cb089fa035f1ec0a796789666e244fd1`.
Its 244-byte `export-key.age` has SHA-256 `4ae0fbba3e6a508648de8518a1fa10cb7920ddc9a5e5a85105f75c041ca3a72f`.
The 3832-byte `private-fill-export/bundle.fernet` has SHA-256 `e14badd479cb69258608993f3cfc1f92fe384b7f095e49a321f27de7174290b0`.
An independent post-process read confirms all three hashes and both previous-registration file hashes.
The transient unit is absent after completion; all four monitored services remain active without automatic restarts.
HALT and the BUY block remain enabled, reconciliation has no differences, and the deployed checkout remains unchanged.

No plaintext signing-key or export-key file is created; the isolated process terminates after verification.
The encrypted recovery file remains, but recovery with the operator's separately held age identity is not tested here.
Preserve both registrations and the encrypted package; repeat collection cannot reuse the occupied slots.
Further provenance qualification and replay integration remain separate work, without permission for another private collection.

### Recovery verification with the installed age identity

On 2026-09-16, an authorized isolated process verifies recovery using the backup identity created by the Pi installer.
The process passes its protected identity descriptor directly to age; it never prints or copies the private identity.
It verifies independently pinned registration, recovery-ciphertext, and package hashes before decryption.
The recovered export-key hash matches registration, and the package passes decryption, signature, binding, and complete-order validation again.
The result is `RECOVERY_VERIFIED`; no plaintext key or private-fill file is created.
The transient process has no network access, uses read-only filesystem protection, and terminates after the check.

This proves recovery with the currently installed identity, not recovery after loss of the Pi or its storage.
An independently stored protected identity copy remains unconfirmed; its destination requires an operator decision.
No identity copy, credential rotation, accounting import, or replay admission occurs during verification.
Account UID verification remains absent, and both private authentication and replay flags remain false.

### Apple Passwords copy verification remains pending

The operator reports a saved Apple Passwords copy; the helper receives 75 bytes but rejects input before SSH.
The local regex incorrectly requires 75 identity characters instead of 74, excluding the optional newline.
The corrected regex accepts an in-memory identity generated by age; the old regex rejects that same identity.
Five local length and newline cases pass without real clipboard or network access.
This corrects helper validation only; verification of the saved Apple Passwords copy still requires an actual recovery attempt.
No evidence establishes that the saved copy is invalid, and the original Pi identity remains preserved.

### Composed archive reader

The [composed reader](../ladder_dragon/strategy/prediction/signed_capture.py) verifies the external trust key and rederives clock claims from retained measurements.
It reads the complete archive once, with byte and line limits, before returning a selected price.
Malformed tails, changed bytes, sequence gaps, invalid receipt ordering, and incomplete counts reject the result.

REST and WebSocket commission adapters share `settled_bnb_fill` for complete quantities, ownership, and fee-unit validation against durable settlement.
The composed reader applies the conservative upper receipt bound and the existing causal commission converter.
A synthetic test compares both adapters and verifies unchanged journal state.
This proves shared valuation behavior for the tested evidence, not complete live/replay execution equivalence.
Private fill timestamps still require independently authenticated source bytes; durable inventory projection alone does not preserve their origin.
The result explicitly retains `private_fills_authenticated=false` and `replay_allowed=false`.

The local integration passes 143 related tests, including collector-to-reader composition and signed malformed archives.
On 2026-09-14, the full suite passes 2943 tests, with 2 skipped; compilation and all five safety audits pass.
The integrated path adds 28 regressions; combined integration and deployment checks pass 114 tests.
No production capture, key enrollment, service change, private exchange request, or replay admission occurs in this stage.

### Protected credential and slot integration

The [credential loader](../ladder_dragon/strategy/capture_credentials.py) reads at most 4096 bytes from one protected regular file.
It opens every absolute path component without symlink traversal and retains directory descriptors during resolution.
The immediate parent must be owner-only and owned by root or the effective user.
The file must have one hardlink, the same allowed ownership, and mode `0400` or `0600`.
The loader rejects changed file metadata, encrypted PEM inputs, non-Ed25519 keys, and mismatched public-key fingerprints.
It never prompts for a password, copies key files, prints parser details, or exports private key bytes.
The required fingerprint is SHA-256 of the raw 32-byte public key, supplied independently of the archive.
Permission checks do not replace the operator requirement for native protected storage or a protected process credential mount.

The command accepts `--slot original` or `--slot signed-test`; the original slot remains the unsigned default.
Command-line signed collection requires all of these options:

- `--slot signed-test`;
- `--signing-credential`, containing a file path, never key material;
- `--trusted-key-sha256`, containing the independently enrolled public-key fingerprint;
- `--collector-id`;
- `--clock-max-uncertainty-ms`, `--clock-ttl-ms`, and `--clock-drift-ppm`.

Incomplete signing options block execution before credential loading or network collection.
No production clock limits are inferred from test values.
The [slot manager](../ladder_dragon/strategy/capture_storage.py) preserves occupied slots and checks only known capture-file metadata.
It never reads backups or deletes existing data; insufficient disk space blocks collection.
The test suite covers a preserved first archive, rejected third slots, unsafe paths, oversized slots, changed keys, and secret-safe command errors.
No production key, trust-store entry, systemd credential mapping, or Pi directory is created by this local implementation.
On 2026-09-14, 101 focused tests and 122 command, surface, and deployment checks pass.
The full suite passes 2985 tests, with 2 skipped; compilation and all five safety audits pass.

## Original diagnostic boundary

This review follows the [mechanism memo](BASELINE_ENTRY_MECHANISM_REVIEW.md).
The original diagnostic changes no model, production state, or immutable evidence.
The fixtures use synthetic prices and quantities, not account data.

## Method and scope

The diagnostic instantiates `HistoricalExecution` and processes synthetic `MarketEvent` objects through the unchanged matcher.
It reuses the `policy`, `context`, and `event` fixture builders from the existing historical-entry test module.
All financial arithmetic uses Decimal.
No exchange request, private database, or historical archive participates.

The fixture starts at 3000 milliseconds with bid 100 and ask 101.
Its gap is 100 basis points, notional is 100, and modeled submission latency is 100 milliseconds.
The resulting entry price is 99.49 and requested quantity is 1.005.
The fixture commission rate is 0.001 and emergency impact is 10 basis points.
These numbers describe a diagnostic, not a proposed trading configuration.

## Results

### Partial entry below its stop trigger

The arrival event occurs at 3200 milliseconds.
A SELL-aggressor trade fills 0.1 at the entry price at 3300 milliseconds.
At 3400 milliseconds, the book falls to bid 97 and ask 98, with a BUY-aggressor trade at 97.
That trade does not add another BUY fill.

The model remains in `ENTRY` with quantity 0.1.
Neither target nor stop exists, and `stop_ms` remains unset despite the below-trigger trade.
The entry remainder is still active.
This proves a modeled protection gap while a partial entry remains unfinished.
It does not prove that the production worker follows this behavior.

Qualification requires an explicit partial-entry protection contract, including pending cancellation fills and residual exchange minimums.
The model cannot silently classify this interval as protected.

### Stop activation after the trigger

A separate episode fills its entire entry at 3300 milliseconds.
At 3500 milliseconds, a trade reaches its trigger while the book has bid 98.4 and ask 98.5.
The target is removed immediately; the stop has an effective arrival timestamp of 3601 milliseconds.
No exit occurs at 3600 milliseconds.
At 3601 milliseconds, displayed liquidity above the stop limit permits the full exit.

This reproduces normal submission latency plus the one-millisecond tie exclusion after the trigger.
Binance describes STOP_LOSS_LIMIT as a conditional limit order activated when the stop price is reached.
See the [official glossary](https://developers.binance.com/en/docs/products/spot/faqs/spot_glossary).
That description does not establish zero activation latency or exact event ordering.
The model's extra delay is therefore an unqualified assumption, not a measured venue delay or proven production bug.

### Emergency exit beyond displayed capacity

A fully filled episode receives PANIC at 3500 milliseconds.
The event contains only 0.001 at bid 90, with ask 91.
The model reports all 1.005 units sold at 89.910 and returns `PANIC_FLATTEN` with `censored=False`.

This exceeds supplied bid capacity by a factor of 1005.
The diagnostic proves that emergency flatten does not enforce available depth.
It does not prove that the real exchange lacks additional liquidity beyond the supplied book.
Qualification requires depth-aware consumption or an explicitly unresolved residual when liquidity cannot be established.
A fixed impact allowance alone cannot prove a complete executable exit.

### Commission deducted from the purchased asset

The fully filled fixture creates a target for gross quantity 1.005.
Under a hypothetical base-asset fee of 0.001005, available inventory is only 1.003995 before exchange rounding.
The target therefore exceeds that scenario's net inventory.

The model accepts quote-valued fee rates but has no fee-asset quantity deduction in this path.
This is a conditional accounting mismatch, not evidence about the actual account's commission asset.
Binance distinguishes received quantity for BUY commission calculations and documents separate BNB payment behavior.
See the [official commission explanation](https://developers.binance.com/en/docs/products/spot/faqs/commission_faq).
Qualification requires explicit base, quote, and discount-asset cases, with no double deduction of fees.

## Disposition and correction boundary

Four assertions confirm the observed behavior; they are not four safety PASS results.
The existing historical-entry and market-matching tests remain separate evidence about their covered scenarios.
The temporary diagnostic is not a permanent regression suite or release artifact.
The new study remains blocked on execution qualification, independently of its proposed entry signal.

The proposed next implementation scope is one coordinated replay correction and qualification set:

1. Define partial-entry protection and cancellation semantics against the actual runtime owner.
2. Separate venue-conditional activation from client submission latency, with explicit unresolved timing assumptions.
3. Enforce emergency-exit liquidity capacity and preserve unresolved residual inventory.
4. Model fee-asset inventory effects and rounding without duplicated fee costs.
5. Add permanent regressions and a new model identity for changed semantics.

Old reports must remain immutable; corrected results need separately identified artifacts on the same inputs.
Those old inputs remain development evidence, not new independent confirmation.
No correction, release, Pi update, cohort import, or trading action is performed by this review.
