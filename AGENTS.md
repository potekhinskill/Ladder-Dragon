# Ladder Dragon project rules

These rules apply to every repository change and every Raspberry Pi update.

## Before editing

- Read this file and the nearest `AGENTS.md` instructions.
- Read `DECISIONS.md` and `MISTAKES.md` completely before making changes.
- Read `docs/TECHNICAL_ENGLISH.md` before you write or change documentation.
- Check `git status` and preserve user changes.
- Locate related tests, migrations, systemd units, `.env.example` files, and docs.
- Never read or print values from `.env`, keys, tokens, or backups.

## Git and changelog

- Keep `main` as the only branch published to GitHub. Work on a local,
  temporary `ladderdragon/*` branch, but never push that branch to `origin`.
  After verification, fast-forward the reviewed commit to `origin/main` and
  delete the local temporary branch.
- Do not create remote feature, release, agent, Dependabot, or compatibility
  branches. If an exceptional remote branch is explicitly authorized, record
  why it is necessary and delete it immediately after integration or rejection.
- Keep GitHub's automatic merged-branch deletion enabled and an active ruleset
  that blocks creation of every branch except `main`.
- Keep one logical change set per atomic commit.
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
- The release continuity gate is mandatory.
- A candidate must be the direct next Semantic Version from the signed baseline.
- A branch tip can increase the version only once.
- Each published release must have one annotated tag on a linear ancestor of `main`.
- Do not push a release when `release_continuity` is `BLOCKED`. Its verification
  artifact is the release manifest and must list the previous SHA, current SHA,
  and every included commit.
- Push only after tests; report the commit SHA and Raspberry update command.
- Derive the GitHub repository name from the configured `origin` before each `gh` command.
- Do not type or reconstruct the GitHub repository owner and name manually.

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
- Untrusted HTTP response bodies must be streamed with a strict decoded-byte
  ceiling before JSON parsing; never rely only on provider token limits.
- Validate and quote every SQLite identifier before interpolation. Dynamic
  migration declarations must use an explicit narrow grammar.
- Version SQLite schema changes with migrations; do not delete historical data outside retention policy.
- Classify each new persistent record as authoritative, derived, or disposable.
  Define its growth limit, retention period, archive dependency, and scheduled
  maintenance in the same change. Never auto-delete accounting, fills, FIFO,
  unresolved state, order intents, or lifecycle evidence. Archive eligible
  derived data only after a recent verified encrypted backup. Add tests that
  prove pending and protected records survive retention.
- After changes run at least `python3 -m compileall -q .` and `PYTHONPATH=. pytest -q`.
- AI/Risk/Executor changes must run related unit and regression tests, including restart,
  partial fill, OCO/STOP, gap, and idempotency scenarios.
- New logic needs a fail-closed test and a test proving no secret or look-ahead leakage.
- Write comments for major nodes and dangerous financial decisions in English.

## Documentation language

- Write English technical documentation with the project ASD-STE100 profile in
  `docs/TECHNICAL_ENGLISH.md`.
- Use no more than 20 words in an instruction.
- Use no more than 25 words in a descriptive sentence.
- Use one term for one meaning. Define each uncommon abbreviation.
- Preserve commands, identifiers, legal text, locale text, and historical
  evidence exactly when their exact form is necessary.
- Run `.venv/bin/python -m bin.check_technical_english` before each commit that
  changes documentation.

## Learning records

- After a successful solution is validated, add a concise reusable decision to
  `DECISIONS.md` when it establishes a new invariant or workflow. Do not copy
  routine changelog entries.
- Identify the root cause when an agent decision causes a defect or avoidable rework.
- Add a concise entry to `MISTAKES.md` in the same logical change set.
- A mistake entry must state impact, root cause, correction, and prevention.
  Recording only the symptom is not sufficient.
- Never place secrets, private endpoints, balances, account identifiers, or raw
  production evidence in either learning file.

## Raspberry Pi deployment

- Update only with `deploy/update_raspberry_pi.sh update <40-char-SHA>`.
- The Pi verification profile must compare deployed HEAD, the PASS release
  artifact, the reviewed GitHub SHA, and the fetched upstream SHA exactly.
- Before updating, preserve service state and an encrypted backup; never replace `.env`
  or `.env.dashboard` with Git content.
- After updating, check `mybot`, `pi-healthd`, heartbeat, `/api/health`, `/api/ai/status`,
  protected logs, and the actual execution mode.
- Dashboard deployment must verify every published HTML/CSS/JavaScript/vendor
  asset against the exact release checkout. A missing or hash-mismatched asset
  blocks deployment and the Pi verification profile.
- Any deployment/systemd/nginx change must also be recorded in the changelog and tests.
