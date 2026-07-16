# Ladder Dragon — Binance Spot Grid Bot

Приватный Python-проект для управления лестничной торговлей на Binance Spot. Бот строит адаптивные сетки BUY/SELL, учитывает ATR, EMA и VWAP, управляет OCO-ордерами и сохраняет торговую статистику в SQLite.

Текущая версия продукта: **2.9.0**. Ladder Dragon использует [Semantic Versioning](https://semver.org/); единственный источник версии — `product_version.py`. Проверить установленную версию можно командой `python ai_supervisor.py --version`.

> [!WARNING]
> Проект работает с реальными биржевыми ордерами. Это не инвестиционная рекомендация. DRY является режимом по умолчанию, а любые изменяющие Binance-запросы дополнительно блокируются на уровне транспорта. Тем не менее перед Mainnet LIVE обязателен отдельный прогон на Binance Spot Testnet и ручная проверка лимитов.

## Возможности

- динамическая процентная лестница для нескольких торговых пар;
- адаптация по направлению рынка, ATR, EMA и VWAP;
- опциональный AI-рекомендатель режима, ширины лестницы и коэффициента CAP;
- автоматический CAP на один ордер;
- постановка OCO и перенос защиты в breakeven после TP1;
- фильтры паники и медвежьего режима;
- контроль позиции и ночной flatten;
- SQLite-статистика, FIFO/cash PnL и отчёты;
- FastAPI-дашборд для состояния Raspberry Pi, сделок и журналов.

## Архитектура

| Компонент | Назначение |
| --- | --- |
| `ai_supervisor.py` | Главный orchestration loop, очистка ордеров, position guard и запуск воркеров |
| `ai_advisor.py` | Изолированный LLM-рекомендатель со строгой схемой, диапазонами и fail-safe fallback |
| `ai_context.py` | Агрегаты истории/рынка и раздельная оценка прошлых AI-рекомендаций |
| `ai_policy.py` | Детерминированный safety-шлюз, shadow/A-B, бюджеты и числовой benchmark |
| `ai_statistical.py` | Локальная трёхклассовая logistic regression на накопленной shadow-истории |
| `autosize_universal.py` | Координация исполнения BUY/SELL/OCO для отдельного символа |
| `supervisor_config.py`, `executor_config.py` | Построение строгих CLI и проверка конфигурации процессов |
| `strategy_math.py` | Чистая математика лестниц, EMA, ATR, ADX и panic-сигналов |
| `binance_transport.py` | Fail-closed HTTP, подпись Binance, DRY-gate и retry/backoff |
| `executor_market.py` | Чтение цен, балансов и base/quote активов с fallback и кэшем |
| `executor_orders.py` | Идемпотентное размещение LIMIT/OCO и fail-closed восстановление ACK |
| `executor_planning.py` | Чистое планирование BUY/SELL: кандидаты, лимиты, guard-цены и размеры заявок |
| `executor_protection.py` | Сопровождение исполненных BUY, создание OCO/fallback TP и breakeven re-arm |
| `executor_runtime.py` | Жизненный цикл торгового воркера: длительность, остановка и периодические тики |
| `executor_recovery.py` | Query/cancel ордеров, проверка OCO и восстановление после рестарта |
| `executor_stats.py` | Импорт `/myTrades` и точная оценка комиссий в quote-активе |
| `tools_market.py` | Binance HTTP API, подпись запросов, цены, свечи и торговые фильтры |
| `tools_stats.py` | Хранение сделок и агрегатов в SQLite |
| `risk_manager.py`, `risk_ctl.py` | Постоянный circuit breaker, портфельные лимиты и ручной reset |
| `order_identity.py`, `order_recovery.py` | Идемпотентные ID, persistent order-intents и восстановление после рестартов |
| `binance_testnet_smoke.py` | Изолированный Spot Testnet preflight и create/query/cancel smoke |
| `simulation.py`, `backtest.py` | Decimal-симулятор с комиссиями, проскальзыванием и walk-forward |
| `auto_ladder_map.py` | Генерация лестницы по режиму рынка |
| `gen_vwap_env.py` | Расчёт базовых VWAP-параметров |
| `gen_vwap_autotune.py` | Подстройка VWAP по FIFO PnL |
| `pnl_24h.py`, `pnl_reporter.py` | Расчёт и экспорт PnL |
| `FastAPI/pi-dashboard/app.py` | API системного и торгового дашборда |
| `FRONT/` | Статический интерфейс и встроенная документация |

## Требования

- Linux или Raspberry Pi OS;
- Python 3.10+;
- Binance Spot API;
- для основной части: `requests`, `python-dotenv`;
- для дашборда: `fastapi`, `uvicorn`, `psutil`.

Проект использует Linux-специфичные механизмы `fcntl`, `/proc`, `systemd` и `vcgencmd`. Полноценный торговый запуск на macOS и Windows не поддерживается.

## Локальное окружение

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,dashboard]'
```

Версии runtime, dashboard и test-зависимостей зафиксированы в `pyproject.toml`.

## Конфигурация

Создайте локальный `.env` из безопасного шаблона. Файл исключён из Git:

```bash
cp .env.example .env
```

Для локального запуска на macOS используйте доступный для записи runtime-каталог:

```env
BOT_RUN_DIR=.runtime
BOT_TESTNET_RUN_DIR=.runtime/testnet
BOT_STATS_DB=.runtime/bot_stats.db
BOT_ORDER_JOURNAL=.runtime/order_intents.sqlite3
BOT_TESTNET_STATS_DB=.runtime/testnet_bot_stats.db
BOT_TESTNET_ORDER_JOURNAL=.runtime/testnet_order_intents.sqlite3
```

На сервере systemd оставьте `BOT_RUN_DIR=/run/mybot` из шаблона.

Testnet использует отдельные runtime, circuit state, stats DB и order journal. Его
состояние проверяется и сбрасывается отдельно: `python risk_ctl.py status --testnet`
и `python risk_ctl.py reset --testnet --force`.

Рекомендации для API-ключа:

- не разрешать вывод средств;
- ограничить доступ доверенным IP;
- для дашборда использовать отдельный read-only ключ;
- начинать с Binance Spot Testnet;
- никогда не добавлять `.env`, приватные ключи, базы и логи в Git.

### AI-рекомендатель и DeepSeek

AI-слой выключен по умолчанию. Он получает только агрегированные рыночные
индикаторы и может рекомендовать режим `UP/DOWN/FLAT`, коэффициент ширины
лестницы и коэффициент CAP. У него нет торговых инструментов и доступа к
созданию, отмене или просмотру ордеров.

Каждый ответ проходит локальную строгую схему, проверку типов, диапазонов и
минимальной уверенности. Ошибка API, неверный JSON или неподходящая рекомендация
возвращают супервизор к детерминированной стратегии. Рекомендованный CAP может
уменьшить, но не увеличить CAP, уже рассчитанный `RiskManager`.

Для DeepSeek:

```env
AI_ADVISOR_ENABLE=1
AI_MODE=SHADOW
AI_PROVIDER=deepseek
AI_MODEL=deepseek-v4-flash
AI_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=ваш_ключ
AI_USAGE_LOG=.runtime/ai_usage.ndjson
AI_DECISIONS_DB=.runtime/ai_decisions.sqlite3
AI_TESTNET_DECISIONS_DB=.runtime/testnet_ai_decisions.sqlite3
AI_DAILY_COST_LIMIT_USD=0.05
AI_DAILY_TOKEN_LIMIT=100000
AI_MAX_REQUESTS_PER_DAY=1000
```

Для OpenAI достаточно заменить provider и ключ:

```env
AI_PROVIDER=openai
AI_MODEL=gpt-5-mini
OPENAI_API_KEY=ваш_ключ
```

Ключ LLM не передаётся через CLI. Для совместимого API используйте
`AI_PROVIDER=compatible`, `AI_BASE_URL`, `AI_MODEL` и `AI_API_KEY`.

Проверить несколько синтетических сценариев через настроенного провайдера без
подключения к Binance и без ордеров:

```bash
python ai_advisor_smoke.py --provider deepseek
```

Расход каждого фактического запроса пишется в `AI_USAGE_LOG` в формате NDJSON:
модель, символ, outcome, latency, prompt/cache/completion tokens и оценка USD.
Промпт, ответ модели, ключи и торговые данные в журнал не записываются. При
достижении `AI_USAGE_LOG_MAX_BYTES` текущий файл переносится в `.1`.

Для DeepSeek V4 Flash встроена оценка по официальным тарифам за 1 млн токенов:
cache-hit input `$0.0028`, cache-miss input `$0.14`, output `$0.28`. Тарифы
можно переопределить через `AI_INPUT_CACHE_HIT_USD_PER_MTOK`,
`AI_INPUT_CACHE_MISS_USD_PER_MTOK` и `AI_OUTPUT_USD_PER_MTOK`.

При каждом новом запросе модель получает только безопасные агрегаты:

- PnL, win rate, серии убытков, комиссии и оборот за 30 дней;
- нереализованный PnL позиции без раскрытия количества и средней цены;
- доходности и объём за 15 минут, 1 час, 4 часа и 24 часа;
- spread и дисбаланс верхних 5/20 уровней стакана без сырых заявок;
- число BUY/SELL, суммарную BUY-экспозицию и долю portfolio CAP;
- отношение свободного USDT к обязательному резерву;
- точность прошлых AI-рекомендаций на горизонтах 15 минут, 1 час и 4 часа.

Сырые сделки, полный баланс, API-ключи, `orderId`, `clientOrderId` и полный
стакан модели не передаются. Рекомендации Testnet и Mainnet хранятся в разных
SQLite-файлах. Результаты решения оцениваются позднее по движению цены и
автоматически агрегируются в следующий AI-контекст.

Режимы AI:

- `DISABLED` — запросы к модели не выполняются;
- `SHADOW` — рекомендации записываются и оцениваются, но торговый план не меняется;
- `APPLY` — рекомендация может повлиять на план только после кодового safety-policy.

В рабочем `.env` установлен безопасный `SHADOW`. Переводить в `APPLY` следует
после накопления достаточной A/B-статистики.

Safety-policy независимо от prompt:

- отклоняет устаревший или неполный контекст;
- запрещает сужать лестницу при высокой волатильности;
- запрещает повышать агрессивность при малом числе сделок;
- уменьшает CAP при серии убытков, просадке или высокой загрузке портфеля;
- включает `PAUSE_BUYS` при широком spread или недостаточном USDT-резерве;
- отключает влияние AI, если накопленная точность ниже порога;
- никогда не расширяет CAP Risk Manager.

Дневные лимиты `AI_DAILY_COST_LIMIT_USD`, `AI_DAILY_TOKEN_LIMIT` и
`AI_MAX_REQUESTS_PER_DAY` переводят AI в детерминированный fallback до следующего
UTC-дня. Рядом с DeepSeek считается независимый числовой regime benchmark.
После накопления минимум 60 размеченных решений к нему подключается локальная
трёхклассовая logistic regression (`UP/FLAT/DOWN`). Она обучается только на
локальной shadow-истории и не требует внешнего ML-сервиса; до минимальной
выборки используется прозрачный rule-based benchmark.

Защищённый endpoint `/api/ai/status` и карточка дашборда показывают статус
`ACTIVE/SHADOW/DISABLED/DEGRADED`, расходы, последние решения, calibration
confidence и сравнение AI с baseline на горизонте 1 час.

Торговый процесс атомарно публикует `/run/mybot/ai_status.json`: фактический
Testnet/Mainnet, LIVE/DRY, версию продукта, AI-провайдера/модель, бюджеты и пути
к активным базам. Файл не содержит ключей, промптов, балансов или order ID.
При `DASHBOARD_FOLLOW_BOT_PATHS=1` дашборд читает именно активные stats/AI-файлы,
поэтому переключение venue не оставляет интерфейс на старой базе.

## Проверка кода

Проверить синтаксис без запуска торгового цикла:

```bash
python -m compileall -q .
bash -n supervisor_ctl.sh
python ai_supervisor.py --help
python -m pytest
```

Безопасный DRY/Testnet-запуск без создания и отмены ордеров:

```bash
python ai_supervisor.py \
  --testnet \
  --symbols SOLUSDT,ETHUSDT \
  --base-script ./autosize_universal.py
