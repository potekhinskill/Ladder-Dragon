# Engineering mistakes and root causes

Read this file before changing the repository. Add an entry whenever an agent
decision causes a defect, unsafe state, failed release, misleading output, or
avoidable rework. Identify the root cause rather than recording only the
symptom. Keep entries concise and exclude secrets, balances, account data, and
private infrastructure details.

## Entry format

### YYYY-MM-DD — Short failure title

- **Impact:** what failed or became misleading.
- **Root cause:** the controllable reason the decision failed.
- **Correction:** what fixed the immediate problem.
- **Prevention:** the rule or test that must stop recurrence.

## Mistakes

### 2026-07-28 — Audited only the outer extracted function scope

- **Impact:** two holdings safety tests failed because a nested rounding helper
  could not resolve `price_round_mode`.
- **Root cause:** dependency discovery inspected the outer function symbol table
  but did not recursively include its nested function scopes.
- **Correction:** inject the missing rounding policy and rerun worker safety
  tests.
- **Prevention:** dependency audits for extracted functions must recurse through
  every child symbol table before the first behavior run.

### 2026-07-28 — Searched package imports but missed a bin-to-bin dependency

- **Impact:** the first complete no-facade suite stopped during Testnet soak
  monitor collection.
- **Root cause:** the migration search covered `ladder_dragon` and tests first,
  but did not audit one production command importing another command module.
- **Correction:** import Testnet client contracts from their owning
  verification package and rerun full collection and tests.
- **Prevention:** before deleting a facade, search the entire repository for
  both absolute and relative references to its module path.

### 2026-07-28 — Set the worker budget before the final import line

- **Impact:** the first complete 2.20.67 suite had one architecture failure.
- **Root cause:** the line budget was measured before adding the service import
  that completed the wrapper wiring.
- **Correction:** set the budget to the final measured 2835 lines and rerun the
  complete suite.
- **Prevention:** measure budgeted modules only after all wiring and formatting
  changes are complete.

### 2026-07-28 — Extracted annotated worker code without postponed annotations

- **Impact:** the first worker contract run failed during module import before
  any test or trading path executed.
- **Root cause:** the extracted service retained runtime-only annotation names
  but did not carry over `from __future__ import annotations` from its source
  module.
- **Correction:** postpone annotation evaluation in the service and rerun the
  full worker compatibility set.
- **Prevention:** every mechanical function extraction must preserve module
  future imports before its first compile and collection check.

### 2026-07-28 — Repeated synthetic SHA and guessed harness option

- **Impact:** the first post-amend release harness exited before verification,
  so the commit could not be published on that attempt.
- **Root cause:** the command embedded the visible abbreviated commit prefix
  with zero padding and guessed `--json-out` instead of reading the parser
  output and using its documented `--output` option.
- **Correction:** record the failure, amend again, capture the new exact SHA
  from `git rev-parse HEAD`, and pass it unchanged with `--output`.
- **Prevention:** build release commands only after `--help`; never type,
  expand, or reuse a commit identifier manually.

### 2026-07-28 — Rewrote injected dependency names inside string keys

- **Impact:** two targeted risk reconciliation tests bypassed their patched
  accounting adapter and opened an incomplete fixture database directly.
- **Root cause:** a bulk identifier rewrite also changed quoted runtime mapping
  keys, although compatibility keys must retain the original global names.
- **Correction:** restore exact runtime keys and inject the patched daily
  metrics loader explicitly; rerun supervisor recovery tests.
- **Prevention:** after mechanical extraction, compare every dependency key
  against the source module symbol table before running behavior tests.

### 2026-07-28 — Put literal Cyrillic inside the English-source test

- **Impact:** the complete suite failed because the new detector's own regex
  contained literal Cyrillic range characters.
- **Root cause:** a new source-language test was added without first locating
  the existing repository-wide English-source regression and matching its
  Unicode-escape representation.
- **Correction:** express the Cyrillic block as `\\u0400-\\u04ff`, preserving
  detection while keeping the test source itself English-only.
- **Prevention:** search existing policy tests before adding a parallel guard;
  source scanners must satisfy the same policy they enforce.

### 2026-07-28 — Added docstrings without updating raw line budgets

- **Impact:** the first targeted documentation regression failed because six
  coordinator files exceeded their exact non-growth budgets by the newly added
  docstring lines.
- **Root cause:** the source-language change treated comments as behavior-free
  but overlooked that the architecture gate intentionally counts every line.
- **Correction:** raise each affected budget only to its exact documented line
  count, with no spare capacity, and rerun the architecture suite.
