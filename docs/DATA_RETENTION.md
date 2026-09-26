# Data retention

The project stores operational data in SQLite databases. Each database has a
specific safety class. Do not use one retention rule for all databases.

## Authoritative data

The following data has no automatic deletion:

- trades and exact fees;
- FIFO inventory lots and cost basis;
- unresolved fills and AI attribution;
- order intents, protection legs, and lifecycle closures;
- migration and recovery evidence.

This data supports accounting, recovery, and safety checks. Archive or retire
it only with a reviewed migration.

BUY settlement evidence is authoritative journal metadata under `buy_inventory_settlement_v1`.
Each BUY can hold one immutable evidence set, limited to 10,000 fills and 2 MiB of serialized evidence.
The record contains order identities, quantities, and exact commission evidence; it contains no credentials.
Retention is indefinite, including pending and protected parents; scheduled retention must not delete this evidence.
Existing encrypted journal backups cover this metadata. No separate archive or cleanup job is introduced.
The total store follows journal growth; capacity exhaustion rejects new evidence without deleting existing records.

The authoritative `zero_fill_cancel_reconciled` flag records a verified cancellation in existing protection metadata.
It adds one Boolean per retired protection, never an execution or an exact-closure record.
Retention is indefinite through existing encrypted journal backups; no new store, archive dependency, or maintenance job is introduced.

Unresolved-fill rows use these permanent lifecycle states:

- `PENDING` blocks the applicable gate.
- `REVIEWED_UNATTRIBUTABLE` records proven history without an invented AI link.
- `RESOLVED_LINKED` records a later exact link to an existing decision.

The runtime never deletes these rows. Retention jobs must not select them.

## Derived data

Legacy prediction snapshots and terminal outcomes are derived evidence.
The retention service keeps 30 days of this data in the active database.
It processes a maximum of 5,000 decisions in one run.
Selection, confirmation, diagnostic, and pending records are never eligible.

The service applies this sequence:

1. Require a successful encrypted backup that is not older than 36 hours.
2. Select legacy decisions whose outcomes are all terminal and older than 30 days.
3. Write a content-addressed gzip JSONL archive with mode `0600`.
4. Recheck the selected rows in one `BEGIN IMMEDIATE` transaction.
5. Delete the archived outcomes and decisions in that transaction.
6. Publish a JSON report.

Pending, settling, overdue, and unresolved outcomes are never eligible. The
service does not run `VACUUM`. SQLite reuses free pages without a long writer
lock or extra SD-card writes.

### Prediction database concurrency

Prediction store initialization requires write-ahead logging (WAL) before schema migration.
Existing committed rows remain unchanged during the journal-mode transition.
An unavailable WAL mode blocks initialization; an unexpected mode blocks subsequent store connections.
Prediction writers retain `synchronous=FULL`, a ten-second busy timeout, and a 1,000-page automatic checkpoint threshold.
This threshold triggers checkpoint work; it is not a hard file-size limit.
Long read snapshots can delay checkpoint completion and temporarily increase WAL disk usage.
Monitor free space during natural backup cycles; never remove live WAL or shared-memory sidecars manually.

The WAL contains committed database state until checkpoint completion; it is not an independently disposable evidence archive.
Shared-memory sidecars coordinate access and contain no independent business records.
SQLite owns their lifecycle; no new deletion timer or evidence-retention rule is introduced.
Use the existing SQLite backup API to capture committed WAL state; copying only the main database file is unsafe.
Backup and retention continue to use existing verified external archives and unchanged eligibility checks.

WAL separates readers from writers, not simultaneous writers.
Retention keeps its bounded atomic writer transaction; contention between writers still fails closed after the existing timeout.
The fix does not establish that every historical contention event involved a reader.
Validate the next natural backup and retention cycle after separately authorized deployment.

### Market scenario retention

Market scenario snapshots and outcomes are derived SHADOW evidence.
The store blocks new snapshots at 250,000 rows.
The scheduled retention job keeps 365 days online.
It archives terminal rows only after a recent verified encrypted backup.
Pending outcomes are never deleted.

Use these commands on Raspberry Pi:

```bash
systemctl status ladder-dragon-database-retention.timer
journalctl -u ladder-dragon-database-retention.service --since today
cat /var/lib/ladder-dragon/database-retention/report.json
```

Exit code `0` means PASS. Exit code `2` means BLOCKED. A missing or stale backup
blocks deletion but does not change the database.

The backup service starts retention only after a successful encrypted backup.
The daily timer provides a safe retry after a temporary BLOCKED result.
A later successful run clears the failed unit state.

## Existing bounded stores

