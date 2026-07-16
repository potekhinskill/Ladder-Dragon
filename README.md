# Ladder Dragon — Binance Spot Grid Bot

Приватный Python-проект для управления лестничной торговлей на Binance Spot. Бот строит адаптивные сетки BUY/SELL, учитывает ATR, EMA и VWAP, управляет OCO-ордерами и сохраняет торговую статистику в SQLite.

Текущая версия продукта: **2.2.0**. Ladder Dragon использует [Semantic Versioning](https://semver.org/); единственный источник версии — `product_version.py`. Проверить установленную версию можно командой `python ai_supervisor.py --version`.

> [!WARNING]
> Проект работает с реальными биржевыми ордерами. Это не инвестиционная рекомендация. DRY является режимом по умолчанию, а любые изменяющие Binance-запросы дополнительно блокируются на уровне транспорта. Тем не менее перед Mainnet LIVE обязателен отдельный прогон на Binance Spot Testnet и ручная проверка лимитов.

## Возможности

- динамическая процентная лестница для нескольких торговых пар;
- адаптация по направлению рынка, ATR, EMA и VWAP;
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

Все `/api/*` требуют `DASHBOARD_AUTH_TOKEN` или подтверждённый reverse proxy (`DASHBOARD_TRUST_PROXY_AUTH=1`). API логов и SSE выключены по умолчанию. Для equity используется только отдельный `DASHBOARD_BINANCE_API_KEY` без торговых разрешений; чтение секретов процесса бота из `/proc` удалено.

## Оставшийся технический долг

- постепенно разделить монолитный исполнитель на небольшие модули;
- перевести оставшуюся биржевую арифметику с `float` на `Decimal`;
- сузить оставшиеся широкие обработчики исключений;
- провести длительный soak-тест настоящего супервизора в Spot Testnet с контролируемыми рестартами;
- провести walk-forward анализ на реальных исторических свечах перед изменением стратегии.

## Документация

- [История изменений](CHANGELOG.md)
- [Полное руководство](FRONT/readme.html)
- [Справка по дашборду](FRONT/help.html)
- [Безопасный шаблон systemd](deploy/mybot.service)
- [Исторические заметки systemd — не разворачивать](docs/legacy-systemd-notes.txt)

## Лицензия

Проект приватный. Лицензия на распространение пока не определена.
