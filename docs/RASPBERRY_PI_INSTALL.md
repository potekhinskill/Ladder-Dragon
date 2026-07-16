# Установка и обновление Ladder Dragon на Raspberry Pi

Инструкция рассчитана на Raspberry Pi OS Bookworm/Debian с `systemd`.
Канонический каталог проекта:

```text
/home/bot/apps/binance_bot
```

Чистая установка всегда запускает бота в безопасном режиме **Testnet DRY**:
торговые запросы и реальные ордера не отправляются.

## 1. Подготовка чистой Raspberry Pi

Рекомендуется:

- Raspberry Pi 4/5 с 4 ГБ RAM или больше;
- Raspberry Pi OS Lite 64-bit;
- SSD или качественная endurance microSD;
- фиксированный DHCP lease;
- включённый SSH;
- корректный часовой пояс и синхронизация времени.

Подключитесь по SSH и обновите базовую систему:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git openssh-client ca-certificates
sudo timedatectl set-timezone Asia/Almaty
timedatectl status
```

После обновления ядра перезагрузите Raspberry Pi:

```bash
sudo reboot
```

## 2. Доступ к приватному GitHub

Создайте системного пользователя бота, если его ещё нет:

```bash
id bot >/dev/null 2>&1 || sudo useradd --create-home --shell /bin/bash bot
sudo install -d -o bot -g bot -m 0700 /home/bot/.ssh
```

Создайте отдельный SSH deploy key без права записи:

```bash
sudo -u bot ssh-keygen \
  -t ed25519 \
  -f /home/bot/.ssh/ladder_dragon_github \
  -N '' \
  -C 'ladder-dragon-raspberry'

sudo cat /home/bot/.ssh/ladder_dragon_github.pub
```

Скопируйте выведенный публичный ключ и добавьте его в GitHub:

```text
Repository → Settings → Deploy keys → Add deploy key
```

Параметры:

- Title: `raspberry-bot`;
- Allow write access: **выключено**.

Создайте SSH-конфигурацию:

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
```

Проверьте доступ:

```bash
sudo -u bot ssh -T git@github.com
```

GitHub обычно отвечает сообщением об успешной аутентификации и отсутствии
shell-доступа. Это нормально.

## 3. Получение проекта

```bash
sudo install -d -o bot -g bot -m 0750 /home/bot/apps

sudo -u bot git clone \
  --branch codex/safety-hardening \
  --single-branch \
  git@github.com:potekhinskill/binance_bot.git \
  /home/bot/apps/binance_bot
```

Проверьте ветку и версию:

```bash
cd /home/bot/apps/binance_bot
sudo -u bot git branch --show-current
sudo -u bot git log -1 --oneline
```

## 4. Запуск универсального инсталлятора

```bash
cd /home/bot/apps/binance_bot
RELEASE_SHA="<40-символьный SHA проверенного коммита>"
sudo bash deploy/install_raspberry_pi.sh install --commit "$RELEASE_SHA"
```

Инсталлятор:

- устанавливает системные пакеты и Python-зависимости;
- создаёт venv;
- устанавливает nginx, FastAPI, fail2ban, zram и journald limits;
- создаёт systemd-сервисы и автозапуск;
- включает mDNS-адрес `bot.local`;
- создаёт локальный TLS-сертификат;
- закрывает dashboard через Basic Auth;
- закрывает URL `/backups/`;
- публикует только очищенные журналы по защищённому URL `/logs/`;
- включает ежедневный приватный backup;
- запускает `mybot` как Testnet DRY.

Пароль дашборда:

```bash
sudo cat /root/ladder-dragon-dashboard-credentials.txt
```

Откройте:

```text
https://bot.local/
```

При первом входе браузер может предупредить о локальном сертификате. Для
постоянного доверия импортируйте сертификат `/etc/nginx/certs/bot.local.pem`
на администраторский компьютер или замените его сертификатом вашей локальной CA.

## 5. Настройка Binance и AI

Секреты находятся только в:

```text
/home/bot/apps/binance_bot/.env
```

Откройте файл:

```bash
sudo -u bot nano /home/bot/apps/binance_bot/.env
```

