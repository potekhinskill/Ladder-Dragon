import base64
import hashlib
from pathlib import Path
import re

import product_version


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text()


def test_source_code_uses_english_outside_localization_catalogs():
    """Keep maintenance text English while allowing translated UI catalogs."""
    extensions = {".py", ".sh", ".html", ".js"}
    allowed = {ROOT / "FRONT/locales.js"}
    violations = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in extensions or path in allowed:
            continue
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"[\u0400-\u04ff]", line):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert not violations, "Cyrillic source text found outside localization catalogs: " + ", ".join(violations)


def test_production_code_has_copyright_and_english_maintenance_note():
    paths = list(ROOT.glob("*.py"))
    paths += list((ROOT / "bin").glob("*.py"))
    paths += list((ROOT / "bin").glob("*.sh"))
    paths += list((ROOT / "ladder_dragon").rglob("*.py"))
    paths += list((ROOT / "deploy").glob("*.py"))
    paths += list((ROOT / "deploy").glob("*.sh"))
    paths += list((ROOT / "deploy").glob("*.service"))
    paths += list((ROOT / "deploy").glob("*.timer"))
    paths += list((ROOT / "FRONT").glob("*.html"))
    paths += [ROOT / "FRONT/locales.js", ROOT / "FastAPI/pi-dashboard/app.py"]
    for path in paths:
        source = path.read_text()
        assert "SPDX-License-Identifier: MIT" in source
        assert "Copyright (c) 2026 IURII Potekhin" in source
        assert "Purpose:" in source or "purpose:" in source


def test_maintenance_headers_are_specific_not_boilerplate():
    phrase = "Purpose: keep the file role and safety boundaries clear during maintenance."
    paths = list(ROOT.glob("*.py"))
    paths += list((ROOT / "bin").glob("*.py")) + list((ROOT / "bin").glob("*.sh"))
    paths += list((ROOT / "deploy").glob("*"))
    paths += list((ROOT / "ladder_dragon").rglob("*.py"))
    paths += [ROOT / "FRONT/index.html", ROOT / "FRONT/locales.js"]
    assert all(phrase not in path.read_text() for path in paths if path.is_file())


def test_dashboard_launcher_uses_absolute_project_app_path():
    launcher = read("bin/run_dashboard.py")
    assert "Path(__file__).resolve().parents[1]" in launcher
    assert "sys.path.insert(0, str(app_dir))" in launcher
    assert "uvicorn.run(app," in launcher


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
    assert "Content-Security-Policy" in site
    assert "X-Content-Type-Options" in site
    assert "Referrer-Policy" in site
    assert "Permissions-Policy" in site
    assert "frame-ancestors 'none'" in site


def test_dashboard_csp_hash_matches_the_only_inline_script():
    index = read("FRONT/index.html")
    site = read("deploy/nginx/bot.local.conf")
    blocks = re.findall(r"<script>(.*?)</script>", index, flags=re.DOTALL)
    assert len(blocks) == 1
    digest = base64.b64encode(hashlib.sha256(blocks[0].encode()).digest()).decode()
    assert f"'sha256-{digest}'" in site
    assert "script-src 'self' 'unsafe-inline'" not in site


def test_dashboard_escapes_exchange_and_database_values_before_inner_html():
    index = read("FRONT/index.html")
    for expression in (
        "${escapeHtml(row.asset)}",
        "${escapeHtml(x.symbol)}",
        "${escapeHtml(x.side||'—')}",
        "${escapeHtml(feeCell)}",
    ):
        assert expression in index
    assert "body.replaceChildren()" in index
    assert "cell.textContent = `${tr('api_error')}: ${e}`" in index


