import { describe, expect, it } from 'vitest'

function memoryStorage(initial: Record<string, string> = {}): {
  values: Map<string, string>
  getItem(key: string): string | null
  setItem(key: string, value: string): void
} {
  const values = new Map(Object.entries(initial))
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  }
}

describe('memory storage test helper', () => {
  it('returns initial values and null for missing keys', () => {
    const storage = memoryStorage({ existing: 'value' })
    expect(storage.getItem('existing')).toBe('value')
    expect(storage.getItem('missing')).toBeNull()
  })

  it('stores values by key', () => {
    const storage = memoryStorage()
    storage.setItem('chosen', 'value')
    expect(storage.values.get('chosen')).toBe('value')
  })
})
