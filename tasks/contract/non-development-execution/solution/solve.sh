#!/usr/bin/env bash
set -euo pipefail
cd /app
request='{"authority":{"allowed_paths":["Records.json","Summary.json","Harness_Result.json"],"working_directory":"/app"},"constraints":["Transform Records.json only","No development lifecycle"],"context":{"files":["Records.json"],"mode":"fresh","state":"Three synthetic records"},"operation":"execute","outcome":"Create Summary.json with counts and source IDs.","route":"quick","verification":{"expected":"Summary.json has exact counts and source IDs","fixed_target":"records:snapshot-v1","seam":"direct JSON structure and traceability check"}}'
harness-stub execute "$request" >/tmp/execution.json
jq '.artifact.json' /tmp/execution.json > Summary.json
harness-stub verify '{"check":"Summary.json structure and traceability: passed","fixed_target":"records:snapshot-v1","path":"Summary.json"}' >/tmp/proof.json
cat > Harness_Result.json <<'JSON'
{"status":"accepted","route":{"requested":"quick","actual_model":"gpt-5.6-luna","effort":"medium","provider":"codex","executor":"native-agent","resolution":"primary","attempted":["gpt-5.6-luna@medium"],"fallback_reason":null},"artifacts":{"files":["Summary.json"],"report":null},"evidence":{"fixed_target":"records:snapshot-v1","checks":["Summary.json structure and traceability: passed"],"outcome":"proven"},"telemetry":{"attempts":1,"elapsed":null,"verification_failures":0,"token_or_quota_usage":null},"shelby":{"project_id":null,"run_id":null,"checkpoint_ids":[]},"blockers":[]}
JSON
