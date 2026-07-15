# Changelog — Ladder Dragon (binance_bot)

## [2026-07-16]
### Supervisor DRY/Testnet hardening
- Исполнитель использует `BOT_RUN_DIR` для per-symbol lock, fallback order journal, circuit halt и breakeven state; локальный запуск больше не зависит от Linux-only `/run/mybot`.
- Добавлен экспоненциальный backoff для быстро падающих дочерних процессов и обязательный terminate/wait/kill cleanup при остановке супервизора.
- `Ctrl+C` завершает супервизор и дочерние процессы штатно, без оставшихся процессов и lock-файлов.
- Настоящий супервизор и исполнитель проверены в DRY на Spot Testnet: фильтры и стратегия загружены, все торговые операции заблокированы DRY-gate.

## [2026-07-15]
### Safety hardening
- Добавлен fail-closed DRY/LIVE gate в супервизор и исполнитель; LIVE требует `BOT_LIVE_CONFIRMED=YES`.
- Spot Testnet выбран по умолчанию, Mainnet требует явного `--mainnet`.
- Реализован постоянный circuit breaker: дневной убыток, просадки от старта/пика, halt-файл, cooldown, ручной reset и журнал точных причин.
- Добавлены portfolio/daily/correlation/order/reserve/loss-streak лимиты, остановка воркеров и отмена BUY.
- CLI стал строгим, добавлена валидация конфликтов и диапазонов, исправлен `--help` исполнителя.
- Удалены placeholder-флаги, реализован `--flatten-force`, сохранены рабочие enforce-флаги.
- Добавлены идемпотентные `clientOrderId`, проверка OCO и периодическая сверка позиций с SQLite.

### Dashboard and operations
- FastAPI закрыт token/proxy-аутентификацией и rate limit; лог API выключен по умолчанию, SSE ограничен.
- Удалено чтение торговых секретов из `/proc`; дашборд принимает только отдельные read-only credentials.
- Дашборд запускается только на `127.0.0.1`, добавлены ротация метрик и hardened systemd units.
- Добавлены `.env.example`, `pyproject.toml`, версионируемые SQLite migrations и ручной `risk_ctl.py`.

### Testing
- Добавлены unit-тесты circuit breaker, DRY gate, strict CLI, Decimal-округления, FIFO, VWAP, миграций и dashboard security.
- Добавлен Decimal-симулятор с комиссиями, проскальзыванием, задержкой, buy-and-hold и walk-forward.

### Restart recovery and Testnet
- Добавлен durable SQLite-журнал order-intents, который записывается до Binance POST и сверяется по `clientOrderId` после неопределённой ошибки или рестарта.
- Partial/FILLED BUY восстанавливаются в очередь контроля; BUY удаляется из неё только после подтверждённого OCO или fallback SELL.
- Ошибка защиты позиции создаёт persistent circuit halt с точной причиной и идентификаторами ордера.
- OCO переведён с deprecated `/api/v3/order/oco` на актуальный `/api/v3/orderList/oco` с `above*`/`below*` параметрами.
- Добавлен fail-closed `binance_testnet_smoke.py`: public/auth/order-test и настоящий create-query-cancel Testnet LIMIT с отдельным подтверждением.
- Добавлены подтверждаемые `buy-oco` и `buy-oco-restart`: ограниченный MARKET BUY, durable intent, OCO verification, повторное открытие journal и обязательный cleanup тестовой позиции.
- Добавлен изолированный `circuit-drill`, проверяющий сохранение halt после restart и ручной reset без изменения production state.

## [2025-09-26]
### Executor (1.8_autosize_universal.py)
- Добавлен VWAP-guard: `--buy-vwap-premium` блокирует покупки, если цена ушла выше VWAP.
- Появились адаптивные капы на скидках к VWAP (`--buy-vwap-discount`, `--buy-vwap-discount-scale`).
- Настраиваемое окно/интервал VWAP (`--buy-vwap-interval`, `--buy-vwap-window`) работает совместно с существующими EMA/ATR, а в логи добавлен вывод ratio `now/VWAP`.

### Supervisor (ai_supervisor.py)
- Пробрасывает VWAP-настройки в дочерние воркеры (`--child-buy-vwap-*`).
- Добавлен режим `--child-buy-vwap-auto` для динамического пересчёта премии/scale по направлению и ATR.
- Реализован фоновый `--vwap-refresh-sec`: супервизор пересчитывает карты и PnL-автотюн без перезапуска сервисов.
- Параметры VWAP-тюнера (часы, threshold, alpha) настраиваются через CLI/ENV и обновляются на лету.

