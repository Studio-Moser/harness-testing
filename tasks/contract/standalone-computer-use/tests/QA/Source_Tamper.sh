#!/usr/bin/env bash
set -euo pipefail
bash /tmp/harness-qa-oracle.sh
printf '\n' >> /app/Computer_Use_Request.json
