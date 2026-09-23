#!/usr/bin/env sh
set -eu

python -m rewardkit /tests \
  --workspace /app \
  --output /logs/verifier/reward.json \
  --max-concurrent-programmatic 3
