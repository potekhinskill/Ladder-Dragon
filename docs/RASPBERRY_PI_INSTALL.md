# Ladder Dragon Raspberry Pi installation and update runbook

This runbook targets Raspberry Pi OS Bookworm/Debian with `systemd`. The
canonical project directory is `/home/bot/apps/binance_bot`.

Fresh installation always starts in **Testnet DRY**. No real order is sent.

## 1. Prepare the host

Use a Raspberry Pi 4 or 5 with at least 4 GiB of RAM.
Use 64-bit Raspberry Pi OS Lite, reliable storage, stable power, SSH, and synchronized time.

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

The installer creates the Python environment and the required host services.
These services include nginx, FastAPI, fail2ban, zram, systemd, mDNS, TLS, backups, and the watchdog.
The installer does not put secrets in Git.
It starts `mybot` in Testnet DRY mode.

The [command reference](COMMAND_REFERENCE.md) lists each installed unit and timer.

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
BOT_EXPECTANCY_APPROVED=NO
BOT_MAKER_POLICY_MODE=SHADOW
BOT_MAKER_POLICY_APPROVED=NO
BOT_REGIME_GATE_MODE=SHADOW
BOT_REGIME_GATE_APPROVED=NO
BOT_INVENTORY_SKEW_MODE=SHADOW
BOT_INVENTORY_SKEW_APPROVED=NO
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
The bot and User Stream services receive this file through systemd.
Failed authentication alerts retry after one minute.
An IP change sends one transition notice without a fingerprint or source count.
Successful signed recovery sends one notice and keeps all independent risk gates unchanged.

Verify configuration without printing values:

```bash
sudo awk -F= '/^(TELEGRAM_ALERTS_ENABLED|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=/ {print $1 "=" (length($2) ? "<set>" : "<empty>")}' /etc/ladder-dragon/telegram.env
```

## 5. Select the execution mode

Systemd mode is stored separately in `.env.service`:

```dotenv
BOT_SERVICE_VENUE=testnet
BOT_SERVICE_EXECUTION=dry
BOT_SERVICE_SYMBOLS=SOLUSDT
BOT_PREDICTION_SHADOW_SYMBOLS=SOLUSDT,ETHUSDT,BTCUSDT
BOT_EXECUTION_CANDIDATE_SYMBOLS=BTCUSDT,ETHUSDT
BOT_MARKET_ANALYSIS_SYMBOLS=SOLUSDT,ETHUSDT,BTCUSDT
BOT_MARKET_ANALYSIS_TIMEFRAMES=1h,4h,1d,1w,1M
```

The dashboard reports each SHADOW symbol and generation separately.
The scenario service uses public closed candles only.
Its symbol list cannot start an execution worker.
The candidate list cannot start an execution worker.
Do not add a candidate to `BOT_SERVICE_SYMBOLS` before promotion passes.
Promotion requires `CONFIRMED`, two reviewed CAPs, and symbol approval.
SOLUSDT version sixteen supersedes versions eleven through fifteen.
ETHUSDT version fifteen supersedes versions eleven through fourteen.
BTCUSDT version fourteen supersedes versions eleven through thirteen.
BTCUSDT version twelve supersedes version eleven.
All superseded evidence remains append-only and visible.
SHADOW-only controls show `not_applicable_shadow_only` for execution-only limits.

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
The application accepts a client address only from the authenticated local nginx proxy.

Compare the installed configuration with the
[configuration reference](CONFIGURATION.md).
Review the [implementation status](IMPLEMENTATION_STATUS.md) before you change a mode.

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

`mybot.service` sends `SIGTERM` to the supervisor and each worker.
The supervisor changes the first signal to the normal `STOPPING` state.
It waits for worker exit and keeps bounded TERM and KILL timeouts.
The process manager counts repeated worker exits in a one-hour window.
The third nonzero exit starts exponential backoff.
The fifth exit sends one Telegram restart-storm alert.
Configure these defaults with
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

Run the controlled User Data Stream drill separately:

```bash
sudo -u bot env BOT_TESTNET_ORDER_CONFIRMED=YES PYTHONPATH=. \
  .venv/bin/python -m bin.binance_testnet_smoke \
  --mode user-stream-drill --symbol SOLUSDT
```

The drill forces one reconnect. It then creates and cancels one non-filling
Testnet LIMIT order. The authenticated event must wake a matching REST GET.

The drill does not change Mainnet, HALT, APPLY, or CAP.

### Optional bounded Mainnet acceptance canary