def test_dashboard_uses_ladder_dragon_branding():
    index = read("FRONT/index.html")
    assert "<title>Ladder Dragon</title>" in index
    assert "🧪" not in index
    assert "<h1>Ladder Dragon</h1>" in index
    assert "function updateTrade24(sum, balances)" in index
    assert "balances.total_value_usdt" in index
    assert "updateTrade24(sum, balances)" in index
    assert 'src="/ladder-dragon-dashboard-icon.svg"' in index
    assert '<link rel="icon" type="image/svg+xml" href="/ladder-dragon-dashboard-icon.svg"/>' in index
    assert '<rect' not in read("docs/assets/ladder-dragon-dashboard-icon.svg")
    assert "Pi Dashboard" not in index
    assert 'class="github-update is-unavailable"' in index
    assert "status.classList.add(`is-${state}`)" in index
    assert "url.startsWith('https://github.com/')" in index
    assert "setState(payload.update_available ? 'available' : 'current', payload.remote_url)" in index
    assert 'data-i18n="portfolio_change_24h"' in index
    assert 'id="t24-portfolio"' in index
    assert 'data-i18n="fifo_pnl_24h"' in index
    assert 'id="t24-fifo"' in index
    assert 'data-i18n="cashflow_pnl_24h"' in index
    assert 'id="t24-cashflow"' in index
    assert "d.portfolio_change_usdt ?? d.equity_pnl_usdt" in index
    assert "d.net_pnl_usdt ?? d.realized_pnl_usdt" in index
    assert "d.cashflow_pnl_usdt ?? null" in index


def test_public_license_and_financial_disclaimer_are_explicit():
    license_text = read("LICENSE")
    disclaimer = read("DISCLAIMER.md")
    readme = read("README.md")
    assert "MIT License" in license_text
    assert "IURII Potekhin / Ladder Dragon" in license_text
    assert "not financial, investment" in disclaimer
    assert "losses, including loss of money" in disclaimer
    assert "DISCLAIMER.md" in readme


def test_public_project_contact_is_documented_not_runtime_data():
    readme = read("README.md")
    copyright_text = read("COPYRIGHT.md")
    assert "https://www.linkedin.com/in/ypotekhin/" in readme
    assert "https://www.linkedin.com/in/ypotekhin/" in copyright_text


def test_intro_document_and_logo_cover_supported_platforms():
    intro = read("docs/INTRODUCTION.md")
    logo = read("docs/assets/ladder-dragon-logo.svg")
    readme = read("README.md")
    assert "Raspberry Pi" in intro
    assert "macOS" in intro
    assert "Linux" in intro
    assert "WSL2" in intro
    assert "BOT_LIVE_CONFIRMED=NO" in intro
    assert "<svg" in logo and "Ladder Dragon" in logo
    assert 'viewBox="0 0 120 120"' in logo
    assert 'id="drg"' in logo
    assert "docs/INTRODUCTION.md" in readme


def test_dashboard_exposes_read_only_ops_trading_and_ai_quality_blocks():
    index = read("FRONT/index.html")
    app = read("FastAPI/pi-dashboard/app.py")
    backup = read("deploy/backup_raspberry_pi.sh")
    for marker in (
        "id=\"ops-load\"", "id=\"ops-ntp\"", "id=\"ops-backup\"",
        "id=\"execution-banner\"", "id=\"trade-risk\"", "id=\"positions-body\"",
        "id=\"ai-context-age\"", "id=\"ai-budget\"", "id=\"ai-degraded-quality\"",
    ):
        assert marker in index
    assert '@app.get("/api/trading/overview")' in app
    assert '"operations": ops' in app
    assert '"network_probe_ok": network_probe_ok' in app
    assert '"writable": writable' in app
    assert 'heartbeat_risk = dict(_AI_RUNTIME_STATUS.get("risk") or {})' in read("bin/ai_supervisor.py")
    assert 'backup_status.json' in backup
    assert 'BACKUP_RUNTIME_STATUS_FILE' in backup
    assert 'id=\"ops-backup-reason\"' in index
    assert "SupplementaryGroups=www-data" in read("deploy/pi-dashboard.service")
    assert '\"heartbeat\": _runtime_heartbeat_snapshot()' in app
    assert "dashboard namespace RO" in index


