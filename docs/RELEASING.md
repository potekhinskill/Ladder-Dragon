# Releasing Ladder Dragon

Production releases use an exact commit, a signed annotated tag, and a pinned
maintainer GPG fingerprint. Do not publish an unsigned production release.

1. Use the dedicated release key published as
   `docs/release-signing-key.asc`. Its full fingerprint is
   `808B9F52CB6C08901703EF7C113144122F1830A0`; verify both the file and this
   independently displayed value before trusting a release.
2. Set `user.signingkey`, `commit.gpgsign=true`, and `tag.gpgSign=true` in the
   release checkout.
3. Run the full test, compile, shell-syntax, dependency-audit, and secret-scan
   suite through the release profile:

   ```bash
   RELEASE_SHA="$(git rev-parse HEAD)"
   python -m bin.verification_harness --profile release \
     --expected-sha "${RELEASE_SHA}" \
     --output ".runtime/verification-release.json"
   ```

   `release_continuity` must be `PASS`. Starting with the signed baseline in
   `.release-lineage.json`, the candidate must directly follow the latest tag,
   contain exactly one version bump at the branch tip, and remain on one linear
   tag ancestry. The check metrics are the release manifest: previous version
   and SHA, current version and SHA, and the complete included-commit list.
   Historical changelog entries before the baseline are retained as legacy
   documentation and are not represented as newly backdated tags.
4. Create a signed commit and annotated tag:

   ```bash
   git commit -S -m "release: 2.10.x"
   git tag -s v2.10.x -m "Ladder Dragon 2.10.x"
   git verify-commit HEAD
   git verify-tag v2.10.x
   ```

5. Push the commit and tag. Confirm that GitHub `main`, the tag target and the
   release artifact all resolve to `RELEASE_SHA`. Raspberry hosts must pin the full fingerprint in
   root-owned `/etc/ladder-dragon/update-trust.conf` with mode `0600`, import the
   public key into the bot user's GPG keyring, and update by exact SHA. Trust
policy must never be supplied through command environment variables.

6. After deployment, rerun the Pi profile with both reviewed SHA inputs:

   ```bash
   python -m bin.verification_harness --profile pi \
     --expected-sha "${RELEASE_SHA}" \
     --github-sha "${RELEASE_SHA}" \
     --release-report .runtime/verification-release.json
   ```

   The Pi gate blocks unless deployed HEAD, fetched upstream, the reviewed
   GitHub SHA and the PASS release artifact are identical.

The public repository and tag name are discovery mechanisms, not trust roots.
The updater accepts only a signature from the pinned fingerprint.
