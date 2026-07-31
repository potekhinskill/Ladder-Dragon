# Technical English writing standard

This project uses a controlled writing profile based on ASD-STE100 Simplified
Technical English (STE), Issue 9.

Use these official references:

- [ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf);
- [ASD-STE100 frequently asked questions](https://www.asd-ste100.org/STE_faq.html).

This profile applies to these files:

- `README.md`;
- `CONTRIBUTING.md`;
- `SECURITY.md`;
- all current guides in `docs/`;
- new entries in `CHANGELOG.md`, `DECISIONS.md`, and `MISTAKES.md`;
- operator help text that is not part of a locale.

The profile does not change these items:

- code, commands, paths, API fields, and configuration names;
- exact error messages and quoted external text;
- licenses, copyright notices, trademarks, and third-party notices;
- locale files and translated user-interface text;
- historical evidence that an earlier release recorded.

## Required writing rules

Use these rules for each new or changed document:

1. Use American English.
2. Use one word for one meaning.
3. Use the same term for the same item or action.
4. Use approved general words and necessary project technical terms.
5. Define an abbreviation at its first use in each document.
6. Use active voice when the actor is known.
7. Use the present tense for descriptions.
8. Use the imperative form for an instruction.
9. Put a condition before the action that depends on it.
10. Put only one instruction in each numbered step.
11. Use no more than 20 words in a procedural sentence.
12. Use no more than 25 words in a descriptive sentence.
13. Use a vertical list when one sentence contains many items.
14. Keep one subject in each paragraph.
15. Do not use contractions, idioms, slang, or promotional exaggeration.
16. Do not use an `-ing` form when a clear approved verb is available.
17. Do not omit articles when normal English grammar requires them.
18. Put a warning or caution before the related instruction.
19. Use `must` for a requirement. Use `can` for capability.
20. Do not use `may` when you mean permission or possibility.
21. Verify each implementation claim against code, tests, configuration, or service files.
22. Derive each command example from the current command parser.
23. Mark planned work as planned. Do not describe planned work as available.

## Project technical terms

The following terms are approved technical terms in this project:

- Binance Spot;
- BUY, SELL, LIMIT, MARKET, LIMIT_MAKER, OCO, OTOCO, STOP, and STOP_LIMIT;
- Risk Manager, CAP, HALT, DRY, LIVE, SHADOW, APPLY, and Testnet;
- FIFO, PnL, RAG, API, REST, WebSocket, JSON, JSONL, SQLite, SHA-256, and CI;
- fill, partial fill, slippage, spread, ladder, re-anchor, replay, and walk-forward;
- Raspberry Pi, systemd, nginx, FastAPI, Telegram, and GitHub.

Use the exact spelling and capitalization in this list. Define less common
terms when the reader first needs them.

## Procedure format

Use this format for an operator procedure:

1. State the required condition.
2. Give one action.
3. Show the command in a code block.
4. State the expected result.
5. State the fail-closed result when the check fails.

Put `WARNING` before an instruction that can cause injury, data loss, financial
exposure, or removal of exchange protection.

Put `CAUTION` before an instruction that can damage software state or make
evidence invalid.

## Verification

Run the documentation check from the project virtual environment:

```bash
.venv/bin/python -m bin.check_technical_english
```

The check finds objective sentence-length and contraction errors. A writer
must also review vocabulary, meaning, active voice, and technical accuracy.

The check is an aid. It is not an ASD certification and does not replace the
official ASD-STE100 standard or qualified review.

Technical accuracy requires a separate contract review.
The review must compare CLI examples, service names, file paths, modes, and defaults with the repository.
