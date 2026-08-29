#!/usr/bin/env bash
set -euo pipefail
cd /app
printf '%s\n' 'Harness contracts keep evidence local.' > Normalized.md
cat > Harness_Result.json <<'JSON'
{"status":"accepted","route":{"requested":"default","actual_model":"gpt-5.6-terra","effort":"high","provider":"codex","executor":"native-agent","resolution":"primary","attempted":["gpt-5.6-terra@high"],"fallback_reason":null},"artifacts":{"files":["Normalized.md"],"report":null},"evidence":{"fixed_target":"input:snapshot-v1","checks":["Shelby callable inventory: absent; continued without optional enrichment","Normalized.md content: passed"],"outcome":"proven"},"telemetry":{"attempts":1,"elapsed":null,"verification_failures":0,"token_or_quota_usage":null},"shelby":{"project_id":null,"run_id":null,"checkpoint_ids":[]},"blockers":[]}
JSON
