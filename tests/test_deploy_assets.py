from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text()


def test_production_code_has_copyright_and_russian_maintenance_note():
    paths = list(ROOT.glob("*.py"))
    paths += list((ROOT / "deploy").glob("*.py"))
    paths += list((ROOT / "deploy").glob("*.sh"))
    paths += list((ROOT / "deploy").glob("*.service"))
    paths += list((ROOT / "deploy").glob("*.timer"))
    paths += list((ROOT / "FRONT").glob("*.html"))
    paths += [ROOT / "FastAPI/pi-dashboard/app.py"]
    for path in paths:
        source = path.read_text()
        assert "Copyright (c) 2026 IURII Potekhin / Ladder Dragon" in source
        assert "Назначение" in source or "назначение" in source


def test_nginx_requires_auth_and_publishes_only_encrypted_backups():
    site = read("deploy/nginx/bot.local.conf")
    snippet = read("deploy/nginx/pi_api.conf")
    assert 'auth_basic "Ladder Dragon"' in site
    assert "auth_basic_user_file" in site
    assert "location ^~ /backups/" in site
    assert "alias /var/lib/ladder-dragon/backups-public/;" in site
    backup_location = site.split("location ^~ /backups/", 1)[1].split("}", 1)[0]
    assert "autoindex on" in backup_location
    assert "autoindex_localtime on" in backup_location
    assert "Cache-Control \"no-store\"" in backup_location
    assert "X-Authenticated-User $remote_user" in snippet
    assert "ladder_dragon_proxy_secret.conf" in site
    assert "location /logs/" in site
    assert "alias /var/lib/ladder-dragon/logs/" in site
    assert "autoindex on" in site
    assert "autoindex_localtime on" in site
    assert "charset utf-8;" in site
    assert "location = /CHANGELOG.md" in site
    assert 'default_type text/plain;' in site
    assert 'Content-Disposition "inline"' in site


def test_dashboard_publishes_version_and_changelog():
    index = read("FRONT/index.html")
    app = read("FastAPI/pi-dashboard/app.py")
    installer = read("deploy/install_raspberry_pi.sh")
    updater = read("deploy/update_raspberry_pi.sh")
    assert 'id="product-version"' in index
    assert 'id="changelog-link"' in index
    assert '"changelog_url": "/CHANGELOG.md"' in app
    assert '"product": {"name": PRODUCT_NAME, "version": __version__}' in app
    assert '"${PROJECT_DIR}/CHANGELOG.md" /var/www/bot/' in installer
    assert 'FRONT/index.html FRONT/help.html CHANGELOG.md' in updater


def test_dashboard_publishes_read_only_account_balances():
    index = read("FRONT/index.html")
    app = read("FastAPI/pi-dashboard/app.py")
    assert 'id="balance-body"' in index
    assert 'getJSON(\'/api/account/balances\')' in index
    assert '@app.get("/api/account/balances")' in app
    assert '"valuation_status": "priced"' in app
    assert 'dashboard API credentials are read-only by design' in app


def test_dashboard_publishes_read_only_open_orders():
    index = read("FRONT/index.html")
    app = read("FastAPI/pi-dashboard/app.py")
    assert 'id="open-orders-body"' in index
    assert "getJSON('/api/account/open-orders')" in index
    assert '@app.get("/api/account/open-orders")' in app
    assert '"client_order_id"' in app
    assert '"remaining_qty"' in app
    assert 'open orders snapshot failed' in app


def test_dashboard_balance_filter_hides_small_assets_by_default():
    index = read("FRONT/index.html")
    assert 'id="balance-hide-small"' in index
    assert 'type="checkbox" checked' in index
    assert 'скрывать &lt; 1 USDT' in index
    assert "localStorage.getItem('balance-hide-small')" in index
    assert "row.value_usdt == null || Number(row.value_usdt) < 1" in index
    assert 'id="balance-hidden"' in index


def test_dashboard_switches_use_binance_style_visual_state():
    index = read("FRONT/index.html")
    assert index.count('class="switch-visual"') >= 2
    assert 'aria-pressed="false"' in index
    assert ".switch-visual.on" in index
    assert ".switch-label input:checked + .switch-visual" in index
    assert ".ai-toggle:focus-visible .switch-visual" in index


def test_dashboard_charts_have_bounded_responsive_containers():
    index = read("FRONT/index.html")
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in index
    assert ".grid-charts>.card{min-width:0" in index
    assert ".chart-frame{position:relative" in index
    assert "maintainAspectRatio:false" in index
    assert '<div class="chart-frame"><canvas id="chartTemp"></canvas></div>' in index