def test_dashboard_transient_failures_are_bounded_and_visible():
    app = read("FastAPI/pi-dashboard/app.py")
    index = read("FRONT/index.html")
    site = read("deploy/nginx/bot.local.conf")
    unit = read("deploy/pi-dashboard.service")

    assert "DASHBOARD_STALE_CACHE_MAX_SEC" in app
    assert "ACCOUNT_BALANCE_STALE" in app
    assert "OPEN_ORDERS_STALE" in app
    assert "API_RESPONSE_CACHE" in index
    assert "API_RESPONSE_CACHE_TTL_MS = 300000" in index
    assert "API_RESPONSE_CACHE_MAX_KEYS = 24" in index
    assert "API_RESPONSE_CACHE_MAX_BYTES = 512 * 1024" in index
    assert "FETCH_TIMEOUT_MS = 8000" in index
    assert "AbortController" in index
    assert "visibilitychange" in index
    assert "pagehide" in index
    assert "chart.destroy()" in index
    assert "FILLED_PAGE_SIZE = 300" in index
    assert "LOG_TAIL_BYTES = 256 * 1024" in index
    assert "POLL_JOBS" in index
    assert "setInterval(" not in index
    assert "url !== '/api/security/csrf'" in index
    assert "transport retry" in index
    assert "REFRESH_IN_FLIGHT" in index
    assert "OPEN_ORDERS_REFRESH_IN_FLIGHT" in index
    assert "error_page 502 504 = @dashboard_api_unavailable" in site
    assert "DASHBOARD_UPSTREAM_UNAVAILABLE" in site
    assert "Restart=always" in unit
    assert "RestartSec=2" in unit


def test_dashboard_large_sources_are_bounded_server_side():
    app = read("FastAPI/pi-dashboard/app.py")
    exporter = read("deploy/export_sanitized_logs.py")
    service = read("deploy/ladder-dragon-log-export.service")

    assert "min(int(limit), 500)" in app
    assert "LIMIT ? OFFSET ?" in app
    assert "_ai_database_aggregates" in app
    assert "SELECT {expressions['evaluation_json']} AS evaluation_json FROM ai_decisions" not in app
    assert 'BOT_LOG_MAX_BYTES", "262144"' in exporter
    assert "Environment=BOT_LOG_MAX_BYTES=262144" in service


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
    assert '"${PROJECT_DIR}/docs/assets/ladder-dragon-logo.svg" "${PROJECT_DIR}/docs/assets/ladder-dragon-dashboard-icon.svg"' in installer
    assert 'FRONT/vendor/chart.umd.min.js' in installer
    assert 'FRONT/vendor/chart.js.LICENSE.txt' in installer
    assert 'FRONT/index.html FRONT/help.html FRONT/locales.js docs/assets/ladder-dragon-logo.svg docs/assets/ladder-dragon-dashboard-icon.svg CHANGELOG.md' in updater


def test_dashboard_localization_has_all_supported_languages_and_is_deployed():
    index = read("FRONT/index.html")
    locales = read("FRONT/locales.js")
    installer = read("deploy/install_raspberry_pi.sh")
    updater = read("deploy/update_raspberry_pi.sh")
    for locale in ("en", "ru", "zh", "es", "de", "fr", "it", "kk", "uk", "ko", "ja", "pt", "et", "fi", "da"):
        assert f'["{locale}"' in locales
        assert f"Object.assign(translations.{locale}, {{fifo_pnl_24h:" in locales
    assert locales.count("cashflow_pnl_24h:") == 15
    assert '<script src="/locales.js"></script>' in index
    assert 'id="language-select"' in index
    assert "localStorage.getItem(LOCALE_KEY)" in index
    assert "localStorage.setItem(LOCALE_KEY,CURRENT_LOCALE)" in index
    assert "LOCALES.translations[storedLocale]" in index
    assert '"${PROJECT_DIR}/FRONT/locales.js"' in installer
    assert '"${PROJECT_DIR}/docs/assets/ladder-dragon-logo.svg"' in installer
    assert "FRONT/index.html FRONT/help.html FRONT/locales.js docs/assets/ladder-dragon-logo.svg docs/assets/ladder-dragon-dashboard-icon.svg CHANGELOG.md" in updater
    assert "FRONT/vendor/chart.umd.min.js" in updater
    assert "FRONT/vendor/chart.js.LICENSE.txt" in updater
    assert 'src="/ladder-dragon-dashboard-icon.svg"' in index
    assert 'id="ops-platform"' in index