```

Для отправки ордеров в Testnet одновременно нужны `--live` и точное подтверждение:

```bash
BOT_LIVE_CONFIRMED=YES python ai_supervisor.py \
  --live --testnet \
  --symbols SOLUSDT,ETHUSDT \
  --base-script ./autosize_universal.py
```

Перед LIVE выполняется fail-closed preflight: доступность SQLite, синхронизация времени, биржевые фильтры, права API, circuit halt и корректность всех лимитов.

### Spot Testnet smoke

Скрипт жёстко разрешает только `https://testnet.binance.vision` и не может обратиться к Mainnet. Публичная проверка не требует ключей:

```bash
python binance_testnet_smoke.py --mode public --symbol SOLUSDT
```

Проверка подписи и прав ключа без настоящего ордера:

```bash
python binance_testnet_smoke.py --mode authenticated --symbol SOLUSDT
python binance_testnet_smoke.py --mode order-test --symbol SOLUSDT
```

Настоящий Testnet LIMIT создаётся далеко ниже рынка, проверяется и отменяется в `finally`. Для него нужно отдельное подтверждение:

```bash
BOT_TESTNET_ORDER_CONFIRMED=YES \
python binance_testnet_smoke.py --mode limit-cancel --symbol SOLUSDT
```

Полный Testnet lifecycle делает минимальный MARKET BUY, проверяет исполнение, создаёт и повторно запрашивает OCO, затем в `finally` отменяет OCO и продаёт только приобретённый тестом остаток. Он требует отдельного подтверждения и никогда не использует исходные холдинги:

