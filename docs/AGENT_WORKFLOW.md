# Agent workflow and learning index

This index routes affected components to contracts and historical lessons.
General permissions, completion rules, and safety requirements belong in [AGENTS.md](../AGENTS.md).

## Task routing and learning index

Use applicable rows when changing behavior, contracts, or an unfamiliar component.
For simple wording, formatting, or link corrections, work directly with the affected document.
Read relevant sections and complete matching lesson entries, not every linked document.
Search additional history when a dependency or unresolved question requires it; this index is not exhaustive.

| Task boundary | Current contracts | Selected historical lessons |
|---|---|---|
| Execution, risk, protection | [Authorities](DOMAIN_AUTHORITIES.md), [runtime safety](RUNTIME_SAFETY_AND_REPORTING.md) | [Final writer](../DECISIONS.md#2026-09-09--enforce-exact-closure-at-the-final-writer), [all consumers](../MISTAKES.md#2026-09-09--fixed-one-consumer-without-covering-the-final-writer) |
| Accounting, fills, persistence | [State map](ARCHITECTURE_STATE_MAP.md), [retention](DATA_RETENTION.md) | [Complete evidence](../DECISIONS.md#2026-09-09--bind-acknowledgement-and-cursor-progress-to-complete-evidence), [adjacent boundaries](../MISTAKES.md#2026-09-09--stopped-validation-before-adjacent-acceptance-boundaries) |
| Public market data and startup | [Configuration](CONFIGURATION.md), [authorities](DOMAIN_AUTHORITIES.md) | [Signed barrier](../DECISIONS.md#2026-09-05--join-concurrent-public-authorities-at-the-signed-boundary), [transport precision](../MISTAKES.md#2026-09-04--mocked-away-the-lossy-ticker-transport-adapter) |
| Dashboard and reports | [Runtime safety](RUNTIME_SAFETY_AND_REPORTING.md), [surface map](ARCHITECTURE_SURFACE_MAP.md) | [Evidence quality](../DECISIONS.md#2026-09-09--present-evidence-quality-beside-financial-results), [headline uncertainty](../MISTAKES.md#2026-09-09--qualified-an-uncertain-result-only-after-its-headline) |
| Prediction and advisory models | [Authorities](DOMAIN_AUTHORITIES.md), [architecture](ARCHITECTURE.md) | [Causal signal](../DECISIONS.md#2026-09-01--use-one-causal-signal-contract-across-replay-and-live), [training separation](../MISTAKES.md#2026-08-18--mixed-training-rows-into-configuration-selection) |
| Architecture and commands | [Plan](ARCHITECTURE_EVOLUTION_PLAN.md), [command reference](COMMAND_REFERENCE.md) | [Concrete extraction](../DECISIONS.md#2026-09-09--prove-a-command-extraction-with-unchanged-implementation-syntax), [source contracts](../MISTAKES.md#2026-07-28--moved-implementations-without-updating-source-contract-tests) |
| Deployment and systemd | [Release procedure](RELEASING.md), [Pi runbook](RASPBERRY_PI_INSTALL.md) | [Restart scope](../DECISIONS.md#2026-09-06--resolve-service-restart-scope-before-checkout-mutation), [asset verification](../MISTAKES.md#2026-07-26--published-dashboard-html-without-required-style-assets) |
| Documentation and agent instructions | [Technical English](TECHNICAL_ENGLISH.md), this guide | [Executable documentation](../DECISIONS.md#2026-07-31--derive-documentation-contracts-from-executable-interfaces), [unproved claims](../MISTAKES.md#2026-08-16--published-a-constant-as-proof) |

For store changes, also inspect [state ownership](ARCHITECTURE_STATE_MAP.md) and [retention](DATA_RETENTION.md).
For relocated entry points, inspect the [surface map](ARCHITECTURE_SURFACE_MAP.md) and [local artifact boundaries](LOCAL_ARTIFACTS.md).
For financial boundary changes, inspect [domain authorities](DOMAIN_AUTHORITIES.md).
For transport diagnostics, preserve [safe fields and stable alert identity](../DECISIONS.md#2026-09-10--separate-transport-diagnostics-from-provider-exception-text).
For deployment revisions, preserve [the separation from cleanup authority](../DECISIONS.md#2026-09-10--separate-release-revision-from-cleanup-authority).
For offline replay, preserve [input-bound resume](../DECISIONS.md#2026-09-11--resume-only-complete-input-bound-replay-paths) and verify bounded progress on the target host.
Inspect parser declarations before executing unfamiliar commands; even help paths can initialize private state.

## Verification stages

Choose checks through [verification by change type](../AGENTS.md#verification-by-change-type).
Use the [release procedure](RELEASING.md) for candidate verification and publication.
Use the [Pi runbook](RASPBERRY_PI_INSTALL.md) for deployment procedures.

## Policy rationale

See the [change-type decision](../DECISIONS.md#2026-09-09--select-preparation-and-verification-by-actual-change-effects) and [applicability lesson](../MISTAKES.md#2026-09-09--relocated-universal-requirements-instead-of-narrowing-their-triggers).
See the [preparation decision](../DECISIONS.md#2026-09-09--route-preparation-without-weakening-completion-evidence) and [completion lesson](../MISTAKES.md#2026-09-09--treated-individual-extractions-as-task-completion).
Current [learning-record rules](../AGENTS.md#learning-records) govern new entries.
