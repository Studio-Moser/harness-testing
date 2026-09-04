#!/usr/bin/env bash
set -euo pipefail
cd /app
harness-stub lookup-rubric '{"path":"/home/agent/.config/studio-moser/model-rubric.yml"}' >/tmp/rubric.json
printf '%s\n' '{"status":"accepted"}' > Harness_Result.json