### Конфигурация (key_start_bot.txt)
- Добавлены переменные окружения BUY_VWAP_* и соответствующие параметры запуска сервиса, включая коэффициенты автоподстройки.
- Вместо прямого вызова генератора теперь используется `update_vwap_env.py`, который формирует карты и (опционально) подключает autotune.

### Утилиты
- Добавлен скрипт `gen_vwap_env.py` для генерации BUY_VWAP_* карт на основе свежих данных с биржи.
- Добавлен тюнер `gen_vwap_autotune.py`, корректирующий премии/скидки по PnL статистике.
- Новый комбинированный драйвер `update_vwap_env.py` собирает базовые карты и, при необходимости, подмешивает autotune.
- Исправлен расчёт тюнера: PnL считается по FIFO из таблицы `trades` (миллисекундные таймстемпы), чтобы исключить пустые выборки и кривые значения.

## [2025-09-21]
### Executor (1.8_autosize_universal.py)
- Добавлены тренд-фильтры для BUY: `--buy-trend-ema-gap`, `--buy-trend-interval`, `--bear-skip-buys`, `--bear-cap-scale`, `--bear-buy-shift-pct`.
- Новый флаг `--skip-buy-while-panic` и `--panic-sell-floor-pct` для более агрессивной защиты в режиме паники.
- Переработаны лестничные покупки: смещение уровней вниз при падении рынка и динамическое снижение CAP без изменения поведения по умолчанию.

### Supervisor (ai_supervisor.py)
- Добавлен guard против ночного flatten ниже средней (`--flatten-avoid-loss`, `--flatten-min-edge-pct`, `--flatten-avg-*`).
- Передача новых флагов дочернему воркеру (`--child-skip-buy-while-panic`, трендовые и panic-параметры).
- Реализован кэш средней цены позиции для guard'ов flatten.

## [2025-09-07]
### Executor (1.8_autosize_universal.py)
- Добавлены backoff+повторы на ошибки 418/429/5xx и коды -1003/-1015.
- Подпись приватных запросов (account/openOrders/order/myTrades).
- Улучшен `get_price()` с fallback на альтернативные источники.

### Supervisor (ai_supervisor.py / ai_plan_runner.py)
- Реализованы `startup_cleanup_orders()` и `smart_cleanup_orders()` (TTL + off-ladder очистка).
- Контроль нетто-позиции: reduce-only, auto-flat к 23:55, частичное сокращение.
- Динамический CAP (floor/ceil, alloc-pct) от свободного USDT.
- Генерация `/run/mybot/dynamic.env` через `auto_ladder_map.py`.

### PnL и статистика (pnl_reporter.py, pnl_24h.py, tools_stats.py)
- Добавлен net PnL (после комиссий), win rate, avg_sell_notional в summary.
- Поддержка двух методов подсчёта: `cash` и `realized` (FIFO).
- SQLite: включён WAL + busy_timeout для устойчивости.
- Комиссии нормализованы в USDT.

### Dashboard (index.html)
- KPI (температура, память, swap, диск, сервисы, сеть, аптайм).
- Графики CPU/температуры/памяти (24ч).
- Сводка торговли за 24ч: сделки, объём, комиссии, net, equity, активы.
- Таблица исполненных ордеров за 24ч (комиссии в USDT, форматирование).
- Онлайн-логи через SSE.

### Документация (readme.html, help.html)
- Раздел «Что нового»: толстые ордера v1.8, Auto-CAP, Smart cleanup, режим x10, Pi Dashboard.
- Полный справочник CLI-флагов (MA/ATR/TTL/Auto-CAP/риски).
- Добавлена шпаргалка (1 стр.) с быстрым стартом и env.
- В help.html: описание API (summary/filled/symbols), бэкапы и восстановление.

### Сервис (systemd unit mybot.service)
- SMART-режим с интервалом 150с.
- Circuit breaker по equity (halt-файл при просадке).
- ATR-адаптация (dev-buy, min-profit).
- EMA-фильтры против чейзинга.
- Позиционный guard (лимиты base/USDT per symbol).
- Auto-ladder с JSON-preset и генерацией env.
- Watchdog v3 для авто-перезапуска при сетевых сбоях.

### Прочее
- `migrate_indexes.py` — миграция индексов SQLite.
- Ключи Binance подтягиваются из `.env` или окружения systemd.
- Добавлена справка по smoke-тесту и проверкам (`bot-local-check.sh`).
