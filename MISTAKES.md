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
