# Ladder Dragon Raspberry Pi installation and update runbook

This runbook targets Raspberry Pi OS Bookworm/Debian with `systemd`. The
canonical project directory is `/home/bot/apps/binance_bot`.

Fresh installation always starts in **Testnet DRY**. No real order is sent.

## 1. Prepare the host

Recommended hardware is a Raspberry Pi 4/5 with at least 4 GiB RAM, 64-bit
Raspberry Pi OS Lite, reliable storage, stable power, SSH, a fixed DHCP lease,
and synchronized time.

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git openssh-client ca-certificates gnupg
sudo timedatectl set-timezone Asia/Almaty
timedatectl status
```

Reboot after a kernel update:

```bash
sudo reboot
```

## 2. Configure private GitHub access

Create the service account and a read-only **Deploy Key**:

```bash
id bot >/dev/null 2>&1 || sudo useradd --create-home --shell /bin/bash bot
sudo install -d -o bot -g bot -m 0700 /home/bot/.ssh
sudo -u bot ssh-keygen -t ed25519 \
  -f /home/bot/.ssh/ladder_dragon_github -N '' \
  -C 'ladder-dragon-raspberry'
sudo cat /home/bot/.ssh/ladder_dragon_github.pub
```

Add the public key in **Repository → Settings → Deploy keys** with write access
disabled. Configure SSH:

```bash
sudo tee /home/bot/.ssh/config >/dev/null <<'EOF'
Host github.com
    HostName github.com
    User git
    IdentityFile /home/bot/.ssh/ladder_dragon_github
    IdentitiesOnly yes
EOF
sudo chown bot:bot /home/bot/.ssh/config
sudo chmod 600 /home/bot/.ssh/config
sudo -u bot ssh-keyscan github.com | sudo tee /home/bot/.ssh/known_hosts >/dev/null
sudo chown bot:bot /home/bot/.ssh/known_hosts
sudo chmod 600 /home/bot/.ssh/known_hosts
sudo -u bot ssh -T git@github.com
```

GitHub's successful-authentication/no-shell response is expected.

## 3. Clone and install

```bash
sudo install -d -o bot -g bot -m 0750 /home/bot/apps
sudo -u bot git clone --branch main --single-branch \
  git@github.com:potekhinskill/Ladder-Dragon.git /home/bot/apps/binance_bot
cd /home/bot/apps/binance_bot
RELEASE_SHA="$(sudo -u bot git rev-parse HEAD)"
RELEASE_FINGERPRINT="$(
  gpg --show-keys --with-colons docs/release-signing-key.asc |
  awk -F: '$1 == "fpr" {print toupper($10); exit}'
)"
test "$RELEASE_FINGERPRINT" = \
  '808B9F52CB6C08901703EF7C113144122F1830A0'
sudo -u bot gpg --batch --import docs/release-signing-key.asc
sudo -u bot git verify-commit "$RELEASE_SHA"
sudo bash deploy/install_raspberry_pi.sh install --commit "$RELEASE_SHA"
```

Confirm the displayed release fingerprint through an independent channel before
trusting the first clone. The installer repeats the exact-signature check before
activating the project and refuses an unsigned or differently signed commit.

The installer creates the virtual environment, nginx, FastAPI, fail2ban, zram,
journald limits, systemd units, mDNS (`bot.local`), local TLS, Basic Auth,
protected `/logs/` and `/backups/`, encrypted backups, and the watchdog. It
does not place secrets in Git and starts `mybot` as Testnet DRY.

The dashboard password is stored at:

```bash
sudo cat /root/ladder-dragon-dashboard-credentials.txt
```

## 4. Configure Binance and AI

Secrets belong only in `/home/bot/apps/binance_bot/.env`:

```bash
sudo -u bot nano /home/bot/apps/binance_bot/.env
```

Start with Testnet:

```dotenv
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_API_SECRET=...
BINANCE_TESTNET_API_BASE=https://testnet.binance.vision
BOT_LIVE_CONFIRMED=NO
AI_ADVISOR_ENABLE=1
AI_MODE=SHADOW
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
BOT_EXPECTANCY_MODE=SHADOW
BOT_MAKER_POLICY_MODE=SHADOW
BOT_REGIME_GATE_MODE=SHADOW
BOT_INVENTORY_SKEW_MODE=SHADOW
RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT=30
BUY_VWAP_HYSTERESIS_PCT=0.0002
```

All listed strategy controls are observation-only in `SHADOW`. They cannot
change a worker plan. Authoritative BUY/SELL fee rates are still passed for
exact accounting, while `BOT_REQUIRED_EDGE_PCT` is omitted unless expectancy
is approved and actually in `APPLY`. The managed-inventory CAP is an explicit
quote-value limit for the named symbol; it never inherits the larger portfolio
CAP. Review one positive value for every traded symbol.

Do not copy `.env.example` over an installed `.env`. Normal updates preserve
the live file and do not add new variables automatically. After an update,
check only whether required names exist, without printing their values:

```bash
grep -q '^RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT=' .env \
  || echo 'REVIEW REQUIRED: managed inventory CAP is missing'
