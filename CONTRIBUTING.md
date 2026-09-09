# Contributing

Contributions are welcome through pull requests. The project is MIT-licensed,
but contributors must have the right to submit their changes under that license.

Before opening a pull request:

- keep DRY/Testnet as the default and never add real credentials;
- follow [verification by change type](AGENTS.md#verification-by-change-type), including `git diff --check`;
- run `.venv/bin/python deploy/scan_tracked_secrets.py`;
- use one dated changelog section and version for each unpublished candidate; never add an `Unreleased` section;
- document fail-closed behavior and add regression coverage for risk or execution
  changes;
- use English maintenance comments for production code and preserve copyright
  headers;
- write documentation with the project profile in
  `docs/TECHNICAL_ENGLISH.md`;
- run `.venv/bin/python -m bin.check_technical_english`;
- do not include raw logs, databases, backups, API keys, or account data.

A pull request should explain the user impact, safety boundaries, tests, and any
required Raspberry Pi migration step.

Use these references before you change an interface:

- [task routing and learning index](docs/AGENT_WORKFLOW.md);
- [implementation status](docs/IMPLEMENTATION_STATUS.md);
- [configuration](docs/CONFIGURATION.md);
- [command reference](docs/COMMAND_REFERENCE.md);
- [architecture](docs/ARCHITECTURE.md).
