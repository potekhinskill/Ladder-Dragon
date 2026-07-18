# Copyright and maintenance

Copyright (c) 2026 IURII Potekhin / Ladder Dragon.

Project contact: https://www.linkedin.com/in/ypotekhin/

The code is distributed under the MIT License. Additional warranty and
financial-liability limitations are described in `DISCLAIMER.md`.

The public contact link belongs in this document and `README.md`; it is not
copied into every source header or runtime configuration.

Secrets, real backup files, production configuration, and private trading
parameters must not enter Git or public releases unless they have been
explicitly sanitized and approved for publication.

Production inline comments and maintenance headers are written in English.
Safety notes must remain clear about financial risk, fail-closed behavior,
secrets, backups, and deployment boundaries. Existing user-facing Russian
docstrings are documentation text, not runtime logic, and may be translated in
a separate documentation pass. Every material change must update
`CHANGELOG.md` with a dated semantic-version section; do not use an
`Unreleased` section.