```bash
BOT_TESTNET_BUY_OCO_CONFIRMED=YES \
python binance_testnet_smoke.py --mode buy-oco --symbol SOLUSDT
```

Restart-вариант после BUY заново открывает SQLite journal и сверяет ордер по сохранённому `clientOrderId` до создания OCO:

```bash
BOT_TESTNET_BUY_OCO_CONFIRMED=YES \
python binance_testnet_smoke.py --mode buy-oco-restart --symbol SOLUSDT
```

Изолированная проверка circuit breaker не использует торговые ключи и не касается production halt-файла:

```bash
python binance_testnet_smoke.py --mode circuit-drill --symbol SOLUSDT
```

Для длительного Testnet soak запустите рядом с supervisor read-only монитор. Он
останавливается с ошибкой при лишних BUY, превышении exposure, persistent halt,
длительно незащищённой позиции или расхождении account ↔ SQLite:

```bash
python testnet_soak_monitor.py --symbol SOLUSDT --duration-sec 43200 \
  --interval-sec 5 --max-open-buys 1 --max-exposure-usdt 25
```

Итоговый JSON сохраняется в изолированном Testnet runtime как
`.runtime/testnet/soak_report.json`.

Исполнитель сохраняет BUY/OCO-намерение в `BOT_ORDER_JOURNAL` до отправки запроса. После потерянного ACK или рестарта он сначала запрашивает Binance по прежнему `clientOrderId`; исполненный BUY остаётся незавершённым, пока OCO или fallback SELL не подтверждены. Ошибка защиты создаёт persistent circuit halt.

