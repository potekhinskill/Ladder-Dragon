# Architecture state and policy map

Status: partial P0 inventory, implemented locally.

The machine-readable map is `schemas/architecture_reference_map.json`.
It records 18 store families and seven existing policy sources.
These references identify review locations, not exclusive writers or execution permissions.
Data classes describe families; mixed families still require record-level classification.
Retention authority remains in [Data retention](DATA_RETENTION.md).

## Store review locations

Paths below are relative to `ladder_dragon/`.
The manifest contains concrete function anchors for each location.

| Family | Current source | Class | Review phase |
|---|---|---|---|
| Trades and inventory | `execution/tools_stats.py` | Mixed | P3 |
| Inventory lots | `execution/inventory_lots.py` | Authoritative | P3 |
| Order journal | `execution/order_recovery.py` | Authoritative | P4 |
| Risk state | `risk/risk_manager.py` | Authoritative | P4 |
| Protection state | `execution/protection/breakeven.py` | Authoritative | P4 |
| Advisor decisions | `ai/context/runtime.py` | Mixed | P5 |
| Unresolved fills | `ai/unresolved_fills.py` | Authoritative | P5 |
| Knowledge | `ai/ai_knowledge.py` | Mixed | P5 |
| Prediction store | `strategy/prediction/runtime.py` | Mixed | P5 |
| Episode evidence | `strategy/prediction/episode_evidence.py` | Mixed | P5 |
| Selection evidence | `strategy/prediction/entry_diagnostics.py` | Mixed | P5 |
| Experiment lifecycle | `strategy/prediction/experiment_lifecycle.py` | Authoritative | P5 |
| Champion registry | `strategy/prediction/champion_registry.py` | Authoritative | P5 |
| Champion probation | `supervision/champion_probation.py` | Authoritative | P4 |
| Context journal | `strategy/prediction/context_journal.py` | Derived | P5 |
| Market scenarios | `market_analysis/store.py` | Derived | P3 |
| Validation batches | `verification/live/validation_batch.py` | Authoritative | P0 |
| Database migrations | `persistence/migrations.py` | Authoritative | P6 |

No classification grants deletion rights.
Authoritative fills, unresolved records, order intents, and lifecycle evidence remain protected by existing retention rules.
Encrypted archives remain on the external disk; this inventory never reads their contents.

## Existing policy sources

The map references policy definitions without duplicating their values.
Existing safety audits remain authoritative for their respective contracts.

| Policy | Source | Review objective |
|---|---|---|
| Exchange mutations | `bin/audit_exchange_boundaries.py` | Preserve approved adapters during extraction. |
| Critical guards | `bin/audit_guard_contracts.py` | Preserve fail-closed checks. |
| Authority calls and bindings | `bin/audit_execution_authority_paths.py` | Preserve invocation order, cadence, and provenance. |
| Numeric budgets | `ladder_dragon/verification/numeric_boundaries.py` | Reduce legacy numeric boundaries without widening allowances. |
| Semantic owners | `bin/audit_semantic_authorities.py` | Preserve canonical financial calculations. |
| Runtime budgets | `tests/test_architecture_layout.py` | Reduce existing monoliths. |
| Test budgets | `tests/test_architecture_layout.py` | Move tests with their component contracts. |

These policies are not interchangeable with architectural exceptions.
The exception inventory must distinguish safety permissions from temporary structural debt.
New modules do not acquire mutation authority through this map.

## Harness enforcement

Run `.venv/bin/python -m bin.audit_architecture` for both ownership and reference reports.
Local and release profiles require `architecture_references` alongside `architecture_ownership`.
Missing or duplicate anchors fail verification.
Invalid manifests, unsafe paths, and unreadable sources block verification.
Reports contain source and syntax hashes, not source bodies.
Hash changes are observations, not automatic approval or rejection of policy changes.
The analyzer does not import application modules or read runtime databases.

## Remaining P0 work

Record transaction boundaries and every writer before claiming exclusive store ownership.
Inventory command contracts, deployed assets, dynamic dependencies, and remaining architectural exceptions.
Resolve the complete import graph before introducing cycle and capability rules.
Add mutation tests for each new harness rule before marking its plan requirement complete.
Update this map and canonical references during each later extraction.
Do not move trading behavior merely to satisfy directory naming.

See [Architecture evolution plan](ARCHITECTURE_EVOLUTION_PLAN.md) for phase dependencies and completion criteria.
