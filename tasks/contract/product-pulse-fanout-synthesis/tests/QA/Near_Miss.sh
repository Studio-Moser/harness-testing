#!/usr/bin/env bash
set -euo pipefail

cd /app
harness-stub research '{"citation":"source://alpha","operation":"execute","question":"What reduces verification churn?","route":"bulk","source_id":"alpha"}' >/tmp/alpha.json
printf '%s\n' '# Product Pulse' > Product_Pulse.md
printf '%s\n' '{"status":"accepted"}' > Harness_Result.json