def test_publication_docs_and_local_dashboard_assets_are_present():
    readme = read("README.md")
    index = read("FRONT/index.html")
    assert product_version.__version__ in readme
    assert "not affiliated with" in readme
    assert 'src="/vendor/chart.umd.min.js"' in index
    assert "fonts.googleapis.com" not in index
    assert (ROOT / "FRONT/vendor/chart.umd.min.js").read_bytes().startswith(b"/**")
    assert "MIT License" in read("THIRD_PARTY_NOTICES.md")
    assert "Chart.js Contributors" in read("FRONT/vendor/chart.js.LICENSE.txt")
    for document in ("SECURITY.md", "CONTRIBUTING.md", "TRADEMARKS.md", "THIRD_PARTY_NOTICES.md"):
        assert (ROOT / document).is_file()


def test_sqlite_runtime_sidecars_are_never_tracked():
    ignore = read(".gitignore").splitlines()
    for pattern in ("*.db-shm", "*.db-wal", "*.sqlite3-shm", "*.sqlite3-wal"):
        assert pattern in ignore


def test_bounded_mainnet_canary_is_documented_and_not_preconfigured():
    readme = read("README.md")
    runbook = read("docs/RASPBERRY_PI_INSTALL.md")
    example = read(".env.example")
    source = read("bin/binance_mainnet_canary.py")
    assert "python -m bin.binance_mainnet_canary" in readme
    assert "python -m bin.binance_mainnet_canary" in runbook
    assert "HARD_MAX_NOTIONAL_USDT = Decimal(\"10\")" in source
    assert "HARD_MAX_COMMISSION_USDT = Decimal(\"0.03\")" in source
    assert "--max-commission-usdt 0.02" in readme
    assert "--max-commission-usdt 0.02" in runbook
    assert "BOT_MAINNET_CANARY_CONFIRMED" in source
    assert "BOT_MAINNET_CANARY_CLEANUP_CONFIRMED" in source
    assert "BOT_MAINNET_CANARY_CONFIRMED" not in example
    assert "BOT_MAINNET_CANARY_CLEANUP_CONFIRMED" not in example


def test_dashboard_health_has_portable_host_and_optional_raspberry_telemetry():
    app = read("FastAPI/pi-dashboard/app.py")
    assert 'def _host_snapshot()' in app
    assert '"host": _host_snapshot()' in app
    assert '"supported": False' in app
    assert 'platform.system()' in app


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
    recovery = read("ladder_dragon/execution/order_recovery.py")
    assert 'id="open-orders-body"' in index
    assert "getJSON('/api/account/open-orders')" in index
    assert '@app.get("/api/account/open-orders")' in app
    assert '"client_order_id"' in app
    assert '"remaining_qty"' in app
    assert 'OPEN_ORDERS_FAILED' in app
    assert "executed_qty > 0" in recovery
    assert "executed_qty < requested_qty" in recovery


def test_supervisor_and_dashboard_share_canonical_ai_control_path():
    supervisor = read("bin/ai_supervisor.py")
    dashboard = read("FastAPI/pi-dashboard/app.py")
    control = read("ladder_dragon/ai/ai_control.py")

    assert 'resolve_ai_control_path(os.getenv("AI_CONTROL_FILE"))' in supervisor
    assert 'resolve_ai_control_path(os.getenv("AI_CONTROL_FILE"))' in dashboard
    assert 'Path("FastAPI/pi-dashboard/data/ai_control.json")' in control
    assert 'Path(__file__).resolve().parent / "FastAPI"' not in supervisor