```

```bash
sudo chown bot:bot /home/bot/apps/binance_bot/.env
sudo chmod 600 /home/bot/apps/binance_bot/.env
```

Use a separate read-only Binance key for dashboard equity:

```bash
sudo -u bot nano /home/bot/apps/binance_bot/.env.dashboard
```

```dotenv
DASHBOARD_BINANCE_API_KEY=...
DASHBOARD_BINANCE_API_SECRET=...
```

Never copy a trading Mainnet key into `.env.dashboard`.

### Telegram alerts

```bash
sudo install -o root -g bot -m 0640 /dev/null /etc/ladder-dragon/telegram.env
sudo nano /etc/ladder-dragon/telegram.env
```

```dotenv
TELEGRAM_ALERTS_ENABLED=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

The installer migrates `/etc/bot-alerts.env` when present and removes that old
path only after the current root-owned file has been created successfully.
Circuit-breaker and execution failures remain fail-closed if Telegram is unavailable.

Verify configuration without printing values:

```bash
sudo awk -F= '/^(TELEGRAM_ALERTS_ENABLED|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=/ {print $1 "=" (length($2) ? "<set>" : "<empty>")}' /etc/ladder-dragon/telegram.env
```

## 5. Select the execution mode

Systemd mode is stored separately in `.env.service`:

```dotenv
BOT_SERVICE_VENUE=testnet
BOT_SERVICE_EXECUTION=dry
BOT_SERVICE_SYMBOLS=SOLUSDT,ETHUSDT,TONUSDT
```

Testnet LIVE requires both `BOT_LIVE_CONFIRMED=YES` in `.env` and
`BOT_SERVICE_EXECUTION=live` in `.env.service`. Mainnet LIVE requires a
separate review of filters, balance, CAP, reserve, protection, and circuit state.

```bash
sudo systemctl restart mybot
sudo systemctl is-active mybot pi-healthd nginx
```

## 6. Verify the installation

```bash
cd /home/bot/apps/binance_bot
sudo bash deploy/update_raspberry_pi.sh check
sudo journalctl -u mybot -n 100 --no-pager
sudo journalctl -u pi-healthd -n 50 --no-pager
curl -sk -u dashboard https://bot.local/api/health
curl -sk -u dashboard https://bot.local/api/ai/status
```

The dashboard API listens only on `127.0.0.1`; port `8081` must not be exposed.

## 7. Run Testnet smoke and recovery checks

```bash
sudo systemctl stop pi-watchdog-v3.timer
sudo systemctl stop mybot
sudo -u bot env PYTHONPATH=. .venv/bin/python -m pytest -q
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.binance_testnet_smoke --mode public --symbol SOLUSDT
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.binance_testnet_smoke --mode authenticated --symbol SOLUSDT
sudo systemctl start mybot
sudo systemctl start pi-watchdog-v3.timer
```

`mybot.service` delivers `SIGTERM` to the supervisor and every worker in the
control group. The supervisor translates its first TERM into the normal
`STOPPING` path, waits for workers to exit gracefully, and retains TERM/KILL
timeouts as a final bound. A worker that exits repeatedly is counted in a
rolling one-hour window: the third non-zero exit activates exponential backoff
even when each run lasted longer than the short-crash threshold, and the fifth
emits one Telegram restart-storm alert. These defaults are configurable through
`BOT_CHILD_RESTART_WINDOW_SEC`, `BOT_CHILD_RESTART_WINDOW_LIMIT`, and
`BOT_CHILD_RESTART_ALERT_COUNT`.

The optional lifecycle check uses a minimal isolated Testnet position:

