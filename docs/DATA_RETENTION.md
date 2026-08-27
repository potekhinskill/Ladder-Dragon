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

Unresolved-fill rows use these permanent lifecycle states:

- `PENDING` blocks the applicable gate.
- `REVIEWED_UNATTRIBUTABLE` records proven history without an invented AI link.
- `RESOLVED_LINKED` records a later exact link to an existing decision.

The runtime never deletes these rows. Retention jobs must not select them.

## Derived data

Prediction SHADOW decisions and terminal outcomes are derived evidence. The
daily retention service keeps 365 days in the active database. It processes a
maximum of 2,000 decisions in one run.

The service applies this sequence:

1. Require a successful encrypted backup that is not older than 36 hours.
2. Select decisions whose outcomes are all terminal and older than 365 days.
3. Write a content-addressed gzip JSONL archive with mode `0600`.
4. Recheck the selected rows in one `BEGIN IMMEDIATE` transaction.
5. Delete the archived outcomes and decisions in that transaction.
6. Publish a JSON report.

Pending, settling, overdue, and unresolved outcomes are never eligible. The
service does not run `VACUUM`. SQLite reuses free pages without a long writer
lock or extra SD-card writes.

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

The systemd service records BLOCKED as a failed unit. A later successful run clears the failure.

## Existing bounded stores

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
- Retained depth metadata is rechecked until each covered filled episode becomes terminal.
- Imported L2 features remain append-only after the source archive expires.
- Mainnet validation archives retain at most 32 sessions or 512 MiB.
- Validation capacity blocks new drills. It never deletes replay evidence.
- Archive validation evidence only after a verified encrypted backup and promotion audit.
- Sanitized logs and dashboard history use file-size and age limits.
- Encrypted backups use local and external retention policies.
- External rotation runs before mirroring and preserves the newest encrypted archive.

The backup includes database archives. Do not delete an archive only because
the active database is smaller.
