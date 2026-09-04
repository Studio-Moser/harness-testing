#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/--accent: #2563eb/--accent: #6d28d9/' src/index.css
npm run check:accent
