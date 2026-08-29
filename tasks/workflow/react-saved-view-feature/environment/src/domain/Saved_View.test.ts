import { describe, expect, it } from 'vitest'

import {
  loadSavedView,
  parseSavedView,
  SAVED_VIEW_KEY,
  saveSavedView,
  type ViewStorage,
} from './Saved_View.ts'

function memoryStorage(initial: string | null = null): ViewStorage & {
  values: Map<string, string>
} {
  const values = new Map<string, string>()
  if (initial !== null) values.set(SAVED_VIEW_KEY, initial)
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  }
}

describe('saved dashboard view', () => {
  it.each(['all', 'active', 'archived'] as const)('accepts %s', (view) => {
    expect(parseSavedView(view)).toBe(view)
  })

  it('falls back to all for absent or invalid values', () => {
    expect(parseSavedView(null)).toBe('all')
    expect(parseSavedView('unexpected')).toBe('all')
  })

  it('persists and restores the selected view', () => {
    const storage = memoryStorage()
    saveSavedView('archived', storage)
    expect(storage.values.get(SAVED_VIEW_KEY)).toBe('archived')
    expect(loadSavedView(storage)).toBe('archived')
  })
})
