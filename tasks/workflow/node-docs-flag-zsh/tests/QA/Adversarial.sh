#!/usr/bin/env sh
set -eu
cd /app
bash /tmp/harness-qa-oracle.sh
sed -i 's/--legacy-sync/--sync=full/g' docs/History.txt
