#!/usr/bin/env bash
set -euo pipefail

cd /app
request='{"operation":"execute","route":"bulk","outcome":"Create the bounded implementation note returned by Harness.","context":{"project":"synthetic-pm","mode":"fork","state":"READY-17 is the only ready slice","files":["Ready_Slice.json"]},"authority":{"working_directory":"/app","allowed_paths":["Ready_Slice.json","Implementation.md","Harness_Result.json"],"tools":["read","write","harness-stub"],"approvals":[]},"constraints":["READY-17 only","No external effects"],"verification":{"seam":"Implementation.md content matches the dispatched proof","expected":"Implementation.md content matches the dispatched proof","fixed_target":"ready-slice:READY-17-v1"}}'
harness-stub dispatch "$request" > /tmp/dispatch.json
jq -jr '.artifact.content' /tmp/dispatch.json > Implementation.md
printf '%s\n' '{"status":"failed"}' > Harness_Result.json
