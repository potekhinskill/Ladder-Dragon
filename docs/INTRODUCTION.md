<p align="center">
  <img src="assets/ladder-dragon-logo.svg" alt="Ladder Dragon" width="560">
</p>

<h1 align="center">Ladder Dragon</h1>

<p align="center">Адаптивная лестничная торговля для Binance Spot с Risk Manager, OCO-защитой, backtest/replay и read-only dashboard.</p>

> Важно: проект по умолчанию работает в <code>DRY</code>/<code>Testnet</code>. LIVE требует отдельного подтверждения, проверки защиты и ручного контроля.

## Что это

Ladder Dragon объединяет четыре слоя:

1. **Strategy** — лестница BUY/SELL, ATR/EMA/VWAP/ADX и режимы рынка.
2. **Execution** — Binance transport, fills, OCO/STOP, FIFO inventory и recovery.
3. **Risk** — reserve, CAP, circuit breaker, reconciliation и fail-closed gates.
4. **AI advisory** — SHADOW-рекомендации и RAG-контекст без доступа к ордерам.

## Где запускать

| Платформа | Назначение | Рекомендация |
| --- | --- | --- |
| Raspberry Pi OS 64-bit | постоянный сервис, dashboard, backup | основной production/testnet-вариант |
| Linux Debian/Ubuntu | разработка, backtest, Testnet | полноценная локальная поддержка |
| macOS | разработка, тесты, backtest | поддерживается без systemd; только DRY/Testnet |
| Windows + WSL2 Ubuntu | разработка и тесты | допустимо; нативный Windows-запуск не заявляется |

Причина ограничений — production-режим использует Linux <code>systemd</code>,
<code>/proc</code>, <code>fcntl</code>, <code>vcgencmd</code>, nginx и файловые
политики. Нативный Windows и macOS не являются заменой Raspberry-сервера.

## Быстрый старт на Raspberry Pi

### 1. Подготовить систему

Нужны Raspberry Pi 4/5, Raspberry Pi OS Lite 64-bit, SSH и стабильное питание.

~~~bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git openssh-client ca-certificates
sudo timedatectl set-timezone Asia/Almaty
timedatectl status
~~~

### 2. Настроить доступ к GitHub

Для приватного репозитория используйте отдельный deploy key без права записи.
Полная инструкция: [RASPBERRY_PI_INSTALL.md](RASPBERRY_PI_INSTALL.md#2-доступ-к-приватному-github).

~~~bash
sudo install -d -o bot -g bot -m 0750 /home/bot/apps
sudo -u bot git clone \
  --branch codex/safety-hardening \
  --single-branch \
  git@github.com:potekhinskill/Ladder-Dragon.git \
  /home/bot/apps/binance_bot
~~~

### 3. Установить безопасную конфигурацию

~~~bash
cd /home/bot/apps/binance_bot
RELEASE_SHA="$(sudo -u bot git rev-parse HEAD)"
sudo bash deploy/install_raspberry_pi.sh install --commit "$RELEASE_SHA"
~~~

Чистая установка оставляет <code>Testnet + DRY</code>, создаёт systemd/nginx/dashboard,
защищает <code>/logs/</code> и <code>/backups/</code>, а секреты оставляет вне Git.

### 4. Добавить Testnet-ключи

~~~bash
sudo -u bot nano /home/bot/apps/binance_bot/.env
~~~

Заполните только тестовый блок:

~~~dotenv
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_API_SECRET=...
BINANCE_TESTNET_API_BASE=https://testnet.binance.vision
BOT_LIVE_CONFIRMED=NO
AI_ADVISOR_ENABLE=0
AI_MODE=SHADOW
~~~

Права файла:

~~~bash
sudo chown bot:bot /home/bot/apps/binance_bot/.env
sudo chmod 600 /home/bot/apps/binance_bot/.env
sudo systemctl restart mybot
~~~

### 5. Проверить сервисы и dashboard

~~~bash
sudo systemctl is-active mybot pi-healthd
curl -sk -u dashboard https://bot.local/api/health
curl -sk -u dashboard https://bot.local/api/ai/status
~~~

Откройте <code>https://bot.local/</code>. Пароль dashboard хранится только на Raspberry:

~~~bash
sudo cat /root/ladder-dragon-dashboard-credentials.txt
~~~

### 6. Пройти Testnet до любых Mainnet-решений

~~~bash
cd /home/bot/apps/binance_bot
sudo systemctl stop mybot
sudo -u bot env PYTHONPATH=. .venv/bin/python -m pytest -q
sudo -u bot env PYTHONPATH=. .venv/bin/python \
  binance_testnet_smoke.py --mode public --symbol SOLUSDT
sudo systemctl start mybot
~~~

Переход к LIVE возможен только после проверки баланса, фильтров, OCO/STOP,
gap/restart recovery, circuit breaker и фактического Testnet-сценария BUY → fill
→ protection → exit.

## Запуск на Linux

~~~bash
git clone https://github.com/potekhinskill/Ladder-Dragon.git
cd Ladder-Dragon
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,dashboard]'
cp .env.example .env
~~~

Для разработки оставьте runtime в <code>.runtime</code> и не добавляйте ключи в Git:

~~~bash
export BOT_RUN_DIR=.runtime
export BOT_STATS_DB=.runtime/bot_stats.db
PYTHONPATH=. pytest -q
python -m bin.run_dashboard
~~~

## Запуск на macOS

macOS подходит для backtest, unit-тестов и Testnet-экспериментов:

~~~bash
brew install python git
git clone https://github.com/potekhinskill/Ladder-Dragon.git
cd Ladder-Dragon
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,dashboard]'
cp .env.example .env
export BOT_RUN_DIR=.runtime
PYTHONPATH=. pytest -q
~~~

Не используйте macOS как замену Raspberry для постоянного LIVE: systemd,
аппаратный watchdog и backup-контур здесь не устанавливаются.

## Запуск на Windows

Нативный Windows-запуск не поддерживается. Для разработки используйте WSL2:

1. Установите Ubuntu из Microsoft Store и включите WSL2.
2. В Ubuntu повторите Linux-инструкцию выше.
3. Оставьте <code>DRY/Testnet</code>; не храните ключи в Windows-папках и не
   запускайте LIVE из WSL2.

## Безопасность перед публикацией

- никогда не коммитьте <code>.env</code>, <code>.env.dashboard</code>, ключи,
  Telegram-токены, SQLite-базы, backup-архивы и реальные логи;
- используйте отдельный read-only ключ для dashboard;
- сначала запускайте Testnet, затем DRY и только после отдельного review —
  ограниченный LIVE;
- перед публичным релизом проверьте Git-историю на секреты и замените все
  приватные deployment-пути.

Лицензия и финансовые ограничения: [LICENSE](../LICENSE) и
[DISCLAIMER.md](../DISCLAIMER.md).
