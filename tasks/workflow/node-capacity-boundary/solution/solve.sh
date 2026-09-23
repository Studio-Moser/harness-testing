#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Capacity.js' <<'FIXTURE_EOF'
export const isAtCapacity = (count, limit) => count >= limit;
FIXTURE_EOF
npm test
