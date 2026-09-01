# Domain authorities

Shared financial meanings have one domain owner.
Consumers import that owner and do not copy its values.

## Canonical owners

- `execution/trade_accounting.py` owns symbol parsing and commission provenance.
- `risk/asset_policy.py` owns risk valuation asset groups.
- `strategy/fee_defaults.py` owns non-authoritative research fee assumptions.
- `strategy/indicators.py` owns named Average True Range algorithms.
- `execution/binance_transport.py` owns authenticated exchange transport behavior.

Research fee defaults do not attest an account fee.
They cannot authorize LIVE execution.

Average True Range consumers must name their algorithm and candle population.
Wilder, simple-average, and exponential-average results are not interchangeable.

## Automated controls

Run `python -m bin.audit_semantic_authorities`.
This audit rejects copied vocabularies, direct fee-rate assumptions, and inline Average True Range consumers.
It checks assignments, call keywords, and function argument defaults.
Fee amounts and validation error thresholds are not fee-rate assumptions.

Run `python -m bin.audit_exchange_boundaries`.
This audit rejects authenticated transport calls outside reviewed boundary adapters.

Run `python -m bin.audit_guard_contracts`.
This audit requires executable rejection paths in registered fail-closed guards.
It resolves module functions and qualified class methods without name collisions.

Run `python -m bin.audit_execution_authority_paths`.
This audit requires lifecycle validation in each symbol cycle.
It requires LIVE worker verification before exchange access.

Run `python -m bin.audit_numeric_boundaries`.
New order and protection modules receive a zero-`float` budget automatically.

The release verification profile runs all five audits.
Property and mutation tests exercise generated values, damaged guards, and misplaced authority calls.
