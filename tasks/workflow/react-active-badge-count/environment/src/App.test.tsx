import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App from './App.tsx'
import { selectActiveCount } from './domain/Active_Count.ts'

describe('active project badge', () => {
  it('excludes archived projects from the active count', () => {
    expect(
      selectActiveCount([
        { id: 'current', active: true, archived: false },
        { id: 'archived', active: true, archived: true },
        { id: 'paused', active: false, archived: false },
      ]),
    ).toBe(1)
  })

  it('renders the corrected count', () => {
    expect(renderToStaticMarkup(<App />)).toContain('1 active')
  })
})
