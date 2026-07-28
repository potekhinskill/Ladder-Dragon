# Engineering decisions

Read this file before changing the repository. Record only decisions that were
validated by tests or production evidence and are likely to be reused. Keep
entries concise; this is not a changelog or an activity log.

## Entry format

### YYYY-MM-DD — Short decision title

- **Context:** the constraint or recurring problem.
- **Decision:** the chosen invariant or workflow.
- **Why it worked:** the evidence that validated it.
- **Reuse:** when future work should apply the same decision.

## Decisions

### 2026-07-28 — Normalize hot journal evidence without deleting audit history

- **Context:** OCO leg lookup and lifecycle telemetry scanned every historical
  metadata JSON document, while automatic retention would remove evidence used
  for recovery, accounting, and LIVE approval.
- **Decision:** store verified legs and exact closures in indexed normalized
  tables, commit multi-row lifecycle transitions atomically, and retain CLOSED
  intents indefinitely instead of deleting them in the runtime.
- **Why it worked:** injected mid-transaction failures roll back every related
  state and metadata write; tests also prove lookup and telemetry remain exact
  when legacy metadata JSON is unreadable.
- **Reuse:** durable journals, ledgers, and approval evidence where hot queries
  must remain bounded without weakening the audit trail.

### 2026-07-28 — Persist reusable agent learning in two focused records

- **Context:** useful fixes and root-cause lessons were scattered across chats,
  changelog entries, and review notes, so later changes could repeat them.
- **Decision:** require every agent to read `DECISIONS.md` and `MISTAKES.md`
  before editing, then record validated reusable choices and agent-caused
  failures in their distinct structured formats.
- **Why it worked:** repository tests enforce both files, their required fields,
  README discoverability, and the instruction in `AGENTS.md`.
- **Reuse:** every repository task; add entries only when a durable lesson
  exists rather than logging routine work.

### 2026-07-28 — Publish every semantic version as a continuous release

- **Context:** intermediate version commits without matching public tags made it
  difficult to prove whether changes were lost between releases.
- **Decision:** require one signed commit, one annotated tag, one PASS manifest,
  and one GitHub Release for every direct semantic successor on linear `main`.
- **Why it worked:** releases 2.20.57 through 2.20.60 were published
  sequentially, and each local/GitHub continuity check passed.
- **Reuse:** every release, including documentation-only releases.

### 2026-07-28 — Isolate exact accounting by symbol

- **Context:** incomplete ETH history blocked an otherwise valid daily report.
- **Decision:** calculate each symbol independently, exclude only symbols whose
  exact FIFO provenance cannot be proved, and never invent an opening lot or
  zero cost basis.
- **Why it worked:** mixed valid/incomplete-symbol regressions preserve exact
  eligible totals and identify exclusions explicitly.
- **Reuse:** financial reports, approval evidence, imports, and dashboard
  aggregations.

### 2026-07-28 — Confirm protection and emergency exits authoritatively

- **Context:** an attempted OCO or MARKET request is not proof that a filled BUY
  is protected or closed.
- **Decision:** accept protection only after verifying both Binance OCO legs;
  accept an emergency flatten only after a complete `FILLED` quantity and a
  durable journal commit.
- **Why it worked:** crossed-price, partial-fill, unknown-outcome, and recovery
  regressions remain fail-closed.
- **Reuse:** every order path that changes position or protection state.

### 2026-07-28 — Keep execution HALT separate from SHADOW observation

- **Context:** stopping execution also stopped the counterfactual evidence
  needed to improve BUY distance and re-anchoring.
- **Decision:** HALT blocks all mutations, while a healthy authenticated risk
  snapshot may still produce non-executing SHADOW observations.
- **Why it worked:** tests prove no worker or order mutation starts while
  advisory evidence continues.
- **Reuse:** experiments that need unbiased observation during a safety block.

### 2026-07-26 — Verify every published dashboard asset by hash

- **Context:** a healthy backend can still leave the dashboard unusable when
  HTML, CSS, JavaScript, or vendor assets are missing from the web root.
- **Decision:** compare every published asset with the exact release checkout
  and block deployment on a missing or mismatched file.
- **Why it worked:** deployment and Pi verification tests now fail closed on a
  missing or changed asset.
- **Reuse:** every static asset, nginx, dashboard, or deployment change.