def test_shadow_ai_defaults_limit_cost_and_duplicate_requests():
    example = read(".env.example")
    config = read("supervisor_config.py")
    dashboard = read("FastAPI/pi-dashboard/app.py")
    dashboard_env = read(".env.dashboard.example")
    changelog = read("CHANGELOG.md")
    assert "AI_CACHE_SEC=900" in example
    assert "AI_DAILY_COST_LIMIT_USD=0.50" in example
    assert "AI_DAILY_TOKEN_LIMIT=500000" in example
    assert "AI_MAX_REQUESTS_PER_DAY=400" in example
    assert 'os.getenv("AI_CACHE_SEC", "900")' in config
    assert 'os.getenv("AI_DAILY_COST_LIMIT_USD", "0.50")' in config
    assert 'os.getenv("AI_DAILY_COST_LIMIT_USD", "0.50")' in dashboard
    assert "AI_DAILY_COST_LIMIT_USD=0.50" in dashboard_env
    assert 'os.getenv("AI_DAILY_TOKEN_LIMIT", "500000")' in config
    assert 'AI_DAILY_TOKEN_LIMIT=500000' in dashboard_env
    assert 'os.getenv("AI_DAILY_TOKEN_LIMIT", "500000")' in dashboard
    assert 'os.getenv("AI_MAX_REQUESTS_PER_DAY", "400")' in config
    assert "AI_RAG_INCLUDE_VIRTUAL=1" in example
    assert "## [2.10.10]" in changelog


def test_dashboard_ai_toggle_is_advisory_only():
    index = read("FRONT/index.html")
    app = read("FastAPI/pi-dashboard/app.py")
    supervisor = read("ai_supervisor.py")
    assert 'id="ai-toggle"' in index
    assert "POST'," in index and "/api/ai/control" in index
    assert '@app.post("/api/ai/control")' in app
    assert "AI advisor is not configured" in app
    assert "_stop_children(\"AI disabled from dashboard\")" in supervisor


def test_managed_service_uses_versionless_wrapper_and_separate_env():
    unit = read("deploy/mybot.service")
    wrapper = read("deploy/run_bot_service.sh")
    assert "EnvironmentFile=/home/bot/apps/binance_bot/.env.service" in unit
    assert "deploy/run_bot_service.sh" in unit
    assert "autosize_universal.py" in wrapper
    assert "1.8_autosize" not in unit + wrapper
    assert "--risk-level" not in unit + wrapper
    assert "--copy-top-bots" not in unit + wrapper
    assert 'BOT_SERVICE_EXECUTION:-dry' in wrapper
    assert 'BOT_SERVICE_VENUE:-testnet' in wrapper
    assert 'BOT_LIVE_CONFIRMED:-NO' in wrapper


def test_executor_status_does_not_hide_oco_state_behind_question_mark():
    executor = read("autosize_universal.py")
    assert "OCO:?" not in executor
    assert 'protection_state = "not_checked"' in executor


def test_supervisor_control_logs_stay_inside_writable_rotated_directory():
    ctl = read("supervisor_ctl.sh")
    unit = read("deploy/mybot.service")
    assert 'SUPERVISOR_LOG:-${SCRIPT_DIR}/logs/supervisor.log' in ctl
    assert 'PNL_LOG_PATH:-${SCRIPT_DIR}/logs/pnl.log' in ctl
    assert "ReadWritePaths=/home/bot/apps/binance_bot/db /home/bot/apps/binance_bot/logs /run/mybot" in unit
    assert 'LOG="supervisor.log"' not in ctl


def test_installer_migrates_sqlite_safely_and_closes_legacy_backups():
    installer = read("deploy/install_raspberry_pi.sh")
    backup = read("deploy/backup_raspberry_pi.sh")
    assert "src.backup(out)" in installer
    assert "src.backup(out" in backup
    assert "db-wal" not in backup
    assert "legacy-public-" in installer
    assert "backups-public" in installer
    assert "/etc/bot-alerts.env" in backup
    assert "pi-watchdog_v3.sh" in backup
    assert "disable --now make-pi-backup.timer" in installer
    assert "/opt/pi-dashboard" in installer
    assert "DASHBOARD_TRUST_PROXY_AUTH=1" in installer
    assert "DASHBOARD_PROXY_AUTH_SECRET" in installer
    assert "openssl rand -hex 32" in installer
    assert "--preserve-live" in installer
    assert "--commit" in installer
    assert 'service_execution="dry"' in installer
    assert "rollback_install" in installer


def test_portable_system_tuning_avoids_copying_legacy_firewall_rules():
    installer = read("deploy/install_raspberry_pi.sh")
    journald = read("deploy/system/journald-ladder-dragon.conf")
    fail2ban = read("deploy/system/fail2ban-sshd.local")
    assert "RuntimeMaxUse=50M" in journald
    assert "[sshd]" in fail2ban
    assert "/etc/ufw/user.rules" not in installer
    assert "tmp.mount" not in installer


def test_raspberry_runbook_covers_install_update_and_private_github():
    runbook = read("docs/RASPBERRY_PI_INSTALL.md")
    assert "Deploy Key" in runbook
    assert "git@github.com:potekhinskill/Ladder-Dragon.git" in runbook
    assert "install_raspberry_pi.sh install" in runbook
    assert "update_raspberry_pi.sh update" in runbook
    assert "BOT_SERVICE_EXECUTION=dry" in runbook
    assert "BOT_LIVE_CONFIRMED=YES" in runbook
    assert "/var/lib/ladder-dragon/backups" in runbook
    assert "https://bot.local/logs/current.log" in runbook