Торговая статистика хранит исходный объём исполнения (`gross_qty`), фактическое
изменение позиции (`net_qty`), актив/размер комиссии и её стоимость в quote.
Расчёты inventory, средней цены, FIFO PnL и risk-метрик выполняются через
`Decimal`. Комиссия в BNB оценивается по минутной свече на момент сделки; если
оценка недоступна, risk telemetry блокируется вместо подстановки нулевой комиссии.
Старые SQLite обновляются добавочной миграцией `003`.

## Circuit breaker

Circuit breaker сохраняет стартовую и пиковую equity текущего UTC-дня. При достижении лимита он:

- останавливает дочерние торговые процессы;
- отменяет открытые BUY;
- сохраняет точные причины в halt-файле и `risk_alerts.ndjson`;
- включает cooldown;
- требует ручной reset и не сбрасывается после рестарта.

```bash
python risk_ctl.py status
python risk_ctl.py reset
# --force разрешён только после ручной проверки аккаунта
```

Кроме аварийной остановки контролируются portfolio CAP, дневной оборот, дневной BUY-notional, количество сделок/открытых ордеров, коррелированная экспозиция, резерв USDT и серия убыточных продаж.

## Дашборд

Дашборд запускается только на `127.0.0.1`:

```bash
python run_dashboard.py
```