def test_dashboard_balance_filter_hides_small_assets_by_default():
    index = read("FRONT/index.html")
    assert 'id="balance-hide-small"' in index
    assert 'type="checkbox" checked' in index
    assert 'Hide &lt; 1 USDT' in index
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


def test_ai_recommendation_is_compact_two_column_layout():
    index = read("FRONT/index.html")
    assert ".ai-details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))" in index
    assert ".ai-details .row" in index
    assert '@media (max-width:700px){.ai-details{grid-template-columns:1fr}}' in index
    assert '<div class="ai-details">' in index


def test_dashboard_charts_have_bounded_responsive_containers():
    index = read("FRONT/index.html")
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in index
    assert ".grid-charts>.card{min-width:0" in index
    assert ".chart-frame{position:relative" in index
    assert "maintainAspectRatio:false" in index
    assert '<div class="chart-frame"><canvas id="chartTemp"></canvas></div>' in index


def test_shadow_ai_defaults_limit_cost_and_duplicate_requests():
    example = read(".env.example")
    config = read("bin/supervisor_config.py")
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
    supervisor = read("bin/ai_supervisor.py")
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
    assert 'BOT_SERVICE_AUTO_OCO_HOLDINGS:-0' in wrapper
    assert 'if [[ "${AUTO_OCO_HOLDINGS}" == "1" ]]' in wrapper
    assert "args+=(--auto-oco-holdings)" in wrapper
    assert "  --auto-oco-holdings\n" not in wrapper
    assert "BOT_SERVICE_AUTO_OCO_HOLDINGS=0" in read(".env.service.example")


def test_executor_status_does_not_hide_oco_state_behind_question_mark():
    executor = read("bin/autosize_universal.py")
    assert "OCO:?" not in executor
    assert 'protection_state = "not_checked"' in executor


def test_executor_user_stream_reuses_authoritative_exchange_clock():
    executor = read("bin/autosize_universal.py")
    assert "timestamp_ms=TM._timestamp_ms" in executor
    assert "BOT_USER_STREAM_STATE_WRITE_SEC" in executor
    assert "BOT_USER_STREAM_IDLE_TIMEOUT_SEC" in executor


def test_supervisor_control_logs_stay_inside_writable_rotated_directory():
    ctl = read("bin/supervisor_ctl.sh")
    unit = read("deploy/mybot.service")
    assert 'SUPERVISOR_LOG:-${PROJECT_DIR}/logs/supervisor.log' in ctl
    assert 'PNL_LOG_PATH:-${PROJECT_DIR}/logs/pnl.log' in ctl
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
    assert "/etc/bot-alerts.env" not in backup
    assert "EnvironmentFile=-/etc/ladder-dragon/telegram.env" in read(
        "deploy/pi-watchdog-v3.service"
    )
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
    assert "deploy key" in runbook
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
    updater = read("deploy/update_raspberry_pi.sh")
    assert "journalctl" in exporter
    assert "RETENTION_DAYS" in exporter
    assert "MAX_BYTES" in exporter
    assert "<redacted>" in exporter
    assert "OnUnitActiveSec=1m" in timer
    assert "User=root" in service
    assert "Group=www-data" in service
    assert "CapabilityBoundingSet=\n" in service
    assert "ProtectHome=yes" in service
    assert "ExecStart=/usr/bin/python3 /usr/local/libexec/ladder-dragon/export_sanitized_logs.py" in service
    assert "install_runtime_assets.sh" in installer
    assert "install_runtime_assets.sh" in updater
    assert "/usr/local/libexec/ladder-dragon/export_sanitized_logs.py" in read("deploy/backup_raspberry_pi.sh")
    assert "ladder-dragon-log-export.timer" in installer
    assert "expected protected logs HTTP 401" in installer