- **Prevention:** whenever comments or docstrings touch a budgeted monolith,
  update the exact budget in the same patch or extract enough code to keep the
  raw count below the existing limit.

### 2026-07-28 — Typed a synthetic SHA instead of resolving HEAD

- **Impact:** a candidate harness command received a wrong 40-character
  `--expected-sha`; the run exposed that the option was not enforced.
- **Root cause:** the command manually padded an abbreviated SHA rather than
  using the exact `git rev-parse HEAD` result already printed by the preceding
  command.
- **Correction:** enforce exact checkout matching inside evidence validation
  and rerun with the real full SHA.
- **Prevention:** derive immutable identifiers programmatically and make every
  verification option that claims an expected identity a mandatory equality
  gate.

### 2026-07-28 — Moved implementations without updating source-contract tests

- **Impact:** the first architecture regression run failed because a deployment
  test still searched the thin compatibility facade for configuration defaults,
  and new production modules lacked the required purpose header.
- **Root cause:** the move preserved runtime imports but did not inventory tests
  that deliberately inspect source ownership and repository metadata.
- **Correction:** point the contract test at the packaged implementation and
  add complete production headers to every new module and facade.
- **Prevention:** every module move must search for both imports and raw path
  references, then run source-contract tests alongside runtime regressions.

### 2026-07-28 — Extended a journal contract without preserving test doubles

- **Impact:** two protection regressions initially halted with `AttributeError`
  because lightweight journal doubles did not implement the new partial-exit
  query.
- **Root cause:** the integration called the new method unconditionally even
  though the protection boundary intentionally supports minimal journal
  substitutes in isolated safety tests.
- **Correction:** feature-detect the optional query and treat its absence as
  zero historical partial exits; the production journal still supplies the
  authoritative implementation.
- **Prevention:** when extending a dependency protocol, inspect its test doubles
  and either update all of them or add an explicit backward-compatible default.

### 2026-07-28 — Invented the suffix of an expected commit SHA

- **Impact:** the first release-harness process was started with an incorrect
  40-character `--expected-sha` and had to be interrupted before artifact
  generation.
- **Root cause:** the seven-character SHA printed by `git commit` was expanded
  manually instead of copying the authoritative `git rev-parse HEAD` output.
- **Correction:** record the mistake, amend once more, then pass only the exact
  full SHA returned after the final commit.
- **Prevention:** never construct, autocomplete or reuse a pre-amend SHA;
  capture `git rev-parse HEAD` after the final commit and copy it verbatim into
  verification and deployment commands.

### 2026-07-28 — Split tests by stale line numbers

- **Impact:** the first component-test split produced three syntax/indentation
  collection errors because two cuts landed inside functions and one copied an
  incomplete multiline import.
- **Root cause:** line numbers from the pre-helper-extraction audit were reused
  after the files had already changed.
- **Correction:** exactly rejoined the affected fragments, discovered current
  top-level `def` boundaries, split again there, and verified all 211 original
  tests were collected and passed once.
- **Prevention:** mechanical source splits must use current AST/top-level
  boundaries and run `pytest --collect-only` before executing tests or deleting
  any source fragment.

### 2026-07-28 — Used the host Python for a project smoke check

- **Impact:** the first supervisor version smoke stopped on a missing
  dependency before it could exercise the moved CLI.
- **Root cause:** the command used system `python3` instead of the repository's
  `.venv/bin/python`.
- **Correction:** reran the command with the project virtual environment and
  verified the compatibility CLI successfully.
- **Prevention:** use `.venv/bin/python` for every executable smoke and pytest
  command unless a matrix test explicitly selects another interpreter.

### 2026-07-28 — Guessed prediction test filenames repeatedly

- **Impact:** two prediction verification commands exited before collecting
  tests; no source or runtime state was changed.
- **Root cause:** nonexistent archive/walk-forward filenames were appended
  after discovery output instead of selecting only paths returned by
  `rg --files tests`.
- **Correction:** ran the two discovered prediction/re-anchor test files and
  then the complete project suite.
- **Prevention:** construct every multi-file pytest command solely from the
  current `rg --files tests` output; do not add inferred names afterward.

### 2026-07-28 — Repeated a guessed-test-path mistake

- **Impact:** a related-test command stopped without executing because
  `tests/test_executor_orders.py` was guessed but does not exist.
- **Root cause:** the test list was composed before applying the repository's
  existing lesson to discover paths with `rg --files`.
- **Correction:** discovered the actual execution test files and reran the
  complete targeted set successfully.
- **Prevention:** run `rg --files tests` before every multi-file pytest command;
  do not rely on module-to-test filename inference.

### 2026-07-28 — Backfill parsed exchange payload keys instead of stored keys