```bash
BOT_TESTNET_BUY_OCO_CONFIRMED=YES \
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.binance_testnet_smoke --mode buy-oco-journal-reload --symbol SOLUSDT
```

It verifies BUY fill, OCO legs, journal reload reconciliation, and cleanup. The
circuit-drill mode is isolated from production halt files.

### Optional bounded Mainnet acceptance canary

Run this only after Testnet, reconciliation, backup, and risk checks pass. The
tool is restricted to `SOLUSDT`, preserves the configured USDT reserve, refuses
an active bot/watchdog or existing SOL orders, and cannot exceed `10 USDT`.
It preflights the account commission schedule, defaults to a `0.02 USDT` total
commission budget with a hard `0.03 USDT` ceiling, and permits only one
successful drill per release. The immediate cleanup is an acceptance expense;
do not schedule or repeat it as a trading strategy.

**Never cancel a production OCO or remove protection to satisfy this
preflight.** Existing `SOLUSDT` orders make the account ineligible. Run the
canary on a flat account before enabling LIVE, or defer it until the managed
position closes and Binance, journal and balances have been reconciled by the
reviewed operator procedure. Reloading `OrderJournal` proves durable state; it
does not simulate SIGKILL or a new process.

```bash
(
cd /home/bot/apps/binance_bot
sudo systemctl stop mybot pi-watchdog-v3.timer pi-watchdog-v3.service

set +e
sudo -u bot env \
  BOT_LIVE_CONFIRMED=YES \
  BOT_MAINNET_CANARY_CONFIRMED=YES \
  BOT_MAINNET_CANARY_CLEANUP_CONFIRMED=YES \
  PYTHONPATH=. \
  .venv/bin/python -m bin.binance_mainnet_canary \
  --symbol SOLUSDT --notional-usdt 6 \
  --max-commission-usdt 0.02
RC=$?

if [ "$RC" -eq 0 ]; then
  sudo systemctl start mybot
  sudo systemctl start pi-watchdog-v3.timer
else
  echo "Canary failed; services remain stopped for manual review" >&2
fi
exit "$RC"
)
```

The lifecycle is `MARKET BUY -> exact journal reload -> verified OCO -> OCO
cancel -> MARKET SELL of acquired delta`. Any post-BUY uncertainty attempts
cleanup and creates a persistent halt. Do not reset that halt or start `mybot`
until Binance open orders and balances have been reviewed.

Production safety controls are stored in
`/var/lib/ladder-dragon/control/{circuit_halt.json,risk_state.json,risk_alerts.ndjson}`.
The installer and updater migrate an older `/run/mybot` control file before
stopping the service and block on conflicting evidence. Never delete these
files to make deployment pass; use the reviewed reset procedure only after
authoritative exchange reconciliation.

The installer also enables `ladder-dragon-user-stream-shadow.service`. It is a
read-only authenticated observer and remains active during execution HALT so
the 24-hour stream soak can accumulate without starting an order worker. Check
it independently:

```bash
systemctl is-active ladder-dragon-user-stream-shadow.service
PYTHONPATH=. .venv/bin/python -m bin.audit_user_stream_soak \
  /var/lib/ladder-dragon/user-stream/user_stream_SOLUSDT.json \
  --minimum-hours 24
```

Normal updates bootstrap the updater from the verified target commit before
creating a backup or stopping services. The target must be a signed
fast-forward contained in the configured upstream. This makes newly added
systemd/assets/migration steps effective on the first update invocation; the
running target copy remains immutable while Git fast-forwards the checkout.

Do not repeat this paid acceptance drill to create an artificial sample. Before
expanding beyond the minimal SOLUSDT canary, collect at least three naturally
completed and exactly linked `BUY fill -> OCO confirmed -> TP or STOP fill`
strategy lifecycles. Then keep the same one-symbol, one-BUY, `10 USDT` operator
ceiling configuration running for at least 24 hours (48 hours preferred). The
observation gate fails on any hard-CAP violation, unresolved fill, unprotected
managed position, persistent circuit halt, or reconciliation error. Legacy SOL
inventory is not part of this sample when automatic holdings protection is off.

The dashboard shows this gate as **Exact canary cycles**. You can also run the
isolated gap-watchdog drill without API keys, network access, fees, or exchange
orders:

```bash
cd /home/bot/apps/binance_bot
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.binance_testnet_smoke --mode gap-drill --symbol SOLUSDT
```

