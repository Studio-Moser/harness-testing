#!/usr/bin/env bash
set -euo pipefail

bash /tmp/harness-qa-oracle.sh
printf '\n' >> /app/Sources.json
