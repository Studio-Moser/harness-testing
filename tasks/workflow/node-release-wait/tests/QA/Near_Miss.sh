#!/usr/bin/env sh
set -eu
cd /app
bash /tmp/harness-qa-oracle.sh
sed -i 's/"published": false/"published": true/' release.json