The drill proves that a breached OCO is not considered flattened after the
cancel request alone. The watchdog waits for the exact order-list IDs to
disappear and for their residual quantity to become free, then requires a
`FILLED` MARKET result covering that quantity. A timeout, partial result or
lost acknowledgement leaves a persistent HALT. The executor floors once to
`LOT_SIZE.stepSize`; it does not reserve an additional `minQty`.

## 8. Legacy holdings cost-basis import

This optional operation is for holdings acquired before Ladder Dragon began
recording exact FIFO lots. It does not place an order and does not enable
automatic holdings management. Do not use it while `mybot` is running.

Create a private directory and generate a preview plan:

```bash
cd /home/bot/apps/binance_bot
sudo systemctl stop mybot pi-watchdog-v3.timer pi-watchdog-v3.service
sudo install -d -o bot -g bot -m 0700 \
  /home/bot/.local/state/ladder-dragon

sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.import_legacy_cost_basis \
  --symbol SOLUSDT \
  --plan /home/bot/.local/state/ladder-dragon/SOLUSDT-cost-basis.json \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db
```

Preview never writes the trading database. Review the symbol, account and
managed quantities, weighted average, trade count, lot count, prehistory
quantity, unmanaged dust, history reset trade ID and plan SHA. A negative
historical inventory prefix may be seeded only by the exact quantity needed to
reach zero at a later SELL. That unpriced seed must be fully consumed before
the current FIFO position begins. Any remaining unexplained quantity is kept
outside managed lots and is accepted only when it is strictly smaller than the
exchange `LOT_SIZE.stepSize`; tradeable unexplained inventory fails closed.
The plan is mode `0600` and contains exchange provenance, so do not publish or
commit it.

Apply only after reviewing the preview and confirming that the service is still
stopped:

```bash
sudo -u bot env \
  BOT_COST_BASIS_IMPORT_CONFIRMED=YES \
  BOT_SERVICE_STOPPED_CONFIRMED=YES \
  BOT_RUN_DIR=/run/mybot \
  PYTHONPATH=. \
  .venv/bin/python -m bin.import_legacy_cost_basis \
  --symbol SOLUSDT \
  --plan /home/bot/.local/state/ladder-dragon/SOLUSDT-cost-basis.json \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db \
  --apply
```

Apply re-fetches the full account and fill history and requires the exact same
plan hash. Revalidation is mandatory inside the library mutation function, not
only in the CLI. It fails without changing the database if history is incomplete, a
commission cannot be valued at trade time, a transfer prevents quantity
reconciliation, the symbol has an open order, the account changed during or
after preview, or post-write verification fails. Existing open lots are retained
as `SUPERSEDED`. The JSON result contains `warnings`; a statistics trade-ID gap
is also stored in `inventory_lot_imports` and means reports do not have complete
historical trade rows for that exact range, even though the imported FIFO basis
includes those fills. Keep `mybot` stopped and
inspect the database/dashboard result before deciding whether holdings
management should be enabled.

### 8.1 Existing statistics database retirement

Fresh installations create exact-only accounting storage. An upgraded host
keeps its legacy REAL columns until all historical commission rows have exact
Binance provenance. Preview the repair first; it is read-only and exits with
status 2 if any `(symbol, trade_id)` cannot be proven:

```bash
sudo -u bot PYTHONPATH=. .venv/bin/python -m bin.revalue_legacy_commissions \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db
```

Apply only with the trading service stopped. The command creates its own
mode-0600 SQLite backup before the atomic database update:

```bash
sudo systemctl stop mybot pi-watchdog-v3.timer
sudo -u bot env \
  BOT_COMMISSION_REVALUATION_CONFIRMED=YES \
  BOT_SERVICE_STOPPED_CONFIRMED=YES \
  BOT_RUN_DIR=/run/mybot \
  PYTHONPATH=. \
  .venv/bin/python -m bin.revalue_legacy_commissions \
  --stats-db /home/bot/apps/binance_bot/db/bot_stats.db \
  --backup /var/lib/ladder-dragon/backups/bot_stats-before-fee-revalue.sqlite3 \
  --apply --confirm REVALUE-LEGACY-COMMISSIONS
```

