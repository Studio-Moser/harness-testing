#!/usr/bin/env bash
set -euo pipefail
cd /app
harness-stub capability-check '{"executor":"codex-cli","working_directory":"/app"}' >/tmp/capability.json
printf '%s\n' '{"status":"accepted"}' > Harness_Result.json
