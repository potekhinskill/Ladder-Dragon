# Releasing Ladder Dragon

Production releases use one final signed commit, a signed annotated tag, a
PASS verification manifest and an exact 40-character deployment SHA. A branch,
tag or GitHub release page is a discovery mechanism, not a trust root.

## 1. Prepare the candidate

Use a `ladderdragon/*` branch and keep one logical change set in one commit.
Update `product_version.py` and add the dated `CHANGELOG.md` section in that
same change set. The version must be the direct Semantic Version successor of
the signed baseline in `.release-lineage.json`; `## [Unreleased]` is forbidden.

Configure the dedicated release key published as
`docs/release-signing-key.asc`. Its full fingerprint is:

```text
808B9F52CB6C08901703EF7C113144122F1830A0
```

Verify this value through an independent channel, then configure
`user.signingkey`, `commit.gpgsign=true`, and `tag.gpgSign=true`.

Run focused tests while editing. When the candidate is complete, create the
single signed candidate commit:

```bash
git add <exact-files>
git commit -S -m "docs: synchronize runtime and release documentation"
git verify-commit HEAD
```

Run the Technical English check before you create the candidate commit:

```bash
.venv/bin/python -m bin.check_technical_english
```

## 2. Verify the immutable candidate SHA

The release profile must run against the final signed commit, not against an
uncommitted tree or a predecessor. It performs compilation, the complete test
suite, numeric/secret audits, replay, walk-forward, approval, recovery,
migration, deployment and release-continuity checks:

```bash
RELEASE_SHA="$(git rev-parse HEAD)"
.venv/bin/python -m bin.verification_harness --profile release \
  --expected-sha "${RELEASE_SHA}" \
  --output ".runtime/verification-release.json"
```

The explicit `.venv/bin/python` form remains canonical. As a second line of
defense, the harness entry point automatically re-executes through the
repository `.venv` before project imports when a local venv exists. CI jobs
without a local `.venv` retain their selected matrix interpreter.

`release_continuity` and the overall report must both be `PASS`. Its metrics
are the release manifest: previous/current version and SHA plus every included
commit. If verification changes any tracked file or finds a defect, do not add
a follow-up commit after the version bump. Fix the candidate, amend and re-sign
the same commit, then rerun the entire release profile and capture the new SHA.
Nothing may change between the PASS run and tagging.

## 3. Sign, verify and publish

Create and verify the signed annotated tag for the exact PASS SHA:

```bash
RELEASE_VERSION="$(.venv/bin/python -c \
  'from product_version import __version__; print(__version__)')"
git tag -s "v${RELEASE_VERSION}" \
  -m "Ladder Dragon ${RELEASE_VERSION}" "${RELEASE_SHA}"
git verify-tag "v${RELEASE_VERSION}"
test "$(git rev-list -n 1 "v${RELEASE_VERSION}")" = "${RELEASE_SHA}"
```

Push only after verification. Keep `main` linear and publish the commit and tag
atomically:

```bash
git push --atomic origin HEAD:main "v${RELEASE_VERSION}"
```

Wait for GitHub Actions to pass for `RELEASE_SHA`. Then create the release page
and attach the same PASS manifest:

```bash
gh release create "v${RELEASE_VERSION}" \
  ".runtime/verification-release.json#verification-release-${RELEASE_VERSION}.json" \
  --verify-tag --latest \
  --title "Ladder Dragon ${RELEASE_VERSION}" \
  --notes-file /path/to/reviewed-release-notes.md
```

Confirm GitHub `main`, the tag target, Actions run and release artifact all
refer to `RELEASE_SHA`. Never publish when `release_continuity` is `BLOCKED`.

## 4. Deploy and verify Raspberry Pi

Raspberry hosts pin the maintainer fingerprint in root-owned
`/etc/ladder-dragon/update-trust.conf` with mode `0600` and import the public
key into the bot user's GPG keyring. Deploy only the tested full SHA:

```bash
sudo bash deploy/update_raspberry_pi.sh update "${RELEASE_SHA}"
```

The updater creates an encrypted backup and preserves service state.
It preserves the live environment files.
It verifies the exact signed fast-forward commit.
It publishes and hashes all dashboard assets.
Then it restores the service policy and waits for a fresh heartbeat.
It does not import new `.env.example` values or alter reviewed
exposure.

Before backup or service stop, the installed updater fetches the requested commit.
It verifies the ancestry and maintainer signature.
It extracts the target updater to an immutable, root-only temporary runner.
Then it starts that runner.
This action applies new deployment steps during the first update.
Unsigned break-glass authority never executes target code through this bootstrap.

Copy the exact PASS manifest to the Pi and run the read-only profile with
`--expected-sha`, `--github-sha` and `--release-report` all referring to the
same commit. The full command and runtime paths are maintained in
[RASPBERRY_PI_INSTALL.md](RASPBERRY_PI_INSTALL.md#9-normal-updates).

The Pi profile is stricter than a deployment smoke test:

- `PASS` means deployment and all production evidence gates pass;
- `BLOCKED` means the host may be safely running but required approval evidence
  such as attribution, 24-hour stream soak, exact lifecycles or prediction
  closure is incomplete;
- `FAILED` means a required check actually failed.

Never turn `BLOCKED` into `PASS` by deleting evidence, clearing HALT, inventing
lifecycles or weakening a threshold.

## 5. Trust and emergency recovery

The updater accepts only a signature from the pinned fingerprint. Trust policy
must never be supplied through environment variables. An unsigned emergency
update requires the separate interactive, journaled, one-use break-glass
procedure in the Raspberry Pi runbook; it is not a routine release option.

See the [command reference](COMMAND_REFERENCE.md), the
[configuration reference](CONFIGURATION.md), and the
[implementation status](IMPLEMENTATION_STATUS.md) before release approval.
