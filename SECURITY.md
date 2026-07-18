# Security policy

Please do not publish API keys, secrets, backup archives, account identifiers,
or exploit details in a public issue. Use GitHub's private vulnerability
reporting or a private security advisory for this repository. If private
reporting is unavailable, contact the project owner through the LinkedIn
profile in `README.md` without including secrets.

## If a secret may have been exposed

1. Revoke the key at the exchange or provider immediately.
2. Create a replacement with the minimum permissions and an IP allow-list.
3. Stop LIVE execution and review open orders, balances, and the circuit breaker.
4. Preserve only redacted logs and the encrypted backup; never attach raw `.env`,
   database, Telegram, Binance, DeepSeek, or GitHub credential files.
5. Report the affected commit, path, and rotation time privately.

History rewriting does not revoke a credential. Treat every key that appeared
in Git, a log, a backup, an artifact, or a fork as compromised and rotate it.
