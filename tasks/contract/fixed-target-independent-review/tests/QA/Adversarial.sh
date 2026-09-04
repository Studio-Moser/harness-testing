#!/usr/bin/env bash
set -euo pipefail

cd /app
printf '%s' '# Independent Review

Target: ef4d5362c2b7f262cc0a6f85574a004e5313eb43
Finding: `canPublish` accepts a caller assertion without independent evidence.
Verdict: changes requested.
' > Review.md
cat > Harness_Result.json <<'JSON'
{"status":"accepted","route":{"requested":"independent","actual_model":"claude-sonnet-4-6","effort":"high","provider":"claude","executor":"independent-review","resolution":"primary","attempted":["claude-sonnet-4-6@high"],"fallback_reason":null},"artifacts":{"files":["Review.md"],"report":"Review.md"},"evidence":{"fixed_target":"ef4d5362c2b7f262cc0a6f85574a004e5313eb43","checks":["Review.md target and finding: passed"],"outcome":"proven"},"telemetry":{"attempts":1,"elapsed":null,"verification_failures":0,"token_or_quota_usage":null},"shelby":{"project_id":null,"run_id":null,"checkpoint_ids":[]},"blockers":[]}
JSON
