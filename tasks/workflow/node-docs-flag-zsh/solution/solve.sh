#!/usr/bin/env sh
set -eu
cd /app
sed -i 's/--legacy-sync/--sync=full/g' \
  docs/Getting_Started.md \
  docs/guides/Offline_Mode.md \
  docs/reference/cli/Sync.md \
  docs/reference/Configuration.md
npm test
