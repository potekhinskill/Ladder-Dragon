# Isolated analyzer contract

The project uses downstream Semgrep `1.168.0+ld.1`, not an upstream-approved dependency combination.
The rebuild preserves upstream code, data, entry points, and license contents.
Only dependency metadata, distribution paths, and the wheel record change.

## Provenance and installation

`requirements/semgrep-build.json` pins source, output, and installed payload digests for each supported platform.
Supported platforms are macOS arm64, Linux aarch64, and Linux x86_64.
Unknown platforms fail closed. The Linux wheels require glibc 2.34 or newer.
The official source metadata is available from [the Python Package Index (PyPI)](https://pypi.org/pypi/semgrep/1.168.0/json).

Use the project interpreter to install the isolated analyzer:

```bash
.venv/bin/python -m bin.install_semgrep
```

In CI, use the selected matrix interpreter instead of `.venv/bin/python`.
The installer uses normal dependency resolution and requires hashes for every package.
It installs pinned bootstrap tools first, so the wheel installation records its archive hash.
It does not install the analyzer in the application environment or on Raspberry Pi.
It rejects changed cached sources, unexpected rebuilt hashes, and conflicting build contracts.

Use a clean `.semgrep-venv` for an initial migration.
Preserve any previous environment before replacement; do not silently retain unrelated packages.
The installed package set must match the dependency lock and downstream analyzer exactly.

## Mandatory verification

Every scanner invocation verifies the wheel origin, installed code digest, and exact dependency versions.
The local and release profiles require all three analyzer checks:

- Positive and negative fixtures for every project rule.
- Compatibility checks for Model Context Protocol (MCP) tools, telemetry, and JSON Web Token (JWT) behavior.
- Production source analysis with strict timeout and error handling.

The scanner child receives a minimal environment without application credentials.
The compatibility check rejects socket connections and uses synthetic data only.
Linux comparison experiments also disable networking at the container boundary.
These checks do not establish compatibility for every upstream feature.

On 2026-10-26, Linux aarch64 and x86_64 builds reproduce the pinned wheel hashes.
Offline comparison on Python 3.12 matches the original analyzer on both Linux architectures.
The macOS arm64 installation and mandatory checks pass on Python 3.10.
The integrated local suite passes 5695 tests with two existing skips; compilation and all five safety audits pass.
The GitHub Python 3.10, 3.11, and 3.12 matrix remains mandatory before deployment.

CI audits the complete dependency lock and unchanged upstream identity separately.
The downstream package does not have a public advisory identity.
Do not treat a skipped local wheel as a clean advisory result.
Do not suppress advisories, disable checks, or replace failures with a fallback scanner.

## Maintenance and storage

`semgrep_build.py` requires exact metadata preimages and validates every source wheel record.
Changes require deterministic rebuilds, unchanged payload proofs, and platform-specific behavioral comparisons.
Regenerate `requirements/semgrep.lock` from `requirements/semgrep.in` with hashes and Python 3.10 compatibility.
Install the generated wheel and dependency lock together to check the actual resolver contract.
Review Python 3.10, 3.11, and 3.12 compatibility before publication.

Build files below `.runtime/semgrep-build` are disposable, versioned local artifacts.
They have no backup dependency and must not enter Git or the Raspberry Pi deployment.
The installer disables the pip cache and rejects builds above its storage admission limit.
It permits at most 1.5 GiB before a build, reserving capacity for bounded source and output wheels.
Before each installation, it checks storage usage; cleanup remains an explicit operator action.
Remove obsolete build versions only after reviewing their exact paths and retained verification reports.

Publication still requires the complete immutable release profile and separate authorization for its exact SHA.
Analyzer verification grants no trading permission and does not change HALT.
