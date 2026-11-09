# Offline mode

Tasklog queues changes while you are offline and sends them when you reconnect.

After a long time offline, run `tasklog sync --legacy-sync` to replace the local copy with the server's.

Scripts that run in CI should pass `--legacy-sync` so every run starts from the same state.
