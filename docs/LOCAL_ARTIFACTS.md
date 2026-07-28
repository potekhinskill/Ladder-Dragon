# Local runtime artifacts

Runtime state and secrets are not source code. The repository ignores
`.runtime/`, Python caches, local SQLite databases, logs, `.env` variants and
backup credential files.

## Safety policy

- Never inspect, copy, rename, delete, upload or commit an artifact merely
  because it appears in a workspace audit.
- Never print `.env`, `.env.bak`, key, token, database or backup contents.
- Stop services before an operator-approved database move and preserve an
  encrypted backup plus file ownership and permissions.
- Keep active Raspberry Pi state under the deployment-owned runtime paths;
  keep developer state outside the repository whenever practical.
- Cleanup is always an explicit operator action with exact paths. There is no
  recursive automatic cleanup command in this repository.
- `__pycache__` and test caches may be regenerated, but they are still removed
  only after confirming the exact workspace target.

The architecture and verification checks inspect source paths and Git state,
not the contents of private runtime artifacts.