Все `/api/*` требуют `DASHBOARD_AUTH_TOKEN` или reverse proxy с проверяемым общим секретом (`DASHBOARD_TRUST_PROXY_AUTH=1` + `DASHBOARD_PROXY_AUTH_SECRET`). Raw API логов и SSE удалены; журналы доступны только через очищенную ссылку `/logs/`. Для equity используется отдельный `DASHBOARD_BINANCE_API_KEY` без торговых разрешений.

### Универсальная установка и миграция Raspberry Pi

Полная пошаговая инструкция для чистой системы, приватного GitHub, Testnet,
Mainnet, обновления и восстановления:
[Установка и обновление Raspberry Pi](docs/RASPBERRY_PI_INSTALL.md).

Инсталлятор поддерживает Raspberry Pi OS/Debian, создаёт пользователя и venv,
устанавливает nginx/FastAPI/systemd, включает mDNS, закрывает API через Basic Auth,
создаёт приватный backup timer и переносит старые env/SQLite. Чистая установка
всегда запускается как **Testnet DRY**:

```bash
RELEASE_SHA="<40-символьный SHA проверенного коммита>"
sudo bash deploy/install_raspberry_pi.sh install --commit "$RELEASE_SHA"
```

Старую установку с `/opt/pi-dashboard`, legacy unit и номерным executor нужно
мигрировать. Старый Mainnet определяется автоматически, но LIVE переводится в
DRY, пока не выполнено явное подтверждение:

```bash
sudo bash deploy/install_raspberry_pi.sh migrate --commit "$RELEASE_SHA"
```

Сохранить уже работающий LIVE разрешено только при проверенном
`BOT_LIVE_CONFIRMED=YES`:

```bash
sudo bash deploy/install_raspberry_pi.sh migrate --commit "$RELEASE_SHA" --preserve-live
```

До изменений можно получить безопасный аудит без значений секретов:

```bash
sudo bash deploy/install_raspberry_pi.sh audit
```

Пароль dashboard сохраняется с правами `0600` в
`/root/ladder-dragon-dashboard-credentials.txt`. Архивы находятся только в
`/var/lib/ladder-dragon/backups`; URL `/backups/` всегда отвечает `404`.
SQLite копируется online backup API, а не вместе с несогласованными WAL/SHM.
Инсталлятор применяет переносимые настройки journald, zram и fail2ban. Старые
UFW/FTP/сторонние правила и фиксированные tmpfs-размеры намеренно не копируются:
они зависят от локальной сети, RAM и могут заблокировать удалённый доступ.

