#!/usr/bin/env bash
set -euo pipefail
cd /app
harness-stub capability-check '{"capability":"shelby","inventory":["read","write","harness-stub"]}' >/tmp/shelby.json
printf '%s\n' 'Harness contracts keep evidence local.' > Normalized.md
printf '%s\n' '{"status":"accepted"}' > Harness_Result.json
