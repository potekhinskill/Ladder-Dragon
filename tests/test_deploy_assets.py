from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text()


def test_nginx_requires_auth_and_never_publishes_backups():
    site = read("deploy/nginx/bot.local.conf")
    snippet = read("deploy/nginx/pi_api.conf")
    assert 'auth_basic "Ladder Dragon"' in site
    assert "auth_basic_user_file" in site
    assert "location ^~ /backups/" in site
    assert "return 404;" in site
    assert "autoindex on" not in site
    assert "X-Authenticated-User $remote_user" in snippet


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


def test_installer_migrates_sqlite_safely_and_closes_legacy_backups():
    installer = read("deploy/install_raspberry_pi.sh")
    backup = read("deploy/backup_raspberry_pi.sh")
    assert "src.backup(out)" in installer
    assert "src.backup(out)" in backup
    assert "db-wal" not in backup
    assert "legacy-public-" in installer
    assert "disable --now make-pi-backup.timer" in installer
    assert "/opt/pi-dashboard" in installer
    assert "DASHBOARD_ENABLE_LOGS=0" in installer
    assert "DASHBOARD_TRUST_PROXY_AUTH=1" in installer
    assert "--preserve-live" in installer
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
    assert "git@github.com:potekhinskill/binance_bot.git" in runbook
    assert "install_raspberry_pi.sh install" in runbook
    assert "update_raspberry_pi.sh update" in runbook
    assert "BOT_SERVICE_EXECUTION=dry" in runbook
    assert "BOT_LIVE_CONFIRMED=YES" in runbook
    assert "/var/lib/ladder-dragon/backups" in runbook