Очищенные operational/strategy logs доступны после Basic Auth:
`https://bot.local/logs/` и `https://bot.local/logs/current.log`. Экспорт
обновляется каждую минуту, ограничен 5 МБ на файл и хранит 7 дней. API keys,
secrets, tokens, Authorization и Binance signature редактируются до публикации.
Доступ к сырому journal через dashboard API остаётся выключенным.

### Автоматическое обновление Raspberry Pi

Выполняйте из `/home/bot/apps/binance_bot` после получения новой версии.
Скрипт сам останавливает работающие `mybot` и `pi-healthd`, проверяет
указанный commit SHA как fast-forward, синхронизирует зависимости, обновляет frontend и systemd,
проверяет Python-код и запускает сервисы обратно. Статус `enabled` проверяется и
сохраняется, поэтому автозапуск после перезагрузки Raspberry Pi не пропадёт.
Режим и символы хранятся отдельно в `.env.service`, поэтому updater не
возвращает legacy CLI и не меняет выбранный Testnet/Mainnet или DRY/LIVE:

```bash
sudo bash deploy/update_raspberry_pi.sh update "$RELEASE_SHA"
```

Если `.env.dashboard` отсутствовал, скрипт создаст его и остановится: сначала
добавьте read-only Binance key при необходимости, затем повторите запуск. Auth- и
proxy-секреты генерируются автоматически.
При ошибке после остановки скрипт пытается вернуть в работу те сервисы, которые
были активны до обновления. Открытые Binance-ордера скрипт не отменяет.

Режим `apply` выполняет ту же безопасную остановку и установку, но без Git/pip;
он предназначен для уже обновленной рабочей копии:

```bash
sudo bash deploy/update_raspberry_pi.sh apply
```

Проверка без обновления:

```bash
sudo bash deploy/update_raspberry_pi.sh check
```

Для смены контура редактируйте `BOT_SERVICE_VENUE` и
`BOT_SERVICE_EXECUTION` в root-owned `.env.service`. LIVE дополнительно требует
`BOT_LIVE_CONFIRMED=YES` в секретном `.env`.

## Оставшийся технический долг

- постепенно разделить монолитный исполнитель на небольшие модули;
- перевести оставшуюся биржевую арифметику с `float` на `Decimal`;
- сузить оставшиеся широкие обработчики исключений;
- провести длительный soak-тест настоящего супервизора в Spot Testnet с контролируемыми рестартами;
- провести walk-forward анализ на реальных исторических свечах перед изменением стратегии.
- дополнить event-driven replay реальным историческим стаканом и моделью очереди заявок;
- подтверждать AI edge по фактическому net PnL, а не только по направлению движения;
- расширить rolling correlation и stress-сценарии на полную корзину активов и разные окна;
- выполнить Testnet soak-тест после обновления risk snapshot и симулятора.

## Документация

- [История изменений](CHANGELOG.md)
- [Справка по дашборду](FRONT/help.html)
- [Установка и обновление Raspberry Pi](docs/RASPBERRY_PI_INSTALL.md)
- [Безопасный шаблон systemd](deploy/mybot.service)
- [Drop-in связки supervisor ↔ dashboard](deploy/mybot-dashboard-link.conf)
- [Безопасный шаблон dashboard systemd](deploy/pi-dashboard.service)
- [Установка/миграция Raspberry Pi](deploy/install_raspberry_pi.sh)
- [Обновление Raspberry Pi и проверка связки](deploy/update_raspberry_pi.sh)
- [Приватный backup Raspberry Pi](deploy/backup_raspberry_pi.sh)
- [Исторические заметки systemd — не разворачивать](docs/legacy-systemd-notes.txt)

## Лицензия

Проект приватный. Лицензия на распространение пока не определена.
