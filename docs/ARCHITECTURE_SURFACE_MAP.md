# Command and deployment source map

Status: partial P0 inventory and required local P1 enforcement.

The exact source manifest is `schemas/architecture_surfaces.json`.
It registers 146 files at this implementation stage.
Registration describes current source responsibility, not completed behavior extraction or permission to deploy.

## Registered groups

| Group | Count | Responsibility |
|---|---|---|
| Python commands | 71 | Stable operator entry names under `bin/` |
| Shell command | 1 | Supervisor and report process control |
| Command package initializer | 1 | Python package declaration |
| ASGI entry point | 1 | Dashboard application export |
| Frontend assets | 8 | Dashboard pages, styles, and scripts |
| Vendor resources | 2 | Chart library and its license |
| Service templates | 15 | Source service definitions |
| Timer templates | 10 | Source schedules |
| Deployment shell scripts | 11 | Installation and host workflows |
| Deployment Python modules | 8 | Host validation and administration |
| Deployment configuration | 7 | Reviewed configuration templates |
| Accounting migrations | 10 | Versioned accounting schema resources |
| Context migration | 1 | Versioned prediction context schema resource |

ASGI means Asynchronous Server Gateway Interface.
Source service filenames are not necessarily installed unit names.
For example, `deploy/pi-dashboard.service` supplies the installed `pi-healthd.service` unit.
The manifest does not infer installation destinations from source filenames.

## Required checks

The `architecture_surfaces` check runs in local and release harness profiles.
The architecture command includes its bounded report:

```bash
.venv/bin/python -m bin.audit_architecture
```

The check discovers tracked and nonignored new files under the registered source areas.
Each discovered file needs an exact manifest entry and a compatible role.
Unregistered files fail before the analyzer reads their contents.
Missing registered resources fail verification, including staged deletions.
Symlinks, invalid manifests, excessive inputs, and unavailable required inputs block verification.
Python and shell commands need table entries in [Command reference](COMMAND_REFERENCE.md).
The package initializer is not an executable command.

Reports contain source hashes, sizes, owners, group counts, and the checkout commit.
They contain no source bodies or command output.
The analyzer never starts a command, imports application code, contacts an exchange, or reads runtime state.
Report retention follows the existing bounded verification artifact workflow.
This change adds no production state, retention job, or backup.

## Existing authorities remain separate

- Launcher shape remains covered by `tests/test_architecture_layout.py`.
- Deployment references and packaging remain covered by existing deployment and migration tests.
- Installed dashboard resources retain their release-bound asset verification.
- Source hashes observe migration changes; existing migration contracts decide whether those changes are valid.
- The source map grants no exception to the five financial safety audits.

## Remaining inventory and parity work

### Implemented literal service links

`schemas/architecture_service_links.json` records 25 unit templates and seven literal installed-file destinations.
The required `architecture_service_links` check resolves 27 direct service and timer edges in local and release profiles.
It records the ordered fingerprints of active `Exec*` and timer `Unit` directives.
An argument change requires review, even when the target file remains unchanged.
Timers without `Unit` use their same-name service target.
Installed executables resolve through reviewed source mappings in `deploy/install_runtime_assets.sh`.
Unknown targets, changed directives, and changed literal installation links cannot pass.
Reports contain source paths and hashes, never raw command arguments or source bodies.

The parser supports the current one-line unit syntax; unsupported continuation syntax blocks analysis.
Literal install statements do not prove shell reachability or successful installation.
This check does not resolve nested shell commands, systemd drop-ins, environment overrides, or runtime service state.
Installer unit aliases and their actual installed paths remain separate deployment contracts.

### Remaining work

The Python inventory now reports syntactic CLI sites for registered production modules.
CLI means command-line interface.
Sites include `ArgumentParser` constructors, argument declarations, subcommands, groups, defaults, and parse calls.
Constructor discovery includes explicit `argparse` import aliases.
Each site records its source line, method, syntax hash, argument counts, and argument expansion flag.
The report never includes argument values, defaults, help text, or evaluated expressions.
Local and release profiles include these observations through the required `architecture_ownership` check.

These observations include conditional and nested code, even when that code never runs.
Matching method names do not prove parser identity; a shadowed constructor remains a syntactic observation.
Dynamic method lookup and assigned callable aliases remain unresolved.
The inventory does not prove command-to-parser reachability or default and exit-code parity.
Existing executable CLI tests remain necessary before any behavior moves.

Record every command's parser, options, exit semantics, and implementation owner before migrating its behavior.
Complete nested script references and source-to-installed destinations before changing deployment layout.
Record frontend references and installed package contents before moving assets or migrations.
Add negative tests for each completed reference or interface contract.
The current membership check does not prove these relationships or runtime equivalence.

Do not execute shell help commands merely to discover their interface.
Some shell commands initialize local state before they process arguments.
Use source inspection for inventory and isolated contract tests for executable parity.

See [Architecture evolution plan](ARCHITECTURE_EVOLUTION_PLAN.md) and [State and policy map](ARCHITECTURE_STATE_MAP.md).
