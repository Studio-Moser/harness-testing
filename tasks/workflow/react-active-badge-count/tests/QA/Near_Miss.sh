#!/usr/bin/env bash
set -euo pipefail

cd /app
cat > src/domain/Active_Count.test.ts <<'TEST'
import { describe, expect, it } from 'vitest'
import { selectActiveCount } from './Active_Count.ts'

describe('selectActiveCount', () => {
  it('counts one ordinary active project', () => {
    expect(
      selectActiveCount([{ id: 'current', active: true, archived: false }]),
    ).toBe(1)
  })
})
TEST
npm test -- src/domain/Active_Count.test.ts