- **Impact:** the first schema-v2 migration regression failed because historical
  `verified_legs` metadata uses normalized snake-case keys, while the migration
  accepted only Binance camel-case payload keys.
- **Root cause:** the new backfill reused an input sanitizer without checking
  the actual persisted representation produced by that sanitizer.
- **Correction:** accept both the exchange input shape and the normalized
  historical shape, then persist one canonical representation.
- **Prevention:** migration tests must start from the previous on-disk
  representation, not only from current API-shaped fixtures.

### 2026-07-28 — Treated the MARKET journal sentinel as a numeric price

- **Impact:** two MARKET-order safety regressions failed before submission
  because journal deduplication tried to parse the `MARKET` marker as Decimal.
- **Root cause:** numeric canonicalization was applied to every `price` field
  without first checking the established contract for price-less market orders.
- **Correction:** preserve `MARKET` as a strict non-financial sentinel and use
  Decimal comparison for every actual price.
- **Prevention:** inspect all callers and include LIMIT plus MARKET contract
  tests whenever a shared order-field invariant changes.

### 2026-07-28 — Assumed a recovery test filename instead of discovering it

- **Impact:** the first targeted verification command stopped before running
  tests because `tests/test_executor_recovery.py` does not exist.
- **Root cause:** the command inferred a filename from the module name instead
  of selecting it from `rg --files tests`.
- **Correction:** use the existing `tests/test_worker_order_recovery.py` and
  rerun the complete targeted set.
- **Prevention:** discover test paths with `rg --files` before composing a
  multi-file pytest command.

### 2026-07-28 — Bumped the canonical version without updating README

- **Impact:** targeted version and deployment-documentation tests failed because
  README still advertised 2.20.61 while the candidate was 2.20.62.
- **Root cause:** the version bump patch updated `product_version.py` and
  `CHANGELOG.md` but treated README links as a separate concern and missed both
  public version surfaces.
- **Correction:** synchronize both README declarations with the canonical
  version before committing.
- **Prevention:** change all three version surfaces in one patch and run
  `tests/test_product_version.py` immediately after every bump.

### 2026-07-28 — Tried to verify the final version before publishing intermediates

- **Impact:** the 2.20.60 release harness returned `BLOCKED` even though its code
  tests passed.
- **Root cause:** the candidate was checked directly against published 2.20.56
  while signed 2.20.57 through 2.20.59 commits had not yet received tags.
- **Correction:** verify, tag, push, wait for CI, and publish each version in
  order.
- **Prevention:** never run or publish a later release as a substitute for its
  unpublished direct predecessors.

### 2026-07-28 — Used one brittle patch for several documentation files

- **Impact:** the documentation update failed to apply and had to be retried.
- **Root cause:** one patch coupled many files to an exact README line wrap, so
  one stale context invalidated the entire change.
- **Correction:** split the update into small file-scoped patches and inspect
  each diff.
- **Prevention:** use narrow patches for independent documents, especially
  large frequently edited Markdown files.

### 2026-07-26 — Published dashboard HTML without required style assets

- **Impact:** nginx returned 404 for dashboard CSS and JavaScript, leaving an
  unstyled, partially unusable page while the backend remained healthy.
- **Root cause:** post-deployment readiness checked the service and HTML but did
  not prove that every static asset from the same release was installed.
- **Correction:** restore the missing files and add exact asset publication and
  hash verification.
- **Prevention:** a missing or mismatched HTML, CSS, JavaScript, vendor, locale,
  or image asset must block deployment.

### 2026-07-25 — Allowed a test to inherit the production HALT path

- **Impact:** a fake-canary test on the Raspberry Pi wrote its expected halt
  state to the real control file and could block new BUYs.
- **Root cause:** the test process inherited the production `CB_HALT_FILE`
  environment instead of forcing an isolated temporary path.
- **Correction:** bind test halt state to a temporary path and keep fake clients
  isolated from live control files.
- **Prevention:** environment-dependent safety tests must explicitly override
  every mutable runtime path and assert that production paths are untouched.

### 2026-07-24 — Let SHADOW expectancy change worker behavior

- **Impact:** a mode documented as observation-only raised the effective SELL
  profit floor, contaminating SHADOW evidence with applied behavior.
- **Root cause:** `BOT_REQUIRED_EDGE_PCT` was exported to the worker without
  checking whether expectancy mode was `APPLY`.
- **Correction:** export execution-changing expectancy only in approved APPLY;
  retain fee evidence in SHADOW without modifying the plan.
- **Prevention:** every SHADOW boundary needs a regression proving identical
  execution output to the baseline.
