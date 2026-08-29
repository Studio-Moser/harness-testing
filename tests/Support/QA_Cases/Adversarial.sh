#!/usr/bin/env bash
set -euo pipefail

cd /app

sed -i 's/--accent: #2563eb/--accent: #6d28d9/' src/index.css
sed -i 's/No projects found/No projects yet/' src/App.tsx
sed -i 's/--card-gap: 20px/--card-gap: 12px/' src/index.css
printf '\n// benchmark tamper probe\n' >> src/App.test.tsx

npm run gate