Run this only after Testnet, reconciliation, backup, and risk checks pass. The
tool is restricted to `SOLUSDT`, preserves the configured USDT reserve, refuses
an active bot/watchdog or existing SOL orders, and cannot exceed `10 USDT`.
It checks the account commission schedule before the test.
The default commission budget is `0.02 USDT`, with a hard `0.03 USDT` limit.
It permits only one successful test for each release.
The immediate cleanup is an acceptance expense;
do not schedule or repeat it as a trading strategy.

**Never cancel a production OCO or remove protection to satisfy this
preflight.** Existing `SOLUSDT` orders make the account ineligible. Run the
canary on a flat account before you enable LIVE.
Otherwise, wait until the managed position closes.
Then reconcile Binance, the journal, and balances with the reviewed procedure.
Reloading `OrderJournal` proves durable state; it
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
  --minimum-hours 24 \
  --maximum-transport-failure-reconnects-per-hour 1
```

The soak blocks when transport failures exceed one reconnect each hour.
Idle and controlled reconnects remain visible but do not indicate transport instability.

Readiness uses the current, versioned soak epoch.
The epoch starts from immutable lifetime-counter baselines.
Historical reconnects remain available as lifetime evidence.
The observer never resets or deletes lifetime counters.
Release 2.20.167 starts the `transport-stability-2026-08-v4` epoch.
This epoch starts after reconnect classification and watchdog recovery were corrected.
The v1, v2, and v3 epochs remain in the same sanitized snapshot.
Release 2.20.203 starts the `transport-stability-2026-08-v5` epoch.
This epoch starts after correction of the authorization and host clock incident.
The v1 through v4 epochs remain in the same sanitized snapshot.
Release 2.20.231 starts the `transport-stability-2026-08-v6` epoch.
This epoch starts after Wi-Fi recovery and successful signed REST authentication.
The v1 through v5 epochs remain in the same sanitized snapshot.
The snapshot retains up to 64 append-only epoch baselines.
The observer blocks a new epoch when this limit is full.
The operator must review and archive evidence before any manual migration.
No automatic epoch deletion is permitted.

The current epoch requires 24 hours of continuous observation.
It also requires a controlled reconnect, one order event, and event-triggered REST reconciliation.
Run the controlled drills only after the new epoch starts.

Request one controlled reconnect without restarting the service:

```bash
sudo systemctl kill --kill-who=main --signal=SIGUSR1 \
  ladder-dragon-user-stream-shadow.service
```

Wait until the stream reconnects. Then run the soak audit again.

Run the Mainnet event drill only with a persistent HALT and SHADOW mode.
The drill submits one bounded `LIMIT_MAKER` BUY below the market.
It cancels the order immediately and requires zero execution.
It then requires an account event and authoritative REST reconciliation.
Do not remove an OCO or another open order for this drill.

```bash
sudo -u bot env \
  BOT_LIVE_CONFIRMED=YES \
  BOT_MAINNET_USER_STREAM_DRILL_CONFIRMED=YES \
  BOT_MAINNET_USER_STREAM_DRILL_CLEANUP_CONFIRMED=YES \
  PYTHONPATH=. \
  .venv/bin/python -m bin.mainnet_user_stream_drill \
  --symbol SOLUSDT --notional-usdt 6
```

The drill uses a separate authoritative journal.
Do not delete this journal or its report.
An unexpected fill triggers immediate cleanup and preserves HALT.
Review Binance balances, open orders, and both journals after any failure.

WARNING: The LIMIT_MAKER validation drill creates a real Mainnet fill.
Run it only after separate approval for one 6 USDT attempt.
Keep the persistent HALT active during the complete procedure.

```bash
sudo -u bot env \
  BOT_LIVE_CONFIRMED=YES \
  BOT_MAINNET_LIMIT_MAKER_VALIDATION_CONFIRMED=YES \
  BOT_MAINNET_LIMIT_MAKER_VALIDATION_CLEANUP_CONFIRMED=YES \
  PYTHONPATH=. \
  .venv/bin/python -m bin.mainnet_limit_maker_validation \
  --symbol SOLUSDT --notional-usdt 6 --wait-sec 90
```

The drill posts at the highest non-crossing tick.
It cancels the remainder after the first fill or the wait limit.
It sells only the acquired SOL quantity with a MARKET cleanup order.
Without a batch manifest, the command permits one exchange attempt for each release.
A no-fill result uses exit code 2 and still consumes the attempt.
Any uncertain cleanup preserves HALT and uses exit code 1.

WARNING: The STOP_LOSS_LIMIT validation drill creates real Mainnet orders.
Run it only after separate approval for one 6 USDT attempt.
Keep the persistent HALT active during the complete procedure.

```bash
sudo -u bot env \
  BOT_LIVE_CONFIRMED=YES \
  BOT_MAINNET_STOP_LIMIT_VALIDATION_CONFIRMED=YES \
  BOT_MAINNET_STOP_LIMIT_VALIDATION_CLEANUP_CONFIRMED=YES \
  PYTHONPATH=. \
  .venv/bin/python -m bin.mainnet_stop_limit_validation \
  --symbol SOLUSDT --notional-usdt 6 --wait-sec 300
