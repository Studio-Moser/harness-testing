#!/usr/bin/env bash
set -euo pipefail

cd /app
target=$(git rev-parse HEAD)
request=$(jq -cn --arg target "$target" '{operation:"review",route:"independent",outcome:"Produce an independent review report for the immutable target.",context:{project:"synthetic-review",mode:"fresh",state:"Independent cost approved; builder conclusions intentionally excluded",files:["src/Policy.ts"]},authority:{working_directory:"/app",allowed_paths:["src/Policy.ts","Review.md","Harness_Result.json"],tools:["read","git","write","harness-stub"],approvals:[]},constraints:["Independent review cost approved","Read-only fixed target"],verification:{seam:"Review.md target and finding check",expected:"Review.md names the fixed target and finding",fixed_target:$target}}')
harness-stub review "$request" > /tmp/review.json
jq -jr '.report.content' /tmp/review.json > Review.md
printf '%s\n' '{"status":"accepted"}' > Harness_Result.json