The standalone `record_bnb_public` command writes derived diagnostic public observations, never accounting or lifecycle evidence.
It permits two fixed exclusive slots per explicitly selected external mount: `bnb-public-capture` and `bnb-public-capture-signed-test`.
Each run permits at most 100 requests, 300 seconds, 10,000 events, and 64 MiB of output.
Every response has a 64 KiB encoded and decoded ceiling; the store requires an additional 16 MiB free-space reserve.
Completed and interrupted runs remain indefinitely; the command never overwrites, resumes, or deletes them.
No scheduled collection or maintenance service is installed in this local stage.
Each occupied slot blocks repeat collection; arbitrary slot names are rejected.
Each slot has a 64 MiB logical-file ceiling, with a combined 128 MiB ceiling for both slots.
Bounded metadata checks reject unknown files, nested directories, symlinks, hardlinks, and files on another device.
These application checks are not an operating-system quota against unrelated writers.
Before production scheduling, define reviewed archival maintenance and require a recent verified encrypted external backup before any removal.
The collector never selects private fills, pending records, protected parents, or existing archives for cleanup.
Optional signed capture adds derived `clock.json`, `attestation.json`, and `attestation.sig` within the same exclusive directory.
Clock and attestation documents each have a 16 KiB ceiling; the detached signature contains 64 bytes.
The archive reserves 64 KiB within its existing store limit for manifest and signing metadata.
The public warm-up and qualifying clock measurement consume two requests from the existing total; they do not increase the request ceiling.
The bounded warm-up response is discarded in memory and creates no persistent record.
These records retain the same indefinite preservation, external-disk requirement, and reviewed archival dependency as their archive.
Failed signing never deletes captured observations or authorizes unsigned data; no additional maintenance schedule is installed.
The key loader creates no persistent record and never writes or copies a credential.
Production credential placement and lifecycle remain operator responsibilities; test keys exist only in isolated synthetic fixtures.

The authorized single-run diagnostic also retains one public registration outside its capture slot, with a 16 KiB ceiling.
This authoritative registration binds one diagnostic public key and policy; it never grants trading or replay authority.
Its retention is indefinite until explicit review; no scheduled deletion or backup-content access is introduced.
The one-use private credential exists only in protected runtime storage and is removed after the isolated process stops.
The separately authorized retry retains a second registration, also below 16 KiB, with the same indefinite preservation requirement.
The first failed slot moves intact to `bnb-public-capture-failed-v1`; it contains one zero-byte observation file.
This one-time relocation does not enable automatic slot reuse or additional scheduled capture directories.

On 2026-09-15, separate operator approval preserves the second failed slot intact as `bnb-public-capture-failed-v2` before one new collection.
Both relocated failed directories contain only one zero-byte observation file each; neither is eligible for automatic deletion.
The third public registration occupies `bnb-public-capture-registration-v3`, with one file below 16 KiB and indefinite preservation until explicit review.
The completed third diagnostic uses the existing signed-test slot and its unchanged 64 MiB ceiling, not another active slot.
Its 15,247-byte observation archive and signing metadata remain on the external disk with the public registration.
The one-use private credential and its empty protected runtime directory are removed after the child exits.
No scheduled collection, rotation, slot reuse, or automatic evidence deletion is enabled by this authorization.

### Offline private-source export

The offline exporter creates derived diagnostic source claims, not authoritative fills or verified exchange provenance.
Each explicitly selected external mount permits one fixed `private-fill-export` directory containing only `bundle.fernet`.
The envelope permits eight orders, 64 KiB per source body, 2 MiB of signed-envelope plaintext, and 4 MiB of ciphertext.
The existing external-store check requires 80 MiB free space before directory creation.
Original response bytes, order references, timestamps, and signatures are encrypted in memory before any file write.
No accounting, pending, protected, or existing archive records are selected for modification or deletion.
Interrupted output and completed claims remain indefinitely until an explicit evidence-retirement review; an occupied directory blocks another export.
No scheduled writer, cleanup, rotation, retention job, or automatic slot reuse exists.
Capacity exhaustion blocks export rather than deleting evidence.

The caller supplies distinct in-memory signing and symmetric encryption keys bound to independently reviewed fingerprints.
No private-key persistence or recovery mechanism exists in this local module.
Before real export, approve key custody, encrypted recovery, source scope, trust registration, and a verified encrypted external backup procedure.
Never delete retained evidence before that backup and retirement review.
Plaintext process memory, token creation time, and approximate ciphertext length remain outside the module's file-confidentiality guarantee.

The optional credential-pinned retrieval adapter uses this same single encrypted slot and adds no persistent record type.
At most eight complete order packets remain in memory before encryption; partial retrieval creates no output archive.
Credential values, request authentication parameters, and headers are never included in the retained packet schema.
No new collection schedule, automatic retry, cleanup permission, or private-key storage is introduced.