def test_log_export_is_rotated_sanitized_and_managed_by_systemd():
    exporter = read("deploy/export_sanitized_logs.py")
    service = read("deploy/ladder-dragon-log-export.service")
    timer = read("deploy/ladder-dragon-log-export.timer")
    installer = read("deploy/install_raspberry_pi.sh")
    assert "journalctl" in exporter
    assert "RETENTION_DAYS" in exporter
    assert "MAX_BYTES" in exporter
    assert "<redacted>" in exporter
    assert "OnUnitActiveSec=1m" in timer
    assert "User=root" in service
    assert "Group=www-data" in service
    assert "ladder-dragon-log-export.timer" in installer
    assert "expected protected logs HTTP 401" in installer


def test_updates_are_commit_allowlisted_and_backups_are_encrypted():
    updater = read("deploy/update_raspberry_pi.sh")
    installer = read("deploy/install_raspberry_pi.sh")
    backup = read("deploy/backup_raspberry_pi.sh")
    backup_unit = read("deploy/ladder-dragon-backup.service")
    assert "update requires an exact 40-character commit SHA" in updater
    assert "git pull" not in updater
    assert "merge-base --is-ancestor" in updater
    assert "git verify-commit" in updater
    assert "--commit with an exact 40-character Git SHA is required" in installer
    assert "age -r" in backup
    assert ".tgz.age" in backup
    assert "EnvironmentFile=/etc/ladder-dragon/backup.env" in backup_unit
    assert "backups-public" in backup_unit
    assert "ReadWritePaths=/var/lib/ladder-dragon" in backup_unit
    assert "ReadWritePaths=/var/lib/ladder-dragon /mnt" not in backup_unit
    assert "BACKUP_EXTERNAL_MOUNT" in backup
    assert "external backup disk is not mounted" in backup
    assert "mounted read-only" in backup
    assert "trap cleanup_staging EXIT" in backup
    assert "exFAT не поддерживает chmod" in backup
    assert "ReadWritePaths=%s" in updater
    assert "BindReadWritePaths" not in installer + updater
    assert "RequiresMountsFor" in updater
    assert "external-mount.conf" in installer


def test_backup_service_allows_only_sqlite_directory_for_wal_sidecars():
    service = read("deploy/ladder-dragon-backup.service")
    backup = read("deploy/backup_raspberry_pi.sh")
    assert "ReadOnlyPaths=/home/bot/apps/binance_bot" not in service
    assert "ReadWritePaths=/var/lib/ladder-dragon /home/bot/apps/binance_bot/db" in service
    assert "temporary = target.with_name" in backup
    assert "os.replace(temporary, target)" in backup
    assert "SQLite online backup failed for {source.name}" in backup


def test_backup_reconciles_all_archives_and_verifies_destination_checksums():
    backup = read("deploy/backup_raspberry_pi.sh")
    assert 'shopt -s nullglob' in backup
    assert "mirror_external_archive" in backup
    assert "publish_public_archive" in backup
    assert 'for source_archive in "${BACKUP_DIR}"/*.tgz.age' in backup
    assert 'sha256sum -c "${name}.sha256"' in backup
    assert 'cp --preserve=timestamps -f "${source_archive}"' in backup
    assert "preinstall-*.tgz.age*" in backup
    assert 'publish_public_archive "${source_archive}"' in backup
    assert "BACKUP_EXTERNAL_RETENTION_DAYS" in backup


def test_watchdog_uses_current_heartbeat_and_not_legacy_runner_name():
    watchdog = read("deploy/pi-watchdog_v3.sh")
    service = read("deploy/pi-watchdog-v3.service")
    installer = read("deploy/install_raspberry_pi.sh")
    updater = read("deploy/update_raspberry_pi.sh")
    assert "ai_status.json" in watchdog
    assert "autosize_universal.py" not in watchdog
    assert "1.8_autosize_universal.py" not in watchdog
    assert "STRIKES" in watchdog
    assert "systemctl restart mybot.service" in watchdog
    assert "|| true'" not in service
    assert "pi-watchdog_v3.sh" in installer
    assert "pi-watchdog_v3.sh" in updater


def test_systemd_units_have_extended_sandboxing():
    for relative in (
        "deploy/mybot.service",
        "deploy/pi-dashboard.service",
        "deploy/ladder-dragon-backup.service",
        "deploy/ladder-dragon-log-export.service",
    ):
        unit = read(relative)
        assert "ProtectKernelTunables=yes" in unit
        assert "ProtectKernelModules=yes" in unit
        assert "ProtectControlGroups=yes" in unit
        assert "RestrictSUIDSGID=yes" in unit
        assert "LockPersonality=yes" in unit
