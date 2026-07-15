# Ladder Dragon — Binance Spot Grid Bot

Приватный Python-проект для управления лестничной торговлей на Binance Spot. Бот строит адаптивные сетки BUY/SELL, учитывает ATR, EMA и VWAP, управляет OCO-ордерами и сохраняет торговую статистику в SQLite.

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
| `ai_supervisor.py` | Главный цикл, построение плана, очистка ордеров, position guard и запуск воркеров |
| `1.8_autosize_universal.py` | Исполнение BUY/SELL/OCO для отдельного символа |
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
  --base-script ./1.8_autosize_universal.py
```

Для отправки ордеров в Testnet одновременно нужны `--live` и точное подтверждение:

```bash
BOT_LIVE_CONFIRMED=YES python ai_supervisor.py \
  --live --testnet \
  --symbols SOLUSDT,ETHUSDT \
  --base-script ./1.8_autosize_universal.py
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

Исполнитель сохраняет BUY/OCO-намерение в `BOT_ORDER_JOURNAL` до отправки запроса. После потерянного ACK или рестарта он сначала запрашивает Binance по прежнему `clientOrderId`; исполненный BUY остаётся незавершённым, пока OCO или fallback SELL не подтверждены. Ошибка защиты создаёт persistent circuit halt.

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
- выполнить authenticated Testnet `order-test` и `limit-cancel` с отдельными ключами;
- провести walk-forward анализ на реальных исторических свечах перед изменением стратегии.

## Документация

- [История изменений](CHANGELOG.md)
- [Полное руководство](FRONT/readme.html)
- [Справка по дашборду](FRONT/help.html)
- [Безопасный шаблон systemd](deploy/mybot.service)
- [Исторические заметки systemd — не разворачивать](docs/legacy-systemd-notes.txt)

## Лицензия

Проект приватный. Лицензия на распространение пока не определена.