```

The drill buys exactly 6 USDT before it arms one OCO.
The fixed STOP trigger is 10 basis points below the reference price.
The STOP limit is 5 basis points below the trigger.
The take-profit leg is 5 percent above the reference price.
The drill cancels both legs after the wait limit.
It sells only its remaining acquired SOL quantity.
Without a batch manifest, the command permits one exchange attempt for each release.
A missing STOP fill uses exit code 2 and still consumes the attempt.
Any uncertain cleanup preserves HALT and uses exit code 1.

Each validation drill starts a contiguous public archive before POST.
It closes that archive only after terminal reconciliation and cleanup.
The store accepts at most 32 archives or 512 MiB.
Capacity exhaustion blocks another drill and never deletes evidence.

Create a bounded batch only after separate operator approval.
This command does not place an order:

```bash
sudo -u bot PYTHONPATH=. .venv/bin/python -m bin.mainnet_validation_batch \
  --manifest logs/mainnet-validation-batch.json \
  --symbol SOLUSDT --maximum-attempts 4 \
  --maximum-turnover-usdt 48 --duration-hours 24 \
  --limit-maker-attempts 2 --stop-limit-attempts 2 \
  --minimum-cooldown-sec 300 \
  --confirm CREATE_VALIDATION_BATCH
```

Add `--batch-manifest logs/mainnet-validation-batch.json` to an approved drill.
Each drill still requires its existing Mainnet environment confirmations.
Each reservation consumes one attempt and twice the requested notional.
A crash after reservation cannot restore that attempt.
The batch stops at its attempt, turnover, release, or time limit.
The append-only ledger uses a hash chain.
Separate drill quotas prevent adaptive reallocation after outcomes are visible.
Do not delete its manifest or append-only attempt ledger.

The separate SQLite journal is authoritative order evidence.
The report and sanitized execution log are derived replay evidence.
The maker journal grows by at most two intents for each attempted release.
The STOP journal grows by at most three intents for each attempted release.
The report grows by at most three bounded rows for each attempted release.
Do not delete these records before a verified encrypted backup and promotion audit.
The normal evidence archive policy controls later retention.

The monthly prediction timer creates offline evidence.
It does not authorize APPLY or remove HALT.

```bash
systemctl list-timers ladder-dragon-monthly-prediction.timer --no-pager
journalctl -u ladder-dragon-monthly-prediction.service -n 50 --no-pager
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

The test proves that an OCO cancel request does not prove a position exit.
The watchdog waits until the exact order-list identifiers disappear.
It also waits until the residual quantity becomes free.
It then requires a `FILLED` MARKET result for that quantity.
A timeout, partial result or
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
the current FIFO position begins.
The importer keeps all remaining unexplained quantity outside managed lots.
It accepts this quantity only when it is less than `LOT_SIZE.stepSize`.
Tradeable unexplained inventory fails closed.
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

Apply reads the full account and fill history again.
It requires the same plan hash.
The library mutation function must revalidate the plan.
It fails without a database change for these conditions:

- history is incomplete;
- a commission has no trade-time value;
- a transfer prevents quantity reconciliation;
- the symbol has an open order;
- the account changed during or after preview;
- the post-write verification failed.

Existing open lots remain as `SUPERSEDED`.
The JSON result contains `warnings`.
A statistics trade-ID gap is also stored in `inventory_lot_imports`.
The gap means that reports do not contain complete trade rows for that range.
The imported FIFO basis still includes those fills.
Keep `mybot` stopped and
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
The marker is consumed before the update attempt continues.
If a later update step fails, diagnose the failure.
The operator must create a new exact-SHA authorization.
A failed attempt does not leave reusable unsigned authority.

The default local dashboard certificate is self-signed.
Thus, the nginx template does not send HTTP Strict Transport Security (HSTS).
For remote access, install a certificate from a trusted private certificate authority.
You can use a private overlay before you enable HSTS.

