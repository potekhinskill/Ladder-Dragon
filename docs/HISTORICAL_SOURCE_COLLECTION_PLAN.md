# Historical source collection plan

Prepared: 2026-09-16.
Status: local collector implementation; production collection remains unauthorized.
Current authorization covers local implementation and synthetic verification, not publication, deployment, private requests, or accounting imports.

## Internal input storage candidate: 2026-10-26

The operator approves system-storage custody for bounded diagnostic inputs after exFAT rejects the required private permissions.
This local candidate supersedes the input locations below, not the historical evidence, execution limits, or separate activation approvals.
It is not deployed; the installed `v2.20.353` still uses the earlier external input paths.

| Input | Candidate location |
|---|---|
| Encrypted account assertion | `/var/lib/ladder-dragon/account-enrollment-v1/enrollment.age` |
| Encrypted export-key recovery | `/var/lib/ladder-dragon/history-launch-inputs-v1/export-key.age` |
| Encrypted diagnostic | `/var/lib/ladder-dragon/history-launch-inputs-v1/diagnostic.fernet` |

Manifests and the dedicated signer retain their fixed protected configuration paths.
The history bundle remains `/mnt/usb1/historical-sol-source-v1/bundle.fernet`; backup archives remain external.
The `expected_device` launcher option still pins the external disk during history preparation.
The diagnostic writer independently requires the system filesystem and root-owned ancestors, rather than accepting that external device for private inputs.
Every directory uses mode 0700 and every input file uses mode 0600; creation remains exclusive.
The writer reopens ancestors and compares directory and file identity before accepting persistence.
Retain existing byte ceilings, free-space reserves, failed reservations, request deadlines, and all false admission flags.
See [retention limits](DATA_RETENTION.md#historical-source-claims) for this bounded internal exception.

No automatic migration or fallback reads the earlier external paths.
The empty external diagnostic directory remains preserved; it grants no activation authority.
Release verification and separate deployment approval must precede use of the changed paths.
Independent credential pins, enrollment, recovery verification, and exact diagnostic approval remain required.

## Activation proposal: 2026-10-16

### Production preflight review: 2026-10-16

Status: BLOCKED. This review prepares a diagnostic permit; it does not authorize or execute one.
Only SSH metadata and service-state reads were performed on Raspberry Pi.
No secret, enrollment contents, balances, backup contents, or raw exchange evidence were read.
No API request, deployment, service restart, ownership change, or HALT change occurred.

Observed deployment: `cd94c794cdb982a5e0b20f1cc344fd513108f275`, the existing `v2.20.352` baseline.
Tracked deployed files are clean; the new diagnostic launcher module is absent.
The local `2.20.353` candidate remains uncommitted and has no final reviewed release SHA.
Earlier local test results do not constitute a release-profile PASS for an immutable candidate.

Both `mybot` and `pi-healthd` report active/running, with `NRestarts=0` at inspection.
The regular HALT file exists; its contents and active-state semantics were not inspected.
The external mount is distinct from system storage, with 18,185,846,784 bytes free at inspection.
Its observed device number is 2065; recheck it immediately before activation because device numbers are not permanent identities.
Metadata checks found memory-only swap, `/run` on tmpfs, no piped core handler, and acceptable age executable metadata.
These observations do not replace the isolated worker's full hardening checks.

Blocking items recorded on 2026-10-16:

1. Resolve the storage ownership contract before release.
   The external mount belongs to `bot`, while hardening requires root and both storage guards require the effective user's ownership.
   The current launcher therefore rejects this host before requests.
   Review a narrow ownership policy and add a regression for the actual host layout; do not bypass checks or recursively change ownership.
2. Finish the corrected candidate, sign it, and pass the complete release profile on that exact SHA.
   Publication and deployment require separate current authorization; do not copy uncommitted modules onto Pi.
3. Provision and independently review the missing protected inputs under separate authorization.
   Missing paths include the diagnostic manifest, signer, encrypted enrollment, encrypted export-key recovery, and input directory.
   The fixed dashboard source exists with mode 0600, but its contents, scope, and permissions remain unverified.
4. Decide and record the signer's lifecycle and recovery custody before provisioning.
   No existing backup key or previous diagnostic identity is implicitly selected.
5. Verify interactive hidden recovery access, current shared request capacity, and a bounded operator-approved execution window.
   No final manifest digest or execution window is available yet.

The diagnostic output and historical collection slot are absent.
Absence is not reservation; repeat the exclusive-create and mount checks at execution time.
The effective preparation reserve remains 8 GiB plus 16 MiB, stricter than the diagnostic writer's 3 MiB allowance.

### Local ownership correction: 2026-10-17

The candidate now permits the hardened process owner or the exact local `bot` account as the external mount owner.
The root-only process requirement remains unchanged; no arbitrary UID, group membership, or environment override grants ownership trust.
Missing `bot` account resolution rejects a non-root mount instead of selecting another owner.
The exception applies only to the mount point, not its ancestors, diagnostic directory, or ciphertext file.
All ancestors remain root-owned in production; group or other write permission remains forbidden.
The diagnostic directory must remain root-owned with mode 0700; the ciphertext must remain root-owned with mode 0600 and one link.

Because the mount owner can rename a child directory, the writer reopens the named directory without following symlinks.
It compares device and inode with the retained descriptor before requests, before writes, and after synchronization.
Renamed, detached, substituted, or symlinked directories block success without deleting the original reservation or ciphertext.
Mount identity, capacity, exclusive creation, signatures, independent pins, and false admission flags remain unchanged.
These checks do not guarantee future availability against a compromised mount owner after the final validation.

The first preflight blocker is corrected locally, not verified on a deployed release.
Local verification passes: 157 focused tests, 5502 complete-suite tests, two skips, compilation, and all five safety audits.
No ownership, permission, service, or HALT changes were made on Raspberry Pi.
Release verification, provisioning, recovery custody, and exact single-run approval remain blocking prerequisites.

### Activation review update: 2026-10-17

Status: BLOCKED; no diagnostic execution is authorized or attempted.
This review reads only deployed revision, fixed-path metadata, mount capacity, and service state over SSH.
It does not read credentials, private registrations, keys, balances, or archive contents.

The deployed SHA remains `cd94c794cdb982a5e0b20f1cc344fd513108f275`; tracked files are clean and the diagnostic launcher module is absent.
Both inspected services, `mybot` and `pi-healthd`, are active/running with `NRestarts=0`.
The external disk is mounted, mode 0755, device 2065, with 17,897,226,240 bytes free at inspection.
The regular HALT file remains present with mode 0600; metadata alone does not prove the effective trading gate.
Neither output slot exists; absence does not reserve a slot.

Remaining prerequisites, in order:

1. Complete an immutable release candidate and its full release verification, then obtain publication and deployment approval.
   Prior local tests cover the correction, not an installed release or production custody.
2. Review the released `account_diagnostic_launch` command, including its terminal and recovery behavior.
   A local CLI now delegates to `diagnostic_launch.run`; the preparation CLI cannot substitute for it.
   Do not bypass the external supervisor by calling `execute`, `worker`, or the producer directly.
3. Agree on signer lifetime, independent public registration, encryption-key custody, and hidden recovery access.
   Earlier backup-key recovery is not proof of recovery for these diagnostic inputs.
4. Separately authorize protected provisioning of the missing manifest, signer, encrypted enrollment, encrypted export key, and diagnostic directory.
   These fixed paths remain absent; this review creates none of them.
   The diagnostic directory must be root-owned, mode 0700; do not recursively change the disk owner.
5. Independently verify private pins, selected credential restrictions, and an unused output slot before approving requests.
   Current exchange permissions are not established by this metadata review; the approved diagnostic must validate the actual responses.
6. Bind approval to the released SHA, private manifest digest, current mount identity, and an explicit UTC start window.
   Confirm shared request capacity and the effective HALT/buy-block state without exposing sensitive status fields.

The final approval must reference one protected activation record, not placeholders or values copied from an unverified manifest.
That record must contain the four exact launcher options: `confirmed`, `expected_code_sha`, `expected_device`, and `manifest_sha256`.
The operator must separately enforce the start window and one-attempt budget; the library does not persist an approval-consumption record.
Consume the approval when invocation starts, including preparation failure before any request; retries require a new review and approval.
The current device number is an observation, not a permanent disk identity or a preapproved future argument.

### Concrete diagnostic command: local candidate only

The CLI requires explicit confirmation, exact code and manifest pins, a device number, and a controlling terminal.
Unknown arguments and malformed pins produce safe status without dispatch; there is no default execution or direct worker entry.
An approved command delegates once to the external supervisor, with its existing 300-second and 35-second deadlines.
The operator supplies the recovery identity through hidden terminal prompts, separately for enrollment and export-key recovery.
Never put a recovery identity, credential, or account identifier in command arguments, shell variables, or chat.

CAUTION: the following template can issue private API requests after all guards pass.
It is not authorized for execution during release preparation.
Only after release installation, provisioning, and exact one-shot approval, use an interactive terminal on the reviewed Pi.
Replace the three placeholders from the independently verified activation record; do not infer them from current files.

```text
cd /home/bot/apps/binance_bot
sudo -n env PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m bin.account_diagnostic_launch \
  --confirmed --expected-code-sha <approved-40-character-SHA> \
  --expected-device <fresh-approved-device-number> \
  --manifest-sha256 <independently-reviewed-64-character-digest>
```

Exit 0 means only `DIAGNOSTIC_SAVED_ONLY`; exit 2 means a blocked attempt.
Neither exit code grants historical collection, replay, or trading authority.
Do not repeat a failed command or delete its reserved output.
The start window and approval consumption remain operator controls, not additional CLI guarantees.

### Draft single-run diagnostic permit: NOT EXECUTABLE

The following permit is a draft until every blocking item above is closed.
Bind the final approval to the exact released SHA, independently reviewed private manifest digest, mount identity, and execution window.
Keep private registrations, fingerprints, credential scopes, and account identity out of Git and chat.
Do not substitute the old deployed SHA or infer permission from a generic continuation message.

- Scope: one Stage A diagnostic invocation on Raspberry Pi; no automatic repeat after failure or timeout.
- Host: the reviewed production Pi, with HALT preserved and all service states unchanged.
- Target: `https://api.binance.com`, with TLS verification and no alternate hosts or redirects.
- Requests: at most three sequential GETs, in this order: `/api/v3/time`, `/api/v3/account`, `/sapi/v1/account/apiRestrictions`.
- Authentication: the fixed dashboard read-only credential source only; never use a trading credential or fallback source.
- Time: at most 300 seconds for preparation, then an externally enforced 35 seconds for requests through persistence.
- Transport: no retries; at most five seconds per cooperative HTTP phase, within the external deadline.
- Response ceilings: 1024 bytes for time, 1 MiB for account, and 16 KiB for permissions.
- Destination: `/mnt/usb1/history-launch-inputs-v1/diagnostic.fernet`, exclusive creation only, mode 0600, ciphertext at most 3 MiB.
- Preservation: retain empty reservations and partial ciphertext; no deletion, replacement, automatic retry, or manifest rewrite.
- Stop: any guard, identity, permission, clock, TLS, rate-limit, request, size, deadline, signature, encryption, or persistence failure.
- Exclusions: no historical `myTrades` collection, orders, transfers, accounting import, replay, promotion, or trading.
- Result: only safe status, ciphertext size, and ciphertext digest; success remains `DIAGNOSTIC_SAVED_ONLY` with all admission flags false.

Public endpoint documentation was reviewed without contacting an exchange API endpoint.
Documented request weights are 1 for [time](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/general),
20 for [account](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/account),
and 1 for [API restrictions](https://developers.binance.com/en/docs/catalog/core-trading-wallet/api/rest-api/account).
Confirm capacity in each applicable API/SAPI limiter; this review does not measure the shared IP's available quota.
The request budget is not a monetary trading limit: this diagnostic permits no order and no trading turnover.

After preservation, independently review the output before registering a final history-input manifest.
Neither diagnostic success nor this draft grants Stage B collection authority or permission to remove HALT.

Approval wording, valid only after the prerequisites and private activation record are complete:

> I authorize one Stage A diagnostic attempt on the reviewed Raspberry Pi under the independently verified activation record.
> Use its exact released SHA, manifest digest, mount identity, and UTC start window, with the limits stated above.
> Permit at most three sequential GET requests, no retries, and no trading turnover.
> Preserve HALT, services, existing files, and failed reservations; do not collect historical trades or import evidence.
> This permission expires after the first invocation or the approved start window, whichever occurs first.

This wording is a proposal, not current authorization; an incomplete or changed activation record blocks execution.

The operator selects bounded API collection and requests exact admission limits.
This request authorizes preparation, not network activation, enrollment creation, decryption, accounting imports, or HALT removal.
Status: production remains BLOCKED on release verification, independent custody review, current permissions, and separate activation approval.
The protected diagnostic launcher is implemented locally; the historical collection dispatcher remains unimplemented.

The reviewed source reference is `v2.20.352`, commit `cd94c794cdb982a5e0b20f1cc344fd513108f275`.
This reference contains collector libraries, not a reviewed production history launcher.
Any launcher implementation requires verification and an exact replacement release reference before activation.

### Separate one-shot budgets

| Stage | Endpoint scope | Maximum requests | Process deadline | Activation boundary |
|---|---|---|---|---|
| A: account diagnostic | GET time, account, and API restrictions | 3 total | 35 seconds | Explicit diagnostic approval after enrollment and credential pins |
| B: SOL history | GET time and SOLUSDT myTrades only | 22 total: two clock requests and twenty pages | 150 seconds | Separate collection approval after Stage A review |

Each stage permits one attempt, one sequential request at a time, and no automatic retries or redirects.
The combined ceiling is 25 requests; neither stage borrows unused requests from the other.
Stage A success does not start Stage B automatically.
The deadlines bound the isolated child; termination and reaping add cleanup time.
Do not bypass the process wrapper because HTTP timeouts do not bound blocked DNS.

Stage B starts at `fromId=0`, with 200 records per page and at most 4000 received records.
Retain the exclusive cutoff `2026-09-16T00:00:00Z`; do not extend it silently to the collection date.
This collection targets the historical import boundary, not complete current history through October.
Preserve beyond-cutoff records as excluded boundary evidence.
Require complete page validation before cursor advancement.
Apply 256 KiB response limits per trade page and 1024 bytes per clock response.
Keep the five-second response deadline inside the outer process deadline.

### Exact proposed destination and custody

Proposed destination: `/mnt/usb1/historical-sol-source-v1/bundle.fernet`.
The collector uses Fernet encryption and Ed25519 signatures, not the backup age key directly.
Prior age-key recovery does not establish recovery of this collection key.
The encrypted package ceiling is 16 MiB; the plaintext envelope ceiling is 12 MiB in memory.
No plaintext evidence file is permitted.

Before activation, verify the external mount identity, owner-controlled parent, and absence of the destination slot.
Require at least 8 GiB free space plus the 16 MiB package allowance.
Reject symlinks, unsafe permissions, occupied slots, or an unavailable external disk.
The directory must use mode 0700; the package must use mode 0600.
Preserve failed slots and interrupted ciphertext; do not overwrite or remove them during a retry.
No automatic retention applies to this unresolved source package.

### Required activation record

Keep these private pins in protected operator custody, not Git or chat:

1. The independently enrolled account reference and verified recovery result.
2. The exact selected dashboard credential source and its verified read-only permission scope.
3. The trusted signing registration and fingerprint.
4. The collection encryption-key fingerprint and verified recovery result.

Record the reviewed launcher release SHA, external mount identity, exact destination, and stage-specific request budget.
Confirm shared exchange request capacity before activation.
Recheck the official endpoint contract before the production request.
Do not discover credentials through environment-file searches or derive expected identity from the response under verification.

Stop on identity mismatch, mutation permissions, clock failure, rate limits, authentication failure, malformed pages, or capacity exhaustion.
Also stop on any byte, request, record, or time limit.
Do not change DNS, TLS checks, clock thresholds, service state, or trading controls to obtain a successful result.

### Acceptance remains separate from collection

Return only fixed status codes, stage, reason, and aggregate counts to ordinary logs.
Preserve `history_complete=false`, `private_fills_authenticated=false`, and `replay_allowed=false` after collection.
A short page, signature, or diagnostic identity match does not prove complete account history.
Opening inventory and relevant non-trade SOL movements remain independent requirements.
Compare sources offline before requesting any authoritative accounting change.
STOP execution, cancellation timing, commission valuation, and paired runtime/replay qualification remain separate gates.

No production request, key access, enrollment creation, or database change accompanies this proposal.

### Offline launcher preparation: 2026-10-16

The local command `python -m bin.history_launch_prepare` implements only offline host preparation.
It requires `--confirmed`, `--expected-code-sha`, and `--expected-device` before it creates an isolated child.
The SHA is the exact reviewed checkout; the device is the reviewed external mount device number.
No private values belong in these arguments.

The child checks existing host restrictions, the clean checkout, HALT presence, external ownership, capacity, and destination absence.
The parent enforces a 35-second deadline; operating-system termination and reaping can add cleanup time.
The command does not inspect HALT contents, read credentials, open archives, reserve storage, or invoke either API stage.
All failures return fixed stage codes without exception text.
Successful preparation returns `PREPARATION_ONLY` and exit code 2, with `collection_allowed=false`.
It is not a durable attestation; later activation must repeat all checks before access.

The existing hardening routine also checks Linux isolation, swap, core dumps, and parent-death behavior.
These controls restrict the disposable process; they do not change host configuration.
The preparation command does not provide an operating-system network sandbox.
The production collection dispatcher remains unimplemented.
Do not infer enrollment, diagnostic success, key recovery, or collection permission from this preparation result.

### Protected offline input verification: 2026-10-16

The optional `--manifest-sha256` argument enables protected input verification after the existing host, checkout, HALT, and storage checks.
Without this argument, preparation does not access private inputs.
This mode uses a 300-second isolated-process deadline for operator recovery input; it makes no API requests.
The separate diagnostic and collection request budgets remain unchanged.

The operator must independently review the exact manifest digest before invocation.
The loader accepts only these fixed files:

| File | Role and limit |
|---|---|
| `/root/.config/ladder-dragon/history-launch-inputs.json` | Protected manifest, at most 4096 bytes |
| `/mnt/usb1/account-enrollment-v1/enrollment.age` | Existing encrypted account claim, at most 16 KiB |
| `/mnt/usb1/history-launch-inputs-v1/export-key.age` | Encrypted Fernet key recovery, at most 16 KiB |
| `/mnt/usb1/history-launch-inputs-v1/diagnostic.fernet` | Encrypted signed diagnostic, at most 3 MiB |

The loader rejects unsafe ownership, permissions, symlinks, hardlinks, changed file identity, oversized inputs, and digest mismatches.
It creates no file, slot, key, registration, or receipt.
Production provisioning of these files remains a separately reviewed task.
Keep all contents, credential scopes, and enrollment references outside Git, chat, and ordinary logs.

The manifest schema is `history_launch_inputs_v1`.
It pins the launcher and diagnostic code revisions, enrollment reference, credential scope, recovery recipient, ciphertext digests, and diagnostic signing key.
The signing-key fingerprint must match the manifest public key; the expected manifest digest must not come from the file itself.
The exact schema and field validation are owned by `strategy/history_input_contract.py`.

Recovery uses the operator-held age identity through hidden terminal input and a sealed anonymous memory descriptor.
The loader verifies the recovered enrollment reference and credential scope before recovering the Fernet key.
The recovered key must match its independently pinned fingerprint and decrypt the pinned diagnostic package.
The fixed dashboard credential source must still contain the expected API key.
The loader does not read a trading secret or perform a new permission request.

The diagnostic uses a separate signature domain: `LadderDragon:history-account-diagnostic:v1` with a trailing zero byte.
It binds exact account and permission responses, enrollment identity, credential scope, code revision, and request timing.
The verifier recomputes account matching and read-only permission checks; it does not accept a summary PASS field.
It requires three declared requests, a clock-check claim, at most 35 seconds elapsed, and at most 300 seconds since completion.
Future timestamps, inconsistent wall and monotonic elapsed times, unknown fields, and invalid signatures block verification.
Signed plaintext is bounded to 2 MiB and stays in memory.

This verifies trusted collector claims, not an exchange signature or historical account ownership.
The summary-only interface still returns no source package.
The local producer described below uses the same diagnostic request owner and returns encrypted observations.
Do not fabricate a receipt from an old PASS summary or sign reconstructed responses as actual observations.
No real diagnostic package, registration, or recovery evidence is created or accessed during local synthetic tests.

Success returns `INPUT_CLAIMS_VERIFIED_ONLY`, exit code 2, and false collection, history-completeness, private-fill-authentication, and replay flags.
The result is not a durable authorization or a revocation check.
Future collection must recheck current permissions, freshness, source pins, and host conditions under separate exact activation approval.
No memory-erasure guarantee or protection against a compromised host is claimed.

Local synthetic verification passes: 165 focused tests and 5406 complete-suite tests, with two skips.
Compilation, all five safety audits, and the documentation check pass.
These results do not verify production enrollment, current exchange permissions, or operator recovery on Raspberry Pi.

### Local diagnostic package producer: 2026-10-16

`strategy/diagnostic_package.py` connects the canonical diagnostic request chain to the existing signed-input verifier.
The library requires explicit confirmation and independent signing, encryption, enrollment, credential, and code pins.
Absent confirmation or invalid key bindings prevent all requests.
The protected enrollment loader checks the account reference and credential scope before the first request.

Only successful clock, account, permission, and elapsed-time checks reach the private package sink.
The sink signs the exact received account and permission bytes, measured times, and actual request count.
It verifies the complete signed envelope through the consumer contract before encryption.
It returns a bounded encrypted byte string separately from a fixed safe summary.
Never put the returned byte string in ordinary logs, chat, or Git.
A failed comparison, invalid count, signing failure, or summary without observations returns no package.

Success reports `ENCRYPTED_DIAGNOSTIC_ONLY`; collection, history completeness, private-fill authentication, and replay remain false.
This library creates no file, manifest, registration, key, scheduler, or automatic collection chain.
The original summary-only diagnostic interface retains its existing behavior.

The protected wrapper and exclusive writer described below now integrate this producer locally.
Production use still requires an unchanged signed-candidate release profile, independently reviewed custody, and separate activation approval.
The producer validates supplied pins; it does not independently establish those custody facts or inspect the deployed checkout.
The final manifest digest requires independent review after ciphertext creation; the producer cannot grant trust to its own output.
The offline preparation command does not invoke this producer.

Local round-trip and adjacent regressions pass: 180 tests, with synthetic credentials and substituted HTTP responses.
The complete suite passes with 5427 tests and two skips; compilation, five safety audits, and documentation checks pass.
No production API request, file provisioning, deployment, or HALT change accompanies these checks.

### Protected diagnostic process and exclusive storage: 2026-10-16

`strategy/diagnostic_launch.py` exposes an explicit opt-in library entry, not a CLI, service, or scheduled job.
Its options are `confirmed`, `expected_code_sha`, `expected_device`, and `manifest_sha256`.
Absent exact confirmation or malformed options prevent child creation.
Only these non-secret options cross anonymous stdin; no key, account identity, or raw response crosses the process boundary.

The isolated child first verifies host restrictions, the exact clean checkout, HALT presence, external storage, and the unused historical destination.
It reads a fixed protected manifest at `/root/.config/ladder-dragon/diagnostic-launch.json` only after those checks.
The independently reviewed digest pins its exact bytes.
The `diagnostic_launch_v1` schema uses the history-input manifest fields except `diagnostic_sha256`; no output exists yet.
Both code revision fields must equal the reviewed checkout.
The existing pin grammar checks enrollment, credential scope, recovery ciphertext, recipient, encryption key, and signer identity.

Recovery uses the existing encrypted enrollment and export-key files through hidden operator input.
The child loads the signer only from `/root/.config/ladder-dragon/diagnostic-signing.pem` and validates its independently pinned public key.
This private key file is bounded to 4096 bytes and requires protected ownership, permissions, and symlink-free access.
Credentials come only from the fixed dashboard source, with strict duplicate rejection and credential-scope matching.
Secrets remain local to the hardened process; the worker creates no plaintext enrollment file or serialized key-transfer message.
Host, checkout, HALT, and storage guards repeat after recovery, before the request barrier.

The parent permits at most 300 seconds for preparation and hidden recovery input.
The child announces readiness and waits for acknowledgement before any diagnostic request.
The parent arms a separate 35-second deadline before acknowledgement; it covers requests, signatures, encryption, and persistence.
Blocked DNS cannot extend this outer request deadline.
Timeout, malformed output, interruption, or excess output terminates and reaps the worker.
Existing parent-death guards also protect age-child lifetime; operating-system termination latency prevents a hard real-time guarantee.
Output is bounded to 2048 bytes and contains only the fixed protocol and sanitized final report.

The writer requires the existing owner-only `history-launch-inputs-v1` directory on the pinned external device.
It reserves `diagnostic.fernet` with exclusive creation, mode 0600, and descriptor-relative symlink checks before private recovery or requests.
An occupied file, directory, symlink, or interrupted reservation blocks another attempt.
It requires at least 8 GiB free space plus the 3 MiB ciphertext allowance.
Only verified encrypted bytes reach the reserved descriptor; file and directory synchronization precede success.
Empty reservations, partial ciphertext, and completed ciphertext survive every failure; there is no overwrite, unlink, retry, or automatic cleanup.

Success reports `DIAGNOSTIC_SAVED_ONLY`, ciphertext size, and ciphertext SHA-256; all collection, history, authentication, and replay flags remain false.
The writer never edits the final trusted history-input manifest or starts historical collection.
Review the saved ciphertext digest independently before any subsequent offline manifest registration.
Provisioning, signer lifecycle, current shared request capacity, and actual operator recovery still require production review.
Local tests use synthetic files and responses; no production package or permission evidence is created.
Protected-launch verification passes: 271 focused tests and 5481 complete-suite tests, with two skips.
Compilation, all five safety audits, documentation checks, and static cycle checks for the new modules pass.

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

The protected diagnostic launcher now integrates these checks locally; production custody and activation remain separately reviewed.
The historical collection dispatcher remains unimplemented.
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
