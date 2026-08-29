#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/--cta-background: #2563eb/--cta-background: #6d28d9/' src/index.css
printf '\n// unrelated source edit\n' >> src/App.tsx
npm run check:cta
