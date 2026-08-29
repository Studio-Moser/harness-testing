#!/usr/bin/env bash
set -euo pipefail

cd /app

sed -i 's/project.active)/project.active \&\& !project.archived)/' \
  src/domain/Active_Count.ts

cat > src/domain/Active_Count.test.ts <<'TEST'
import { describe, expect, it } from 'vitest'

import { selectActiveCount } from './Active_Count.ts'

describe('selectActiveCount', () => {
  it('does not count archived active projects', () => {
    expect(
      selectActiveCount([
        { id: 'current', active: true, archived: false },
        { id: 'archived', active: true, archived: true },
      ]),
    ).toBe(1)
  })
})
TEST

npm test -- src/domain/Active_Count.test.ts
npm test
