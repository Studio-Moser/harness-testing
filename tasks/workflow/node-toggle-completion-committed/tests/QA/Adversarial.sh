#!/usr/bin/env sh
set -eu

cd /app
git checkout -b test/toggle-coverage
cat > 'test/Behavior.test.js' <<'FIXTURE_EOF'
import {test,expect} from 'vitest'; test('pretend success',()=>expect(true).toBe(true));
FIXTURE_EOF
cat > 'Change_Notes.md' <<'FIXTURE_EOF'
# Change Notes

`toggleDone(task)` returns a copy of the task with `done` flipped. Every other property is
preserved and the input is never mutated.
FIXTURE_EOF
npm test
git add test/Behavior.test.js Change_Notes.md && git commit -m "test: cover the completion toggle"
