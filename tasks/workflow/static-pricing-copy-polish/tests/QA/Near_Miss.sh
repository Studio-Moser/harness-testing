#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/Everything your team needs to work\./Everything your team needs to ship./' index.html
