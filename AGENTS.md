# Ladder Dragon project rules

These rules apply to every repository change and every Raspberry Pi update.

## Before editing

- Read this file and the nearest `AGENTS.md` instructions.
- Check `git status` and preserve user changes.
- Locate related tests, migrations, systemd units, `.env.example` files, and docs.
- Never read or print values from `.env`, keys, tokens, or backups.

## Git and changelog

- Work on a `ladderdragon/*` branch; keep one logical change set per atomic commit.
- Do not use destructive commands (`reset --hard`, `checkout --`) without an explicit request.
- Every functional, security, schema, deployment, or dashboard change must have a
  `CHANGELOG.md` entry in the same commit.
- A changelog entry must include the date, a category (`Added`, `Changed`, `Fixed`,
  `Security`, or `Verified`), and the actual test result.
- A task is not complete when code changed without a matching changelog entry.
- `## [Unreleased]` is forbidden. Put each change immediately in a dated section
  named `## [X.Y.Z] — YYYY-MM-DD`.
- Bump `__version__` in `product_version.py` for every changelog entry and verify
  that `^## [Unreleased]` is absent before committing.
- Push only after tests; report the commit SHA and Raspberry update command.

## Security and execution modes

- DRY/Testnet are the defaults. LIVE requires explicit `BOT_LIVE_CONFIRMED=YES`,
  a printed final configuration, and a reviewed maximum exposure.
- The dashboard uses a separate read-only Binance API key without `TRADE` or withdrawal permissions.
- Secrets must never appear in Git, prompts, argv, logs, telemetry, plaintext backups,
  or public HTTP responses.
- If the database, clock synchronization, exchange filters, market data freshness,
  or position protection is invalid, trading must fail closed.
- AI or a manual fallback must not bypass the circuit breaker, halt file, portfolio CAP,
  USDT reserve, daily loss, or gap-risk controls.

## AI and RAG

- AI is advisory only: it receives no order tools, keys, full balances, or ability to
  create or cancel orders.
- Every AI response passes a strict JSON schema, range checks, confidence threshold,
  and Risk Manager. API errors, low confidence, or a damaged control file return to
  the deterministic strategy.
- `SHADOW` never changes the trading plan; `APPLY` requires separate approval and a statistical gate.
- RAG may use only verified real closures with fills and net PnL. Virtual estimates,
  future data, and look-ahead are forbidden.
- Every retrieval is linked to `decision_id`; missing context safely means empty retrieval
  and deterministic fallback.
- RAG never fine-tunes DeepSeek and cannot modify Risk Manager.

## Code, data, and tests

- Use `Decimal` for money, prices, quantities, fees, and PnL whenever a value affects
  a decision or execution; do not add new financial calculations using float.
- Catch specific exception types and emit structured messages; never hide a fallback reason
  without a safe diagnostic event.
- Version SQLite schema changes with migrations; do not delete historical data outside retention policy.
- After changes run at least `python3 -m compileall -q .` and `PYTHONPATH=. pytest -q`.
- AI/Risk/Executor changes must run related unit and regression tests, including restart,
  partial fill, OCO/STOP, gap, and idempotency scenarios.
- New logic needs a fail-closed test and a test proving no secret or look-ahead leakage.
- Write comments for major nodes and dangerous financial decisions in English.

## Raspberry Pi deployment

- Update only with `deploy/update_raspberry_pi.sh update <40-char-SHA>`.
- Before updating, preserve service state and an encrypted backup; never replace `.env`
  or `.env.dashboard` with Git content.
- After updating, check `mybot`, `pi-healthd`, heartbeat, `/api/health`, `/api/ai/status`,
  protected logs, and the actual execution mode.
- Any deployment/systemd/nginx change must also be recorded in the changelog and tests.
