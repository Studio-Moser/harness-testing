#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/--cta-background: #2563eb/--cta-background: #6d28d9/' src/index.css
printf '\n// benchmark tamper probe\n' >> src/App.test.tsx
npm run check:cta
