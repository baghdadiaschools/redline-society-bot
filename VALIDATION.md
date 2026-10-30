# Validation record

Prepared October 30, 2026. No production token, private material, or production database was used.

## Passed locally

- Python 3.14.6: 14 database/runtime/backup tests (`python -m unittest discover -s tests -p test_store.py -v`).
- Persistent message and daily cooldowns across reopen, exact 30-second/24-hour boundaries.
- Owner-only adjustments/settings/official listings; bulk changes roll back together.
- Concurrent purchase attempts charge and pay once; insufficient funds/seller overflow leave no partial debit.
- Withdrawn listings preserve purchase entitlements; resets preserve purchases and cooldowns.
- SQLite backup/restore includes private test materials and balances, validates checksums and refuses non-empty restore targets.
- Backup retention, missing-file failure, migration idempotence, duplicate-worker file locking.
- All 17 Discord slash command definitions instantiated and serialized using installed discord.py 2.7.1, without logging in.
- `python -m pip check`: no broken requirements in the available runtime environment; runtime lock reflects these installed versions.
- Production compile and zipapp build (`python scripts/build.py`).

## Not executed successfully here

- The seven asynchronous Discord tests are provided for CI, but this Windows sandbox hangs while creating asyncio's local socket pair, before the test bodies run. The hung test processes were stopped. This is not a passing integration result.
- Mypy was unavailable. Installing development tools was blocked by package-host DNS/network restrictions. Type checking is configured in CI and must pass before deployment.
- Docker Engine was unavailable, so the image and Compose deployment were not run locally. CI includes the Docker build and an image/migration smoke test.
- Python 3.13 and Linux execution are covered by the supplied CI configuration, not by a completed local run.
- No Discord login, real server permission check, actual attachment delivery, GitHub Actions run, or hosting deployment took place.
- GitHub profile access succeeded, but repository creation was not exposed by its connector and the browser fallback failed. No remote repository was created or pushed.

Before production use: publish privately, require green GitHub Actions, then invite/configure the bot and test a small purchase, restart, redelivery, and backup restore in your server. Hosting account setup and secret entry are still required.
