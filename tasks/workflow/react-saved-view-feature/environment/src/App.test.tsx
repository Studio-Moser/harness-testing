// @vitest-environment happy-dom

import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it } from 'vitest'

import App from './App.tsx'
import { SAVED_VIEW_KEY } from './domain/Saved_View.ts'

describe('saved project view', () => {
  beforeEach(() => window.localStorage.clear())

  it('restores an archived view on reload', () => {
    window.localStorage.setItem(SAVED_VIEW_KEY, 'archived')

    const markup = renderToStaticMarkup(<App />)
    document.body.innerHTML = markup
    const archivedButton = Array.from(document.querySelectorAll('button')).find(
      (button) => button.textContent === 'archived',
    )

    expect(markup).toContain('Archived migration')
    expect(markup).not.toContain('Current launch')
    expect(archivedButton?.getAttribute('aria-pressed')).toBe('true')
  })

  it('falls back to all for invalid storage', () => {
    window.localStorage.setItem(SAVED_VIEW_KEY, 'invalid')
    const markup = renderToStaticMarkup(<App />)

    expect(markup).toContain('Current launch')
    expect(markup).toContain('Archived migration')
  })
})
