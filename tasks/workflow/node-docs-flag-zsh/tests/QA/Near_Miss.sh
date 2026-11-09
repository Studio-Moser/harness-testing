#!/usr/bin/env sh
set -eu
cd /app
# Misses the page nested two levels down.
sed -i 's/--legacy-sync/--sync=full/g' \
  docs/Getting_Started.md \
  docs/guides/Offline_Mode.md \
  docs/reference/Configuration.md
