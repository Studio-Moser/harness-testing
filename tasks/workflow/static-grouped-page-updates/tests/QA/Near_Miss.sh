#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/Ship faster together/Build calmer workflows/' index.html
npm run check:hero
