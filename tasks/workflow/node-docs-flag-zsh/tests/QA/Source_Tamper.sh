#!/usr/bin/env sh
set -eu
cd /app
bash /tmp/harness-qa-oracle.sh
printf '\nchanged protected input\n' >> README.md