Then follow the preview/apply accounting-retirement commands in the
[project README](../README.md#legacy-holdings-cost-basis). Normal updates never
drop physical columns from an existing database.

## 9. Normal updates

Always update a reviewed exact commit:

```bash
cd /home/bot/apps/binance_bot
RELEASE_SHA="<40-character-reviewed-SHA>"
sudo bash deploy/update_raspberry_pi.sh update "$RELEASE_SHA"
```

Updates are fail-closed and require a GPG-signed commit from the configured
maintainer fingerprint. A fresh 2.10.73-or-newer installation creates the
root-owned trust anchor automatically. On an existing host, install it once
before the first update with the hardened updater:

```bash
sudo install -d -o root -g root -m 0700 /etc/ladder-dragon
printf '%s\n' \
  'TRUSTED_GPG_FINGERPRINT=808B9F52CB6C08901703EF7C113144122F1830A0' |
  sudo tee /etc/ladder-dragon/update-trust.conf >/dev/null
sudo chown root:root /etc/ladder-dragon/update-trust.conf
sudo chmod 0600 /etc/ladder-dragon/update-trust.conf
sudo -u bot gpg --batch --import docs/release-signing-key.asc
```

The fingerprint cannot be supplied or disabled through the command environment.
The updater accepts only the root-owned configuration and verifies the exact
commit before merging it. Confirm the public key fingerprint through an
independent channel before the first installation. A repository clone, branch,
tag, or SHA alone is not a cryptographic trust root.

An unsigned emergency update requires a separate interactive and journaled
one-use authorization. Use it only when loss of the signing key makes a safety
fix impossible to deploy normally:

```bash
sudo bash deploy/update_raspberry_pi_break_glass.sh "$RELEASE_SHA"
sudo bash deploy/update_raspberry_pi.sh update "$RELEASE_SHA"
```

The authorization is bound to one exact SHA, stored under `/run`, consumed once,
and written to the authpriv journal. It is not a routine update switch.
The marker is consumed before the update attempt continues. If any later
merge, dependency or deployment step fails, the operator must create a new
exact-SHA authorization after diagnosing the failure; a failed attempt never
leaves reusable unsigned authority behind.

The default local dashboard certificate is self-signed, so the nginx template
intentionally does not send HSTS. For remote access, install a certificate from
a trusted private CA or use a private overlay such as Tailscale before enabling
HSTS; otherwise a certificate mistake can lock browsers out of `bot.local`.

The updater creates an encrypted backup, records service state, stops services,
applies only the requested fast-forward SHA, installs dependencies, updates
nginx/frontend/systemd, runs validation, starts services, and waits for a fresh
heartbeat plus an authenticated database-backed dashboard request. A transient
SQLite startup/schema race is reported as retryable HTTP 503, never HTTP 500,
and deployment is not declared ready until that request succeeds. It preserves
`.env`, `.env.dashboard`, venue, execution mode, symbols, and open orders.
Because configuration is preserved, newly documented risk controls must be
reviewed and added explicitly; the updater never expands or rewrites exposure
from `.env.example`.

If an update fails after fast-forward but before external runtime assets are
changed, recovery resets the clean tracked checkout to the recorded previous
SHA, reinstalls that release's hashed dependency lock and editable package, and
only then restores the previous service state. If rollback cannot be proved, or
systemd/nginx/static assets may already be partially changed, `mybot` and its
watchdog remain stopped. Recovery starts `pi-healthd` for diagnosis and prints
an explicit repair instruction. Exchange-hosted OCO protection remains active;
never start `mybot` manually until checkout, dependencies and deployment assets
have been reconciled as one release.

Database migration `007` adds the durable SELL FIFO-consumption journal before
services restart. It is idempotent and does not rewrite historical lots.
Repeated Binance SELL trade IDs are ignored only when their normalized
symbol/order/quantity/price payload matches exactly; a conflict or insufficient
FIFO inventory fails closed without partially changing any lot.

The migration runner owns one `BEGIN IMMEDIATE` transaction per migration.
Schema statements and their `schema_migrations` completion record commit
together; trigger bodies are parsed as complete SQLite statements rather than
through `executescript`. Duplicate numeric versions block startup before any
database mutation. A guarded recovery may skip an already present legacy
`ADD COLUMN` only when its type, nullability and default match exactly.
Fresh-database exact-accounting bootstrap and its completion marker also commit
in one transaction.

Copy the PASS release manifest generated for the same SHA to the Pi before the
post-deployment gate. Run this on the maintainer workstation:

```bash
scp .runtime/verification-release.json \
  bot@bot.local:/tmp/verification-release.json
```

Then install it owner-only and run the read-only Pi profile on the Pi:

```bash
sudo install -d -o bot -g bot -m 0700 /home/bot/verification
sudo install -o bot -g bot -m 0600 \
  /tmp/verification-release.json \
  /home/bot/verification/verification-release.json
rm -f /tmp/verification-release.json

sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.verification_harness --profile pi \
  --expected-sha "$RELEASE_SHA" \
  --github-sha "$RELEASE_SHA" \
  --release-report /home/bot/verification/verification-release.json \
  --runtime-status /run/mybot/ai_status.json \
  --user-stream-status /run/mybot/user_stream_SOLUSDT.json \
  --order-journal /home/bot/apps/binance_bot/db/order_intents.sqlite3 \
  --prediction-db /home/bot/apps/binance_bot/db/prediction_shadow.sqlite3 \
  --ai-decisions-db /home/bot/apps/binance_bot/db/ai_decisions.sqlite3
```

Exit `0` is `PASS`, `1` is `FAILED`, and `2` is safely `BLOCKED`. A deployment
may have matching SHA/assets, active services and healthy reconciliation while
the overall Pi approval profile remains `BLOCKED` because production evidence
is not mature. Attribution-only unresolved fills block RAG/approval but do not
block reconciled deterministic execution; any inventory/protection unresolved
fill blocks both. User-stream approval additionally requires 24 hours, a
reconnect, an order event and event-triggered authoritative REST
reconciliation. Production approval requires three exact closed lifecycles,
no prediction backlog and a passing statistical gate.

Use `apply` only when Git is already at the desired commit:

```bash
sudo bash deploy/update_raspberry_pi.sh apply
```

## 10. Backups and external storage

Encrypted application backups are stored in `/var/lib/ladder-dragon/backups`:

```bash
sudo systemctl start ladder-dragon-backup.service
sudo journalctl -u ladder-dragon-backup.service -n 50 --no-pager
sudo ls -lh /var/lib/ladder-dragon/backups
```

For an external disk, configure `/etc/ladder-dragon/backup.env`:

```dotenv
BACKUP_EXTERNAL_MOUNT=/mnt/usb1
BACKUP_EXTERNAL_DIR=/mnt/usb1/ladder-dragon-backups
BACKUP_EXTERNAL_RETENTION_DAYS=90
```

The service mirrors encrypted archives, checksums, and safe inventory files. It
fails rather than writing to an unmounted path. Mount the disk by UUID or label
in `/etc/fstab`, never by a transient `/dev/sda1` path.

`https://bot.local/backups/` exposes only encrypted archives, checksums, and safe
inventory through Basic Auth. Local/public retention is 14 days; external
retention follows `BACKUP_EXTERNAL_RETENTION_DAYS`.

### 10.1 Daily Telegram trading digest

The installer enables `ladder-dragon-daily-digest.timer`. At 08:00
`Asia/Almaty`, it opens the exact trade database with SQLite `mode=ro` and
reports yesterday, the last 7 complete days, and the last 30 complete days. The
systemd writable database mount exists only because a live WAL reader must
coordinate through SQLite's shared-memory sidecar.

```bash
sudo systemctl status ladder-dragon-daily-digest.timer --no-pager
sudo systemctl list-timers ladder-dragon-daily-digest.timer --no-pager
sudo journalctl -u ladder-dragon-daily-digest.service -n 50 --no-pager
```

Accounting is isolated by symbol. A symbol with incomplete FIFO history or an
unpriced commission appears under `Excluded symbols`; exact eligible-symbol
totals are still sent. The service never synthesizes a BUY or zero cost basis.
A report-build failure sends at most one figure-free `BLOCKED` warning per
local date. A failed service run is retried twice at five-minute intervals;
idempotency prevents a successful report from being sent twice.

Run a private preview only when terminal output is protected:

```bash
sudo -u bot env PYTHONPATH=/home/bot/apps/binance_bot \
  /home/bot/apps/binance_bot/.venv/bin/python \
  -m bin.daily_trading_digest --dry-run
```

See [Runtime safety and reporting](RUNTIME_SAFETY_AND_REPORTING.md) for the
protection, accounting, dashboard, and HALT/SHADOW contracts.

## 11. Sanitized logs and watchdog

```text
https://bot.local/logs/
https://bot.local/logs/current.log
https://bot.local/logs/status.json
```

The exporter runs every minute, retains seven days, limits files to 5 MiB, and
redacts authorization headers, API keys, secrets, tokens, and Binance signatures.
Raw journal APIs remain disabled.

The watchdog checks network access and fresh supervisor heartbeat. A first
failed probe is only an internal suspect state. It announces an incident and,
for heartbeat failures, restarts the service only after three consecutive
failed checks. A recovery message is sent only for an announced incident and
only after two consecutive successful checks. Network and heartbeat
notifications have independent deduplication state. Offline alerts are queued
in `/var/lib/pi-watchdog/telegram-outbox`, expire after 24 hours, and are
bounded to 288 files. Telegram credentials and message bodies are passed to
`curl` through file descriptors rather than process arguments. If no default
route exists, the watchdog reports that condition directly and never probes a
guessed gateway.

An operator stop must also remove automatic restart authority. Use:

```bash
sudo systemctl disable --now mybot
```

The watchdog treats an inactive, non-enabled unit as intentionally stopped and
does not alert or restart it. Resume explicitly with:

```bash
sudo systemctl enable --now mybot
```

A plain `systemctl stop mybot` leaves the unit enabled and is only a transient
stop; the watchdog may restart it after the configured strike threshold. For a
short coordinated maintenance window, stop the watchdog timer first or use the
project maintenance control.

## 12. Public depth archive and execution latency

The installer enables `ladder-dragon-depth-archive.timer`. It records public
SOLUSDT depth and aggregate trades for 15 minutes each hour and removes samples
older than seven days. It never receives trading credentials.

```bash
sudo systemctl status ladder-dragon-depth-archive.timer --no-pager
sudo systemctl start ladder-dragon-depth-archive.service
sudo journalctl -u ladder-dragon-depth-archive.service -n 50 --no-pager
sudo -u bot find /var/lib/ladder-dragon/depth-archives -maxdepth 1 \
  -type f -name '*.metadata.json' -print
```

Non-secret overrides may be placed in the root-owned
`/etc/ladder-dragon/depth-archive.conf`:

```dotenv
BOT_DEPTH_ARCHIVE_SYMBOLS=SOLUSDT
BOT_DEPTH_ARCHIVE_DURATION_SEC=840
BOT_DEPTH_ARCHIVE_RETENTION_DAYS=7
```

Keep the file root-owned and mode `0600`. The service still strips Binance and
AI credential variables before starting. The bot writes sanitized
`logs/execution_latency.ndjson` samples only for exact journal-linked order
events; calibration uses only `NEW/NEW` reports for acknowledgement latency.

## 13. Migration and troubleshooting

Audit or migrate an existing installation before changing it:

```bash
sudo bash deploy/install_raspberry_pi.sh audit
sudo bash deploy/install_raspberry_pi.sh migrate
```

Migration preserves project/systemd/nginx data, moves env and SQLite files,
disables legacy launchers, protects backups, and converts detected LIVE to DRY.
`--preserve-live` is allowed only after manual review and `BOT_LIVE_CONFIRMED=YES`.
After installing current replacements, migrate/update removes superseded
`ai-supervisor.service`, `binance-bot.service`, old `pi-dashboard` nginx paths,
and the migrated `/etc/bot-alerts.env`. `/opt/pi-dashboard` is quarantined below
`/var/lib/ladder-dragon/legacy` rather than silently deleted.

Do not remove SQLite REAL compatibility fields during an ordinary update. Run
the fleet/host audit first; exact-only migration is an explicit stopped-service
major-version operation documented in the README.

For GitHub `Permission denied (publickey)`, verify the deploy key and remote:

```bash
sudo -u bot ssh -T git@github.com
sudo -u bot git -C /home/bot/apps/binance_bot remote -v
```

For Binance `-2015` or `-2014`, verify Testnet/Mainnet, IP allow-list, API
permissions, and that the dashboard key is not used for trading.

For `bot.local` failures, check mDNS, nginx, TLS, and service status:

```bash
sudo systemctl status nginx mybot pi-healthd --no-pager
sudo nginx -t
```

Do not reset a persistent circuit halt until the account, open orders, ledger,
and position protection have been reconciled manually.
