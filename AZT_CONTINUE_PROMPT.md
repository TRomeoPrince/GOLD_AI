# Continue AZT recovery

Read `AZT_RECOVERY_PROGRESS.md` first. The owner source checkout is `C:\Users\USER\Desktop\Bots\Forex\AMD1`, branch `recovery/azt-system-20261108`, initially at `2625689`. The Client checkout is `C:\Users\USER\Desktop\Bots\GOLD_AI_client`, branch `recovery/azt-2026-11-08`, initially at `a5ab196`. Check `git status --short --branch` and recent commits in both checkouts before resuming.

At the baseline checkpoint, both remotes had been fetched and prior November 4 commits preserved. The target `C:\Users\USER\Desktop\Gold_AI` contains legacy binaries and an APK. Existing state is in `%LOCALAPPDATA%\GOLD_AI`. Inspect the latest checkpoint before assuming the installation was copied or that any repair or build passed.

Next task: verify baseline results, then implement and test the reproduced reliability faults. Exercise simulated MT5, mocked Telegram, and isolated databases. Before any installation copy, check for competing workers, back up the old SQLite database via SQLite backup, and retain the old configuration, credentials and execution records. Prepare the Desktop installation without starting production. Do not merge into main without owner approval, place live orders, send real Telegram messages, or delete unresolved execution claims. Update both checkpoint documents with actual commits, build hashes, test outcomes and the next exact command.
