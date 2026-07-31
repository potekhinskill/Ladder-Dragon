# Contributing

Contributions are welcome through pull requests. The project is MIT-licensed,
but contributors must have the right to submit their changes under that license.

Before opening a pull request:

- keep DRY/Testnet as the default and never add real credentials;
- run `PYTHONPATH=. pytest -q`, `python3 -m compileall -q .`, and `git diff --check`;
- run `python3 deploy/scan_tracked_secrets.py`;
- add a dated semantic-version section to `CHANGELOG.md` and bump
  `product_version.py`; never add an `Unreleased` section;
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

- [implementation status](docs/IMPLEMENTATION_STATUS.md);
- [configuration](docs/CONFIGURATION.md);
- [command reference](docs/COMMAND_REFERENCE.md);
- [architecture](docs/ARCHITECTURE.md).