The authorized one-order smoke procedure adds one exclusive `private-fill-registration-v1` directory on the external disk.
It permits only `registration.json` and `export-key.age`, each limited to 16 KiB; partial directories block another attempt.
The public registration is authoritative for the diagnostic enrollment, not exchange truth or replay admission.
The wrapped export key is recovery evidence encrypted for the existing backup recipient; plaintext key files are prohibited.
Both records remain indefinitely until explicit review, together with any completed or interrupted encrypted export.
The signing key and unwrapped export key exist only in the isolated process memory and are not retained after process exit.
The operator must retain the backup recipient's private identity separately; ciphertext verification does not prove actual recipient recovery.
No backup archive is decrypted, no key is rotated, and no scheduled deletion or collection is enabled.

The authorized second diagnostic uses one additional fixed `private-fill-registration-v2` directory with the same two-file limits and indefinite retention.
It preserves the first registration through pinned hashes; it cannot replace or reuse either registration directory.
The two registrations have a combined 64 KiB content ceiling; they share the single exclusive encrypted-export slot.
The 2026-09-16 authorized run creates this registration and one encrypted export; recent verified encrypted-backup and external-capacity checks pass before collection.
Both registration directories and the encrypted-export slot are now occupied; preserve them without automatic cleanup or reuse.

### 2026-09-14 manual backup capacity recovery

The operator authorizes removal of old encrypted copies after preservation checks.
The reviewed plan removes 595 dated encrypted archives and their checksum sidecars, without decrypting any recovery data.
It preserves every regular backup since 2026-08-31, one older backup per calendar week, and the original preinstallation archive.
All three latest ciphertexts pass SHA-256 verification; the newest also matches the published verified backup status.
This verifies ciphertext integrity, not successful decryption or a complete restore.
The operation holds the existing backup lock and rejects unsafe file types or a changed removal plan.
It leaves 101 regular archives and one preinstallation archive; evidence directories and inventory metadata remain untouched.
Available external capacity increases from approximately 0.86 GB to 18.28 GB, with 70 percent utilization after the smoke attempt.
Deleted versions are not directly recoverable; preserved backups remain available.

This is a one-time cleanup, not a change to scheduled retention configuration.
The backup timer and its last run report success; the implementation has age-based retention without an archive-count ceiling.
The legacy image and mirror backup timers are inactive.
Logrotate reports success and passes its debug check; the sanitized-log export timer and last service run are healthy.
Journald uses volatile storage, a 50 MiB runtime ceiling, 10 MiB files, and seven-day retention.
Its observed usage is approximately 43 MiB; logs do not explain the external disk pressure.

### Other retained stores

- Historical replay checkpoints are derived, immutable complete-path results, not complete selection reports.
- Each report directory allows at most 768 checkpoint files and 64 MiB; each file is limited to 2 MiB.
- Scheduled replay passes check capacity; capacity exhaustion blocks new checkpoints without deleting pending evidence.
- Checkpoints remain indefinitely until reviewed archival with a verified encrypted external backup and all dependent requests.
- The replay status file is disposable replacement telemetry with no archive dependency.

- The risk SELL outcome index keeps the latest 4,096 derived results.
- The risk FIFO index keeps at most 65,536 active derived BUY lots.
- One derived marker identifies each symbol with incomplete FIFO streak history.
- Each exact SELL updates the index with its accounting transaction.
- Consumed risk FIFO lots are removed during the exact SELL transaction.
- A verified non-loss SELL clears its symbol's incomplete streak marker.
- Both risk indexes have no archive dependency because authoritative trades rebuild them.
- The risk control lock is one disposable file and has no growth path.
- RAG documents and retrieval links use the configured 365-day window.
- Public depth archives use the configured 3-to-90-day window.
- Rolling volatility uses one disposable replacement file with no archive dependency.
- Retained depth metadata is rechecked until each covered filled episode becomes terminal.
- Imported L2 features remain append-only after the source archive expires.
- Mainnet validation archives retain at most 40 sessions or 512 MiB.
- Validation capacity blocks new drills. It never deletes replay evidence.
- Archive validation evidence only after a verified encrypted backup and promotion audit.
- A terminal rejected validation batch can enter manual encrypted archival.
- Its manifest, hash-chained ledger, and archival audit are authoritative release evidence.
- One deterministic audit can exist for each terminal batch.
- These records remain local indefinitely and have no scheduled deletion.
- The external verified bundle contains each removed public archive and metadata file.
- Each bundle contains at most 12 derived public archives and their metadata.
- Sanitized logs and dashboard history use file-size and age limits.
- Encrypted backup archives reside only on the external disk.
- Local storage contains temporary private staging and public archive pointers, not archive mirrors.
- Old private staging uses an exact timestamp grammar and a sixty-minute minimum age.
- External rotation preserves the newest encrypted archive.
- Each run verifies its new external archive before publishing its pointer.

The backup includes database archives. Do not delete an archive only because
the active database is smaller.
