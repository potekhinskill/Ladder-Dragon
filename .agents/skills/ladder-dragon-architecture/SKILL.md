---
name: ladder-dragon-architecture
description: Implement reviewed Ladder Dragon architecture-plan stages and component extractions. Use for ownership refactoring, not routine bug fixes or deployment.
---

# Ladder Dragon architecture changes

Complete reviewed stages with concrete implementation ownership and verified behavior parity.
New folders, re-exports, and shorter files alone do not prove completion.
General safety, authorization, and verification rules remain in [AGENTS.md](../../../AGENTS.md).

## Select the relevant plan context

For continuation, read the [plan's](../../../docs/ARCHITECTURE_EVOLUTION_PLAN.md) current implementation status, relevant phase, dependencies, and acceptance criteria.
Compare recorded progress with the actual checkout.
Read the complete plan when reviewing overall architecture or changing cross-phase boundaries.
Expand context when the current phase depends on unresolved contracts elsewhere.
For ambiguous continuation, identify the next bounded slice within the reviewed phase.
Perform technical review under the [plan's review rules](../../../docs/ARCHITECTURE_EVOLUTION_PLAN.md) before starting a new phase.
Use the [component index](../../../docs/AGENT_WORKFLOW.md#task-routing-and-learning-index) for affected contracts, not as a mandatory reading package.

## Preserve behavior and prove ownership

- Move concrete behavior and internal callers together; retain required executable entry points.
- Separate mechanical relocation from financial, performance, schema, and strategy changes.
- Check imports, literal paths, dynamic loaders, resource lifetimes, and source-inspecting tests for affected interfaces.
- Compare unchanged implementation syntax where practical; verify behavior through real producer-to-consumer tests.
- Preserve mutable signal state and replaced resources through explicit live interfaces, not copied startup values.
- Investigate unexpected changes to safety order, financial results, evidence identity, or resource lifetime before continuing relocation.
- Add the completed ownership rule and its negative tests to the existing harness in the same change.
- Do not replace canonical safety checks with copied policy values or file-presence assertions.
- Lower completed migration budgets without compressing code merely to satisfy line limits.

Update the plan only after claimed behavior and harness enforcement are verified.
Record completed scope, actual check results, and remaining exceptions.
Do not claim startup acceleration from file movement without comparable measurements.
