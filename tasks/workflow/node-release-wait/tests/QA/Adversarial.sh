#!/usr/bin/env sh
set -eu
cd /app
bash /tmp/harness-qa-oracle.sh
i=0
while [ "$i" -lt 24 ]; do
  npm run --silent release-status
  i=$((i + 1))
done
