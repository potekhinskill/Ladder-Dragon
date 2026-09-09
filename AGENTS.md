# Ladder Dragon project rules

These rules apply to every repository change and every Raspberry Pi update.

## Before editing

- Read this file and the nearest `AGENTS.md` instructions.
- For behavior changes, contract changes, or unfamiliar components, use the [learning index](docs/AGENT_WORKFLOW.md) to select relevant context.
- Read affected contracts and applicable lessons; expand history searches when dependencies or unresolved questions require them.
- Typographical, formatting, and link corrections do not require the index or learning-history searches.
- Historical learning entries explain prior decisions; they do not override current project rules.
- When writing documentation or resolving language uncertainty, consult the relevant sections of `docs/TECHNICAL_ENGLISH.md`; typo fixes need no full reread.
- Check `git status` and preserve user changes.
- Locate tests and contracts relevant to the change. Inspect migrations, systemd units, and configuration examples when affected.
- Never read or print values from `.env`, keys, tokens, or backups.

## Work scope and completion

- State the agreed work boundary and completion checks before implementation.
- Continue implementation, related corrections, and verification within that boundary without requesting approval for every file.
- Stop for missing authority, conflicting user changes, or a decision that materially expands scope.
- Audit requests remain read-only unless implementation is also requested.
- Report local completion separately from publication, deployment, and trading readiness.

## Git and changelog

- Keep `main` as the only branch published to GitHub. Work on a local,
  temporary `ladderdragon/*` branch, but never push that branch to `origin`.
  Publish only within current explicit user authorization, after required verification.
  Follow [the release procedure](docs/RELEASING.md) when preparing commits, versions, tags, publication, or local branch cleanup.
- An exceptional remote branch needs explicit authorization and a recorded reason; delete it after integration or rejection.
- Keep GitHub's automatic merged-branch deletion enabled and an active ruleset
  that blocks creation of every branch except `main`.
- Keep one logical change set per atomic commit.
- Do not use destructive commands (`reset --hard`, `checkout --`) without an explicit request.
- Functional, security, schema, deployment, and dashboard changes require dated changelog entries with actual test results in the same commit.
- `## [Unreleased]` is forbidden.
- The release continuity gate is mandatory.
- Never publish when `release_continuity` is `BLOCKED`; published releases remain immutable.
- Passing tests prove readiness, not permission to push or update Raspberry Pi.
- Before each publication or deployment, verify that the action and target remain within current explicit user authorization.
- Derive the GitHub repository name from the configured `origin` before each `gh` command.
- Never reconstruct repository names or commit identifiers manually.

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
- AI/Risk/Executor changes must run related unit and regression tests, including restart,
  partial fill, OCO/STOP, gap, and idempotency scenarios.
- Add fail-closed regressions when changing validation, financial decisions, or execution authority.
- Add secret-leakage tests when changing sensitive data handling or exposure boundaries.
- Add no-look-ahead tests when changing temporal data, causal cutoffs, prediction, replay, or evidence selection.
- Write comments for major nodes and dangerous financial decisions in English.

## Verification by change type

- During iteration, run affected tests through `.venv/bin/python`; focused results are not a full verification PASS.
- For documentation-only changes, check Technical English, changed links, and affected documentation contracts; full compilation and tests are not required.
- For agent-guidance changes, also run affected workflow and skill validation checks.
- Classify executable examples, safety contracts, configuration, and generated assets by their effects, not their filename extension.
- For code or operational behavior changes, complete compileall, the full suite, and all five safety audits before declaring completion.
- Apply the stricter category to mixed change sets; report documentation checks separately from earlier code verification.
- Every release requires the complete `release` profile on the unchanged signed candidate, including documentation-only releases.
- Keep `local`, `release`, and continuous integration comprehensive; never add filters, optional safety checks, or focused PASS artifacts.
- Disable dotenv loading during local checks. Use isolated synthetic state and inspect runtime adapters before tests with uncertain side effects.
- Keep the candidate unchanged during verification; after code corrections, rerun required completion checks.
- Check `git diff --check` before handoff. Run tests for read-only audits only when needed to establish findings.

## Documentation language

- Follow the English writing profile in `docs/TECHNICAL_ENGLISH.md`, including sentence limits and exact-evidence exceptions.
- Run `.venv/bin/python -m bin.check_technical_english` before each commit that
  changes documentation.

## Learning records

- After a successful solution is validated, add a concise reusable decision to
  `DECISIONS.md` when it establishes a new invariant or workflow. Do not copy
  routine changelog entries.
- Record significant or recurring agent-caused failures in `MISTAKES.md` within the same logical change set.
- Include safety defects, misleading conclusions, lost evidence, failed releases, and substantial avoidable rework; omit isolated, harmless corrected slips.
- A mistake entry must state impact, root cause, correction, and prevention.
  Recording only the symptom is not sufficient.
- Link a new cross-cutting invariant from the learning index when it changes future work; preserve historical entries.
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