def test_public_depth_archive_has_timer_retention_and_no_secret_environment():
    wrapper = read("deploy/record_depth_archive.sh")
    service = read("deploy/ladder-dragon-depth-archive.service")
    timer = read("deploy/ladder-dragon-depth-archive.timer")
    installer = read("deploy/install_raspberry_pi.sh")
    updater = read("deploy/update_raspberry_pi.sh")
    runtime_assets = read("deploy/install_runtime_assets.sh")
    assert "BOT_DEPTH_ARCHIVE_RETENTION_DAYS" in wrapper
    assert "-u BINANCE_API_KEY" in wrapper
    assert "-u BINANCE_API_SECRET" in wrapper
    assert "flock -n" in wrapper
    assert "OnUnitActiveSec=1h" in timer
    assert "User=bot" in service
    assert "EnvironmentFile=-/etc/ladder-dragon/depth-archive.conf" in service
    assert "ReadWritePaths=/var/lib/ladder-dragon/depth-archives" in service
    assert "ladder-dragon-depth-archive.timer" in installer
    assert "ladder-dragon-depth-archive.timer" in updater
    assert "/usr/local/bin/ladder-dragon-depth-archive" in runtime_assets


def test_soak_audit_is_periodic_signed_and_transition_notified():
    wrapper = read("deploy/run_production_soak_audit.sh")
    service = read("deploy/ladder-dragon-soak-audit.service")
    timer = read("deploy/ladder-dragon-soak-audit.timer")
    installer = read("deploy/install_raspberry_pi.sh")
    updater = read("deploy/update_raspberry_pi.sh")
    runtime_assets = read("deploy/install_runtime_assets.sh")
    backup = read("deploy/backup_raspberry_pi.sh")
    assert "openssl genpkey -algorithm ED25519" in wrapper
    assert "openssl pkeyutl -sign -rawin" in wrapper
    assert "--notify-on-change" in wrapper
    assert "OnUnitActiveSec=15m" in timer
    assert "User=root" in service
    assert "CapabilityBoundingSet=\n" in service
    assert "ReadWritePaths=/var/lib/ladder-dragon/soak /etc/ladder-dragon" in service
    assert "ladder-dragon-soak-audit.timer" in installer
    assert "ladder-dragon-soak-audit.timer" in updater
    assert "/usr/local/bin/ladder-dragon-soak-audit" in runtime_assets
    assert "/etc/ladder-dragon/soak-report-signing.pem" in backup
    assert "/var/lib/ladder-dragon/soak" in backup


def test_updates_are_commit_allowlisted_and_backups_are_encrypted():
    updater = read("deploy/update_raspberry_pi.sh")
    installer = read("deploy/install_raspberry_pi.sh")
    backup = read("deploy/backup_raspberry_pi.sh")
    backup_unit = read("deploy/ladder-dragon-backup.service")
    assert "update requires an exact 40-character commit SHA" in updater
    assert "git pull" not in updater
    assert "merge-base --is-ancestor" in updater
    assert "git verify-commit" in updater
    assert "/etc/ladder-dragon/update-trust.conf" in updater
    assert "deploy/read_update_trust.py" in updater
    assert "BOT_UPDATE_REQUIRE_SIGNED_COMMIT" not in updater
    assert "BOT_UPDATE_TRUSTED_SIGNER" not in updater
    assert "VALIDSIG" in updater
    assert "verify_release_checkout" in installer
    assert "docs/release-signing-key.asc" in installer
    assert "install_update_trust" in installer
    assert (ROOT / "deploy/update_raspberry_pi_break_glass.sh").is_file()
    assert (ROOT / "deploy/read_update_trust.py").is_file()
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
    assert "trap on_exit EXIT" in backup
    assert "exFAT does not support chmod" in backup
    assert "ReadWritePaths=%s" in updater
    assert "BindReadWritePaths" not in installer + updater
    assert "RequiresMountsFor" in updater
    assert "external-mount.conf" in installer


