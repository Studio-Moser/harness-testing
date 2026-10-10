#!/usr/bin/env sh
set -eu

cd /app
git checkout -b feat/toggle-completion
cat > 'src/Completion.js' <<'FIXTURE_EOF'
export function toggleDone(task) { return {...task, done: !task.done}; }
FIXTURE_EOF
cat > 'Change_Notes.md' <<'FIXTURE_EOF'
# Change Notes

`toggleDone(task)` returns a copy of the task with `done` flipped. Every other property is
preserved and the input is never mutated.
FIXTURE_EOF
npm test
git add src/Completion.js Change_Notes.md && git commit -m "feat: add an immutable completion toggle"