The updater creates an encrypted backup and records the service state.
It stops services and applies only the requested fast-forward SHA.
It installs dependencies and updates nginx, frontend assets, and systemd.
It validates and starts the services.
It then waits for a fresh heartbeat and an authenticated dashboard response.
It removes the obsolete `wlan0` packet-idle check from the hardware watchdog.
The managed host watchdog continues to test the route, Internet, and heartbeat.
A transient
SQLite startup/schema race is reported as retryable HTTP 503, never HTTP 500,
and deployment is not declared ready until that request succeeds. It preserves
`.env`, `.env.dashboard`, venue, execution mode, symbols, and open orders.
Because configuration is preserved, newly documented risk controls must be
reviewed and added explicitly; the updater never expands or rewrites exposure
from `.env.example`.

If an update fails before an asset change, recovery restores the previous SHA.
Recovery installs the previous hashed dependencies and package.
It then restores the previous service state.
If rollback cannot be proved, or
systemd/nginx/static assets may already be partially changed, `mybot` and its
watchdog remain stopped. Recovery starts `pi-healthd` for diagnosis and prints
an explicit repair instruction. Exchange-hosted OCO protection remains active;
never start `mybot` manually until checkout, dependencies and deployment assets
have been reconciled as one release.

Database migration `007` adds the durable SELL FIFO-consumption journal before
services restart. It is idempotent and does not rewrite historical lots.
A repeated Binance SELL trade ID is idempotent only when its normalized payload matches.
A conflict or insufficient FIFO inventory fails closed.
The failed operation does not partially change a lot.

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
  --user-stream-status /var/lib/ladder-dragon/user-stream/user_stream_SOLUSDT.json \
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
no overdue outcomes or expirations created during the audited soak window, and
a passing statistical gate. Older expirations remain visible as lifetime
evidence without invalidating a later clean run.

Review a historical attribution gap only after the journal proves each order.
The command does not create an AI decision link.

Run the preview first:

```bash
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  -m bin.review_unattributed_fills \
  --ai-db db/ai_decisions.sqlite3 \
  --journal db/order_intents.sqlite3 \
  --note historical_canary_without_decision_link \
  --before-ts <REVIEW_CUTOFF_EPOCH> \
  --expected-count <REVIEWED_COUNT>
```

Confirm the exact candidate count. Then run the same command with `--apply`.
Set `BOT_UNATTRIBUTED_REVIEW_CONFIRMED=YES` only for the apply command.

The command keeps each raw row as `REVIEWED_UNATTRIBUTABLE`.
It does not remove HALT or permit APPLY.

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

The service verifies each encrypted copy before atomic publication.
Status identifies the completed archive by name, size, and SHA-256.
The dashboard reports `unknown` when this evidence is missing or inconsistent.

`https://bot.local/backups/` exposes only encrypted archives, checksums, and safe
inventory through Basic Auth. Local/public retention is 14 days; external
retention follows `BACKUP_EXTERNAL_RETENTION_DAYS`. External rotation runs before
each mirror operation. Rotation keeps the newest encrypted archive until its
verified replacement exists.

Local and public rotation runs before collection and after publication.
It preserves the newest completed encrypted archive.
Staging directories older than sixty minutes are removed before collection.
The cleanup accepts only the timestamp grammar created by the backup script.
Other directories remain unchanged and require separate operator review.

### 10.1 Daily Telegram trading digest

The installer enables `ladder-dragon-daily-digest.timer`.
At 08:00 `Asia/Almaty`, the service opens the exact trade database in read-only mode.
It reports yesterday and the last 7 and 30 complete days.
The
systemd writable database mount exists only because a live WAL reader must
coordinate through SQLite's shared-memory sidecar.

The dashboard uses the same SQLite coordination rule.
Its application connections use `mode=ro` and `PRAGMA query_only=ON`.
The dashboard continues to update healthy sections when one source is unavailable.

After readiness passes, the updater replaces one derived deployment status file.
The file is `/var/lib/ladder-dragon/deployment-status.json`.
It has a 4 KiB limit and contains no account or network address data.
It has no archive dependency.
It needs no cleanup because each successful update replaces it.
The dashboard shows one short action when the heartbeat is `IP_BLOCKED`.
The updater sends the same short action in English through Telegram.
IP Guard checks a changed fingerprint with two independent HTTPS sources.
It accepts the fingerprint after the complete signed read-only Binance preflight passes.
Failed authentication keeps BUY blocked and does not remove HALT.
The supervisor retries a changed-IP rejection each minute.
It recovers automatically after Binance accepts the signed read.
Telegram sends one change notice and one recovery notice for that incident.
Code `-2015` can also mean an invalid key or insufficient permissions.

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

### Automatic network recovery

The network recovery check runs each minute. Bot heartbeat checks retain their five-minute interval.
A reachable default gateway or independent Internet probe prevents disruptive recovery.
An isolated Binance, Telegram, or Internet-provider failure does not authorize reboot when the gateway remains reachable.
Probes do not depend on domain-name resolution.