def test_updater_preserves_stopped_services_and_does_not_arm_watchdog():
    updater = read("deploy/update_raspberry_pi.sh")
    assert 'MYBOT_WAS_ACTIVE="$(service_flag is-active mybot)"' in updater
    assert 'DASHBOARD_WAS_ACTIVE="$(service_flag is-active pi-healthd)"' in updater
    assert 'WATCHDOG_WAS_ACTIVE="$(service_flag is-active pi-watchdog-v3.timer)"' in updater
    assert "systemctl stop pi-watchdog-v3.timer" in updater
    assert 'if [[ "${MYBOT_WAS_ACTIVE}" == "1" && "${WATCHDOG_WAS_ACTIVE}" == "1" ]]' in updater
    assert 'fail "${unit} was stopped before update but became active"' in updater
    assert "systemctl start mybot\nsystemctl start pi-healthd" not in updater
    assert "mybot autostart must be enabled before update" not in updater
    assert 'fail "${unit} autostart policy changed during update"' in updater
    assert 'MYBOT_WAS_ENABLED="$(service_flag is-enabled mybot)"' in updater
    assert 'DASHBOARD_WAS_ENABLED="$(service_flag is-enabled pi-healthd)"' in updater
    assert "verify_previous_service_state" in updater


def test_watchdog_publishes_sanitized_raspberry_health_for_dashboard():
    watchdog = read("deploy/pi-watchdog_v3.sh")
    watchdog_unit = read("deploy/pi-watchdog-v3.service")
    dashboard_unit = read("deploy/pi-dashboard.service")
    dashboard = read("FastAPI/pi-dashboard/app.py")
    index = read("FRONT/index.html")
    assert "HOST_HEALTH_FILE" in watchdog
    assert "get_throttled" in watchdog
    assert "host-health.json" in watchdog
    assert "RuntimeDirectoryMode=0755" in watchdog_unit
    assert "RuntimeDirectoryPreserve=yes" in watchdog_unit
    assert "ReadOnlyPaths=-/run/pi-watchdog/host-health.json" in dashboard_unit
    assert "sanitized_watchdog_probe" in dashboard
    assert 'id="ops-watchdog"' in index


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
    assert "write_status()" in backup


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
    for state in (
        "RUNNING", "AUTH_BACKOFF", "IP_BLOCKED", "RECOVERY_BLOCKED",
        "INTENTIONALLY_STOPPED",
    ):
        assert state in watchdog
        assert state in updater
    assert "|| true'" not in service
    runtime_assets = read("deploy/install_runtime_assets.sh")
    assert "pi-watchdog_v3.sh" in runtime_assets
    assert "/usr/local/bin/pi-watchdog_v3.sh" in runtime_assets


def test_verified_release_installs_runtime_assets_after_merge():
    updater = read("deploy/update_raspberry_pi.sh")
    installer = read("deploy/install_raspberry_pi.sh")
    runtime_assets = read("deploy/install_runtime_assets.sh")
    assert updater.index('git merge --ff-only "${UPDATE_COMMIT}"') < updater.index(
        'PROJECT_DIR="${PROJECT_DIR}" deploy/install_runtime_assets.sh'
    )
    assert "verify_trusted_commit" in updater
    assert '[[ -x deploy/install_runtime_assets.sh ]]' in updater
    assert 'PROJECT_DIR="${PROJECT_DIR}" "${PROJECT_DIR}/deploy/install_runtime_assets.sh"' in installer
    assert "runtime assets must be installed as root" in runtime_assets
    assert "/usr/local/libexec/ladder-dragon/export_sanitized_logs.py" in runtime_assets
    assert "install -o root -g root -m 0644" in runtime_assets


def test_installer_accepts_only_the_canonical_main_branch():
    installer = read("deploy/install_raspberry_pi.sh")
    dashboard = read("FastAPI/pi-dashboard/app.py")
    dashboard_example = read(".env.dashboard.example")
    assert '[[ "${BRANCH}" == "main" ]]' in installer
    assert 'fail "only the canonical main branch is supported"' in installer
    assert 'GITHUB_BRANCH = "main"' in dashboard
    assert "DASHBOARD_GITHUB_BRANCH=" not in dashboard_example


