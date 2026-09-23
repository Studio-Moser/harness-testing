#!/usr/bin/env bash
set -euo pipefail

cd /app
# Start from the complete reference fix, so only the unrelated source change
# below can cause rejection, not a missing persistence/error-handling behavior.
bash /tmp/harness-qa-oracle.sh
printf '\n// unrelated source edit\n' >> src/App.tsx
npm run test:saved-view
npm run test:view-filter
npm run gate
