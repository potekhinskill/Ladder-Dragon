# Changelog — Ladder Dragon (binance_bot)

Формат версий: [Semantic Versioning](https://semver.org/).

## [2.1.0] — 2026-07-16

### Добавлено
- `executor_planning.py` с чистыми функциями планирования BUY/SELL без HTTP-запросов, ключей и глобального состояния.
- Детерминированный выбор свободных уровней BUY ниже рынка и SELL выше рынка с учётом уже открытых заявок.
- Расчёт размера BUY по доступному quote-балансу, CAP, числу оставшихся слотов, `minQty`, `minNotional` и пользовательскому минимуму заявки.
- SELL guard относительно средней цены входа, минимальной прибыли и разрешённого panic-floor.
- Распределение доступного base-баланса между SELL-уровнями с сохранением биржевой пыли.
- `executor_runtime.py` с отдельным планировщиком времени жизни воркера и проверкой периодических status-тиков.
- Boundary-тесты planning/runtime, не требующие подключения к Binance.

### Изменено
- `autosize_universal.py` использует planning/runtime API и больше не содержит дублирующую математику выбора уровней и размеров заявок.
- Локальный остаток quote/base уменьшается только после подтверждённого ответа размещения; ошибка или отсутствие ACK не расходует баланс внутри текущего плана.
- Мягкая остановка по `RUN` теперь проходит через отдельный runtime scheduler без изменения CLI и торговых defaults.
- Крупные узлы супервизора, исполнителя, риска, transport, order journal, recovery, planning и статистики снабжены русскими архитектурными комментариями.

### Проверено
- Строгий `--help`, `--version` и компиляция модулей.
- Полный набор автоматических тестов: **85 passed**.

## [2.0.2] — 2026-07-16

### Добавлено
- `executor_orders.py` как единая граница размещения LIMIT и OCO.
- `OrderDependencies` для late-bound передачи LIVE-gate, transport, фильтров, форматирования, journal, recovery и circuit halt.
- Тесты, подтверждающие, что DRY-gate проверяется непосредственно перед мутацией и блокирует сеть.

### Изменено
- Идемпотентное создание `clientOrderId`, запись intent до POST и восстановление после неопределённого ACK перенесены из исполнителя в order-модуль.
- OCO placement централизует округление, проверку обеих ног, восстановление существующей защиты и fail-closed halt при неполной защите.
- Публичные функции в `autosize_universal.py` сохранены как совместимые фасады для существующих тестов и операторских сценариев.

## [2.0.1] — 2026-07-16

### Добавлено
- Строгие CLI и их валидация вынесены из торговых циклов в `supervisor_config.py` и `executor_config.py` без изменения флагов и defaults.
- Общие детерминированные расчёты лестниц, EMA, ATR, ADX и panic-сигналов собраны в независимом `strategy_math.py`.
- Подпись запросов, DRY transport gate и retry/backoff исполнителя перенесены в `binance_transport.py` с late-bound LIVE/venue state.
- Импорт исполнений и точная оценка base/quote/BNB-комиссий отделены в `executor_stats.py`.
- Market/account reads вынесены в `executor_market.py`, а query/cancel, проверка OCO и restart recovery — в `executor_recovery.py`.
- Добавлены boundary-тесты, которые проверяют конфигурационные, стратегические, транспортные и статистические интерфейсы без запуска торгового цикла.

### Изменено
- `ai_supervisor.py` и `autosize_universal.py` сокращены за счёт удаления встроенных реализаций CLI, transport, market/recovery, статистики и общей математики.
- Зависимости новых модулей передаются явно или late-bound, поэтому тесты не используют реальные ключи и не выполняют торговые запросы.
- Ошибки отсутствующего ордера Binance обрабатываются как ожидаемый recovery-сценарий, а не как общий сбой API.

## [2.0.0] — 2026-07-16

### Добавлено
- Версия продукта вынесена в единый модуль `product_version.py` и подключена к package metadata, CLI и HTTP User-Agent.
- Основные команды поддерживают `--version`, а supervisor и executor фиксируют версию в startup log.

### Изменено
- Исполнитель переименован из legacy-имени с номером версии в `autosize_universal.py`; обновлены supervisor, runners, systemd, тесты и документация.
- Принят Semantic Versioning: версия файла больше не используется как версия продукта.
- `pyproject.toml` получает версию динамически из `product_version.__version__`, исключая расхождение CLI и package metadata.

### Совместимость
- Все внутренние ссылки на прежнее имя исполнителя заменены; операторский запуск выполняется через новое стабильное имя без номера версии.

## [2026-07-16]
### Supervisor DRY/Testnet hardening
- Исполнитель использует `BOT_RUN_DIR` для per-symbol lock, fallback order journal, circuit halt и breakeven state; локальный запуск больше не зависит от Linux-only `/run/mybot`.
- Добавлен экспоненциальный backoff для быстро падающих дочерних процессов и обязательный terminate/wait/kill cleanup при остановке супервизора.
- `Ctrl+C` завершает супервизор и дочерние процессы штатно, без оставшихся процессов и lock-файлов.
- Настоящий супервизор и исполнитель проверены в DRY на Spot Testnet: фильтры и стратегия загружены, все торговые операции заблокированы DRY-gate.
- Операторские CLI `risk_ctl.py` и `db_migrate.py` загружают локальный `.env`, поэтому используют те же runtime и SQLite пути, что супервизор.
- LIVE всегда трактует `target-buy-per-symbol` как жёсткий максимум; risk-block включает cooldown, а сигнал остановки проверяется непосредственно перед каждым exchange POST.
- Startup и periodic cleanup сохраняют свежие ордера в течение 15-минутного warmup даже при небольшом смещении лестницы, исключая cancel/recreate churn после рестарта.
- После FILLED исполнитель сначала подтверждает защитный OCO, затем немедленно синхронизирует trades/inventory; terminal state BUY сохраняется в durable journal до работы с OCO.
- Строгая сверка позиций получила ограниченный grace/retry для гонки exchange-balance ↔ SQLite и учитывает только неторгуемую пыль в пределах одного `LOT_SIZE` шага.
- Supervisor переключает Testnet на отдельные `BOT_TESTNET_STATS_DB` и `BOT_TESTNET_ORDER_JOURNAL`, поэтому виртуальные сделки не влияют на Mainnet inventory и дневные лимиты.
- `BOT_TESTNET_RUN_DIR` изолирует Testnet circuit halt/state/alerts и lock-файлы; `risk_ctl.py --testnet` управляет только этим контуром.
- Миграция `003` добавляет точные `price/gross_qty/net_qty`, актив и сумму комиссии, quote-оценку и Decimal-поля inventory без удаления старых REAL-колонок.
- `/myTrades` учитывает комиссии в base/quote и оценивает BNB по исторической минутной цене; неизвестная комиссия переводит risk telemetry в fail-closed.
- Inventory, средняя себестоимость, realized PnL, дневные risk-метрики, `pnl_24h.py` и VWAP autotune используют единую Decimal-модель.
- Добавлен read-only `testnet_soak_monitor.py`: длительная проверка лимита BUY/exposure, OCO-защиты, circuit halt и account ↔ SQLite с атомарным JSON-отчётом.
- Реальный Testnet restart drill подтвердил сохранение OCO без дублей; TP исполнился, base/quote комиссии и итоговый inventory совпали с account.

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
### Executor (autosize_universal.py)
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
### Executor (autosize_universal.py)
- Добавлены тренд-фильтры для BUY: `--buy-trend-ema-gap`, `--buy-trend-interval`, `--bear-skip-buys`, `--bear-cap-scale`, `--bear-buy-shift-pct`.
- Новый флаг `--skip-buy-while-panic` и `--panic-sell-floor-pct` для более агрессивной защиты в режиме паники.
- Переработаны лестничные покупки: смещение уровней вниз при падении рынка и динамическое снижение CAP без изменения поведения по умолчанию.

### Supervisor (ai_supervisor.py)
- Добавлен guard против ночного flatten ниже средней (`--flatten-avoid-loss`, `--flatten-min-edge-pct`, `--flatten-avg-*`).
- Передача новых флагов дочернему воркеру (`--child-skip-buy-while-panic`, трендовые и panic-параметры).
- Реализован кэш средней цены позиции для guard'ов flatten.

## [2025-09-07]
### Executor (autosize_universal.py)
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
- Раздел «Что нового»: толстые ордера, Auto-CAP, Smart cleanup, режим x10, Pi Dashboard.
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