def test_systemd_units_have_extended_sandboxing():
    for relative in (
        "deploy/mybot.service",
        "deploy/pi-dashboard.service",
        "deploy/ladder-dragon-backup.service",
        "deploy/ladder-dragon-log-export.service",
        "deploy/ladder-dragon-depth-archive.service",
        "deploy/ladder-dragon-soak-audit.service",
    ):
        unit = read(relative)
        assert "ProtectKernelTunables=yes" in unit
        assert "ProtectKernelModules=yes" in unit
        assert "ProtectControlGroups=yes" in unit
        assert "RestrictSUIDSGID=yes" in unit
        assert "LockPersonality=yes" in unit
        assert "PrivateDevices=yes" in unit
        assert "ProtectClock=yes" in unit
        assert "ProtectKernelLogs=yes" in unit
        assert "ProtectHostname=yes" in unit
        assert "RestrictNamespaces=yes" in unit
        assert "SystemCallFilter=@system-service" in unit
        assert "CapabilityBoundingSet=" in unit


def test_backup_service_retains_only_required_filesystem_capabilities():
    service = read("deploy/ladder-dragon-backup.service")
    assert "CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER" in service
    assert "AmbientCapabilities=" in service
    assert "CAP_SYS_ADMIN" not in service
    assert "ReadWritePaths=/var/lib/ladder-dragon /home/bot/apps/binance_bot/db" in service


def test_backup_inventory_handles_restricted_proc_without_warning():
    backup = read("deploy/backup_raspberry_pi.sh")
    assert "[[ -r /proc/meminfo ]]" in backup
    assert 'echo "memory=unavailable"' in backup


def test_runtime_dependencies_are_hash_locked_and_installed_without_dependency_resolution():
    installer = read("deploy/install_raspberry_pi.sh")
    updater = read("deploy/update_raspberry_pi.sh")
    workflow = read(".github/workflows/security.yml")
    for relative in (
        "requirements/raspberry.lock", "requirements/ci.lock", "requirements/audit.lock"
    ):
        lock = read(relative)
        assert "--hash=sha256:" in lock
    assert "setuptools==83.0.0" in read("requirements/raspberry.lock")
    assert "setuptools==83.0.0" in read("requirements/ci.lock")
    assert "--require-hashes -r" in installer
    assert "--no-deps --no-build-isolation -e" in installer
    assert "--require-hashes -r requirements/raspberry.lock" in updater
    assert "--require-hashes -r requirements/ci.lock" in workflow
    assert "--require-hashes -r requirements/audit.lock" in workflow


def test_ci_scans_full_history_and_pins_actions_by_commit():
    workflow = read(".github/workflows/security.yml")
    assert "fetch-depth: 0" in workflow
    assert "gitleaks/gitleaks-action@ff98106e4c7b2bc287b24eaf42907196329070c7" in workflow
    assert "trufflesecurity/trufflehog@466da5b0bb161144f6afca9afe5d57975828c410" in workflow
    assert "--only-verified" in workflow
    assert "actions/checkout@v" not in workflow
    assert "actions/setup-python@v" not in workflow


def test_library_modules_are_grouped_by_responsibility():
    expected = {
        "ladder_dragon/ai/ai_context.py",
        "ladder_dragon/execution/executor_orders.py",
        "ladder_dragon/risk/risk_manager.py",
        "ladder_dragon/strategy/market_replay.py",
    }
    assert all((ROOT / relative).is_file() for relative in expected)
    assert not (ROOT / "ai_context.py").exists()
    assert not (ROOT / "executor_orders.py").exists()
    assert not (ROOT / "migrations").exists()
    assert (ROOT / "ladder_dragon/migrations/001_initial.sql").is_file()
    pyproject = read("pyproject.toml")
    assert '[tool.setuptools.packages.find]' in pyproject
    assert 'include = ["ladder_dragon*", "bin*"]' in pyproject
    assert 'ladder_dragon = ["migrations/*.sql"]' in pyproject
