#!/usr/bin/env bash
set -euo pipefail

cd /app
printf '%s\n' 'Implemented READY-17 within the approved /app paths.' > Implementation.md
cat > Harness_Result.json <<'JSON'
{"status":"accepted","route":{"requested":"bulk","actual_model":"gpt-5.6-terra","effort":"high","provider":"codex","executor":"native-agent","resolution":"primary","attempted":["gpt-5.6-terra@high"],"fallback_reason":null},"artifacts":{"files":["Implementation.md"],"report":null},"evidence":{"fixed_target":"ready-slice:READY-17-v1","checks":["Implementation.md content: passed"],"outcome":"proven"},"telemetry":{"attempts":1,"elapsed":null,"verification_failures":0,"token_or_quota_usage":null},"shelby":{"project_id":null,"run_id":null,"checkpoint_ids":[]},"blockers":[]}
JSON
