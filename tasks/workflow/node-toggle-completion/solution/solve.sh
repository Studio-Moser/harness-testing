#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Completion.js' <<'FIXTURE_EOF'
export function toggleDone(task) { return {...task, done: !task.done}; }
FIXTURE_EOF
npm test
