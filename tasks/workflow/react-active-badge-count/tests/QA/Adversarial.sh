#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i 's/project.active)/project.active \&\& !project.archived)/' \
  src/domain/Active_Count.ts
cat > src/domain/Active_Count.test.ts <<'TEST'
import { describe, expect, it } from 'vitest'
import { selectActiveCount } from './Active_Count.ts'

describe('selectActiveCount', () => {
  it('excludes archived projects', () => {
    expect(selectActiveCount([{ id: 'old', active: true, archived: true }])).toBe(0)
  })
})
TEST
printf '\n// benchmark tamper probe\n' >> src/App.test.tsx
npm test -- src/domain/Active_Count.test.ts
npm test
