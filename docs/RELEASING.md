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
   suite.
4. Create a signed commit and annotated tag:

   ```bash
   git commit -S -m "release: 2.10.x"
   git tag -s v2.10.x -m "Ladder Dragon 2.10.x"
   git verify-commit HEAD
   git verify-tag v2.10.x
   ```

5. Push the commit and tag. Raspberry hosts must set
   `BOT_UPDATE_TRUSTED_SIGNER` to the full fingerprint and update by exact SHA.

The public repository and tag name are discovery mechanisms, not trust roots.
The updater accepts only a signature from the pinned fingerprint.
