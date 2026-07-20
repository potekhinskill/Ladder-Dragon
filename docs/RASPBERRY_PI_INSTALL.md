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
sudo systemctl stop mybot
sudo -u bot env PYTHONPATH=. .venv/bin/python -m pytest -q
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.binance_testnet_smoke --mode public --symbol SOLUSDT
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.binance_testnet_smoke --mode authenticated --symbol SOLUSDT
sudo systemctl start mybot
```

The optional lifecycle check uses a minimal isolated Testnet position:

```bash
BOT_TESTNET_BUY_OCO_CONFIRMED=YES \
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.binance_testnet_smoke --mode buy-oco-restart --symbol SOLUSDT
```

It verifies BUY fill, OCO legs, restart reconciliation, and cleanup. The
circuit-drill mode is isolated from production halt files.

### Optional bounded Mainnet acceptance canary

Run this only after Testnet, reconciliation, backup, and risk checks pass. The
tool is restricted to `SOLUSDT`, preserves the configured USDT reserve, refuses
an active bot/watchdog or existing SOL orders, and cannot exceed `10 USDT`.
It preflights the account commission schedule, defaults to a `0.02 USDT` total
commission budget with a hard `0.03 USDT` ceiling, and permits only one
successful drill per release. The immediate cleanup is an acceptance expense;
do not schedule or repeat it as a trading strategy.

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
plan hash. It fails without changing the database if history is incomplete, a
commission cannot be valued at trade time, a transfer prevents quantity
reconciliation, the symbol has an open order, the account changed during or
after preview, or post-write verification fails. Existing open lots are retained
as `SUPERSEDED`. Keep `mybot` stopped and
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

The default local dashboard certificate is self-signed, so the nginx template
intentionally does not send HSTS. For remote access, install a certificate from
a trusted private CA or use a private overlay such as Tailscale before enabling
HSTS; otherwise a certificate mistake can lock browsers out of `bot.local`.

The updater creates an encrypted backup, records service state, stops services,
applies only the requested fast-forward SHA, installs dependencies, updates
nginx/frontend/systemd, runs validation, starts services, and waits for a fresh
heartbeat. It preserves `.env`, `.env.dashboard`, venue, execution mode, symbols,
and open orders.

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

## 11. Sanitized logs and watchdog

```text
https://bot.local/logs/
https://bot.local/logs/current.log
https://bot.local/logs/status.json
```

The exporter runs every minute, retains seven days, limits files to 5 MiB, and
redacts authorization headers, API keys, secrets, tokens, and Binance signatures.
Raw journal APIs remain disabled.

The watchdog checks network access and fresh supervisor heartbeat. It restarts
the service only after three consecutive failed checks. Duplicate Telegram alerts
are suppressed, and offline alerts are queued in `/var/lib/pi-watchdog/telegram-outbox`.

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
