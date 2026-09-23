#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Completion.js' <<'FIXTURE_EOF'
export function toggleDone(task) { task.done = !task.done; return task; }
FIXTURE_EOF