Для безопасного начала заполните Testnet-блок:

```env
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_API_SECRET=...
BINANCE_TESTNET_API_BASE=https://testnet.binance.vision

BOT_LIVE_CONFIRMED=NO
AI_ADVISOR_ENABLE=1
AI_MODE=SHADOW
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
```

После запуска переключатель `Включить AI` / `Выключить AI` доступен в карточке
AI на `https://bot.local/`. Он меняет только advisory-слой и начинает работать
при следующем runtime-проверочном цикле супервизора; Risk Manager остаётся
обязательным. Если AI не настроен или control-файл повреждён, кнопка остаётся
недоступной либо AI отключается автоматически.

Права файла:

```bash
sudo chown bot:bot /home/bot/apps/binance_bot/.env
sudo chmod 600 /home/bot/apps/binance_bot/.env
```

Для дашборда Binance-ключ не обязателен. Если нужен расчёт equity по аккаунту,
используйте отдельный read-only ключ без `TRADE`:

```bash
sudo -u bot nano /home/bot/apps/binance_bot/.env.dashboard
```

```env
DASHBOARD_BINANCE_API_KEY=...
DASHBOARD_BINANCE_API_SECRET=...
```

Не копируйте торговый Mainnet-ключ в `.env.dashboard`.

## 6. Выбор режима запуска

Режим systemd хранится отдельно от секретов:

```text
/home/bot/apps/binance_bot/.env.service
```

После чистой установки:

```env
BOT_SERVICE_VENUE=testnet
BOT_SERVICE_EXECUTION=dry
BOT_SERVICE_SYMBOLS=SOLUSDT,ETHUSDT,TONUSDT
```

### Testnet DRY

```env
BOT_SERVICE_VENUE=testnet
BOT_SERVICE_EXECUTION=dry
```

### Testnet LIVE

Сначала в `.env`:

```env
BOT_LIVE_CONFIRMED=YES
```

Затем в `.env.service`:

```env
BOT_SERVICE_VENUE=testnet
BOT_SERVICE_EXECUTION=live
```

Перезапуск:

```bash
sudo systemctl restart mybot
```

Перед Mainnet LIVE обязательны Testnet smoke/soak, проверка circuit breaker,
лимитов, времени, API permissions и ручное изучение итоговой конфигурации.

## 7. Проверка установки

```bash
cd /home/bot/apps/binance_bot
sudo bash deploy/update_raspberry_pi.sh check

sudo systemctl is-enabled mybot pi-healthd nginx ladder-dragon-backup.timer
sudo systemctl is-active mybot pi-healthd nginx ladder-dragon-backup.timer

sudo journalctl -u mybot -n 100 --no-pager
sudo journalctl -u pi-healthd -n 50 --no-pager
```

Проверка версии:

```bash
sudo -u bot /home/bot/apps/binance_bot/.venv/bin/python \
  /home/bot/apps/binance_bot/ai_supervisor.py --version
```

Проверка API через nginx:

```bash
curl -k -u dashboard https://bot.local/api/health
```

`8081` не должен быть доступен с другого компьютера: FastAPI слушает только
`127.0.0.1`.

## 8. Обычное обновление

Используйте одну команду:

```bash
cd /home/bot/apps/binance_bot
RELEASE_SHA="<40-символьный SHA проверенного коммита>"
sudo bash deploy/update_raspberry_pi.sh update "$RELEASE_SHA"
```

Updater автоматически:

1. создаёт закрытый backup;
2. запоминает активность и автозапуск сервисов;
3. останавливает `mybot` и `pi-healthd`;
4. применяет только указанный fast-forward commit SHA;
5. обновляет Python-зависимости;
6. обновляет nginx, frontend и systemd;
7. проверяет Python и nginx;
8. запускает сервисы;
9. ждёт свежий `RUNNING` heartbeat;
10. проверяет закрытость API без авторизации.

Testnet/Mainnet, DRY/LIVE, символы и секреты updater не сбрасывает.

После обновления:

```bash
sudo bash deploy/update_raspberry_pi.sh check
sudo journalctl -u mybot -n 100 --no-pager
```