After three continuous failure minutes, recovery activates an existing connection on `wlan0`.
After eight minutes, recovery restarts NetworkManager once.
After fifteen minutes, recovery requests one normal reboot with shutdown-inhibitor checks enabled.
Timer scheduling and bounded probes can add approximately one minute to these thresholds.
This is not a power cycle. A hardware fault can still require physical intervention.

Recovery cannot modify Wi-Fi passwords, candidate parameters, trading state, or HALT.
Disabled Wi-Fi or networking suppresses recovery.
Active maintenance, unavailable safety checks, and corrupt recovery state suppress all recovery actions.
The updater and encrypted backup hold a shared lock throughout their complete operations.
Recovery needs its exclusive lock before any network mutation.
A pending reboot prevents new guarded backups or updates during that boot.
An active legacy SD-backup service or timer also suppresses recovery.
Stop that timer before enabling automatic recovery; do not interrupt an active image backup.
Do not start an unguarded manual SD image while network recovery is enabled.

Only one reboot request is allowed per incident.
Another request requires thirty continuous healthy minutes and at least twenty-four hours since the previous request.
Clock rollback cannot shorten this limit. Timer gaps restart the continuous observation window.

Telegram receives loss, recovery-action, deferred-action, reboot-request, boot-observed, and restored-network messages.
Messages enter the existing persistent outbox before recovery actions.
An offline message cannot arrive until Telegram becomes reachable.
Every watchdog invocation retries queued delivery independently of Binance health.
HTTP delivery errors preserve the queued message and never print the Telegram token.

`/var/lib/pi-watchdog/network-recovery.json` is authoritative recovery control, not trading evidence.
It contains one bounded record below 4 KiB, without credentials or market data.
`network-reboot.boot` is a single authoritative boot marker.
Both files persist across boots and enter the encrypted host backup.
They are not age-pruned because deletion could restore consumed reboot authority.
The zero-byte shared lock is disposable coordination state and must not be replaced during active operations.
Telegram messages remain derived records with the existing 288-file and twenty-four-hour retention limits.
The timer maintains these limits; no additional archive is required for alert deletion.

Inspect sanitized recovery state without exposing environment files:

```bash
sudo cat /var/lib/pi-watchdog/network-recovery.json
sudo systemctl status pi-watchdog-v3.timer --no-pager
```

Use a root-owned service override to disable network mutations without stopping heartbeat monitoring:

```ini
[Service]
Environment=WATCHDOG_NETWORK_RECOVERY=0
```

An unresolved bot-health incident sends another alert after the configured
cooldown. Each confirmed failure series can still restart the enabled service.

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

The installer enables the continuous `ladder-dragon-depth-archive.service`.
It records public SOLUSDT depth and aggregate trades through one continuous connection.
File rotation carries the verified book into a hash-linked segment.
A separate child calibrates completed segments with the fixed replay policy.
The directory byte limit stops capture instead of deleting protected source evidence.
It never receives trading credentials.

The recorder starts evidence only after it proves depth sequence continuity.
Each segment has bounded events, bytes, and book levels.
Prediction backfill rejects aggregate trades with decreasing timestamps.
Do not concatenate separate connection sessions.
The historical reader joins only verified, hash-linked segments of the same session.
See [Historical entry replay](HISTORICAL_ENTRY_REPLAY.md) for source retention and selection requirements.

```bash
sudo systemctl status ladder-dragon-depth-archive.service --no-pager
sudo systemctl start ladder-dragon-depth-archive.service
sudo journalctl -u ladder-dragon-depth-archive.service -n 50 --no-pager
sudo -u bot find /var/lib/ladder-dragon/depth-archives -maxdepth 1 \
  -type f \( -name '*.metadata.json' -o -name '*.calibration.json' \) -print
```

Non-secret overrides may be placed in the root-owned
`/etc/ladder-dragon/depth-archive.conf`:

```dotenv
BOT_DEPTH_ARCHIVE_SYMBOLS=SOLUSDT
BOT_DEPTH_ARCHIVE_DURATION_SEC=840
BOT_DEPTH_ARCHIVE_CAPACITY_BYTES=8589934592
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

If the journal contains a removed symbol, keep HALT active.

1. Stop the bot service.
2. Add the exact symbol to the reviewed configuration.
3. Start the bot and let startup recovery reconcile the intent.
4. Verify the exchange order and journal state.
5. Remove the symbol only after the intent reaches a terminal state.

Do not edit the SQLite journal manually. Keep the bot stopped if recovery
cannot prove the terminal exchange state.