## 9. Режим `apply`

Если Git уже обновлён вручную и нужно только применить файлы:

```bash
cd /home/bot/apps/binance_bot
sudo bash deploy/update_raspberry_pi.sh apply
```

`apply` не выполняет `git pull` и `pip install`, но безопасно останавливает и
запускает сервисы, обновляет nginx/systemd/frontend и проверяет heartbeat.

## 10. Резервные копии

Автоматические архивы:

```text
/var/lib/ladder-dragon/backups
```

Создать архив вручную:

```bash
sudo systemctl start ladder-dragon-backup.service
sudo journalctl -u ladder-dragon-backup -n 50 --no-pager
sudo ls -lh /var/lib/ladder-dragon/backups
```

Архивы содержат env-файлы и являются секретными. Не публикуйте их через nginx,
облако с открытой ссылкой или публичный Git.

## 11. Защищённые ротационные логи

Журналы доступны под тем же Basic Auth, что и dashboard:

```text
https://bot.local/logs/
https://bot.local/logs/current.log
https://bot.local/logs/status.json
```

Экспорт обновляется каждую минуту. `current.log` содержит последние строки,
а дневные файлы имеют формат `mybot-YYYY-MM-DD.log`.

По умолчанию:

- срок хранения — 7 дней;
- максимум одного файла — 5 МБ;
- старые дневные файлы удаляются автоматически;
- запись происходит атомарно;
- `Authorization`, API keys, secrets, tokens и Binance `signature` заменяются
  на `<redacted>`;
- сырой `/api/bot/logs` остаётся выключенным.

Проверка таймера:

```bash
sudo systemctl status ladder-dragon-log-export.timer --no-pager
sudo systemctl start ladder-dragon-log-export.service
sudo ls -lh /var/lib/ladder-dragon/logs
```

Доступ к `/logs/` без имени пользователя и пароля должен возвращать HTTP `401`.
Журнал помогает находить ошибки, оценивать решения стратегии и формировать
гипотезы, но сам по себе не доказывает прибыльность. Изменения стратегии нужно
проверять Testnet, backtest/walk-forward и сравнением с buy-and-hold.

## 12. Миграция старой Raspberry Pi

Для старой установки используйте:

```bash
cd /home/bot/apps/binance_bot
sudo bash deploy/install_raspberry_pi.sh audit
sudo bash deploy/install_raspberry_pi.sh migrate
```

Миграция:

- сохраняет старый project/systemd/nginx;
- переносит env и SQLite;
- удаляет legacy CLI и номерной executor из запуска;
- переносит `/opt/pi-dashboard` в закрытое legacy-хранилище;
- закрывает публичные backup;
- переводит обнаруженный LIVE в DRY.

Сохранять LIVE при миграции можно только после ручной проверки:

```bash
sudo bash deploy/install_raspberry_pi.sh migrate --preserve-live
```

Для этого в `.env` уже должно быть:

```env
BOT_LIVE_CONFIRMED=YES
```

## 13. Типовые ошибки

### `Permission denied (publickey)`

Проверьте Deploy Key:

```bash
sudo -u bot ssh -T git@github.com
sudo -u bot git -C /home/bot/apps/binance_bot remote -v
```

### Binance `-2015 Invalid API-key, IP, or permissions`

Проверьте:

- выбран ли правильный Testnet/Mainnet ключ;
- разрешён ли IP Raspberry Pi;
- включены ли нужные permissions;
- ключ дашборда не используется торговым процессом;
- не перепутаны HMAC secret и API key.

### `bot.local` не открывается

```bash
systemctl status avahi-daemon nginx pi-healthd
getent hosts bot.local
sudo nginx -t
```

Если клиент не поддерживает mDNS, используйте IP Raspberry Pi или добавьте
локальную DNS-запись.

### Бот не запускается после обновления

```bash
sudo systemctl status mybot --no-pager
sudo journalctl -u mybot -n 200 --no-pager
sudo cat /run/mybot/ai_status.json
```

Не включайте Mainnet LIVE, пока `update_raspberry_pi.sh check` и preflight не
завершаются успешно.
