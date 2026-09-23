// @vitest-environment happy-dom

import { createElement } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import App from './src/App.tsx'
import {
  loadSavedView,
  parseSavedView,
  SAVED_VIEW_KEY,
  saveSavedView,
  type ViewStorage,
} from './src/domain/Saved_View.ts'

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

describe('saved dashboard view oracle', () => {
  it.each(['all', 'active', 'archived'] as const)('accepts %s', (view) => {
    expect(parseSavedView(view)).toBe(view)
  })

  it.each([null, '', 'unexpected', 'Active', ' archived ', '"active"'])(
    'falls back without rewriting absent or invalid storage: %s', (value) => {
      const storage = memoryStorage(value)
      expect(parseSavedView(value)).toBe('all')
      expect(loadSavedView(storage)).toBe('all')
      expect(storage.values.get(SAVED_VIEW_KEY) ?? null).toBe(value)
    },
  )

  it('silently tolerates failed reads and writes', () => {
    const storage: ViewStorage = {
      getItem: () => { throw new Error('read unavailable') },
      setItem: () => { throw new Error('write unavailable') },
    }
    expect(loadSavedView(storage)).toBe('all')
    expect(() => saveSavedView('archived', storage)).not.toThrow()
  })

  it('persists every selection and restores transitions in either direction', () => {
    const storage = memoryStorage()
    for (const view of ['all', 'active', 'archived', 'active', 'all'] as const) {
      saveSavedView(view, storage)
      expect(storage.values.get(SAVED_VIEW_KEY)).toBe(view)
      expect(loadSavedView(storage)).toBe(view)
    }
  })
})

describe('saved project view oracle', () => {
  it.each([false, true])('keeps view controls usable with failed storage: %s', (failed) => {
    window.localStorage.clear()
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    if (failed) {
      // Mock the getter, not Happy DOM's Storage proxy: proxy method spies can
      // survive restoreAllMocks and contaminate the following reload checks.
      vi.spyOn(window, 'localStorage', 'get').mockReturnValue({
        getItem: () => { throw new Error('read unavailable') },
        setItem: () => { throw new Error('write unavailable') },
      } as Storage)
    }
    try {
      flushSync(() => root.render(createElement(App)))
      for (const view of ['all', 'active', 'archived', 'active', 'all']) {
        const button = Array.from(container.querySelectorAll('button')).find(
          (candidate) => candidate.textContent === view,
        )!
        flushSync(() => button.click())
        expect(button.getAttribute('aria-pressed')).toBe('true')
        expect(container.querySelectorAll('[aria-pressed="true"]')).toHaveLength(1)
        expect(container.textContent?.includes('Current launch')).toBe(view !== 'archived')
        expect(container.textContent?.includes('Archived migration')).toBe(view !== 'active')
        if (!failed) expect(window.localStorage.getItem(SAVED_VIEW_KEY)).toBe(view)
      }
    } finally {
      flushSync(() => root.unmount())
      container.remove()
      vi.restoreAllMocks()
    }
  })

  it('restores an archived view on reload', () => {
    window.localStorage.clear()
    window.localStorage.setItem(SAVED_VIEW_KEY, 'archived')

    const markup = renderToStaticMarkup(createElement(App))
    document.body.innerHTML = markup
    const archivedButton = Array.from(document.querySelectorAll('button')).find(
      (button) => button.textContent === 'archived',
    )

    expect(markup).toContain('Archived migration')
    expect(markup).not.toContain('Current launch')
    expect(archivedButton?.getAttribute('aria-pressed')).toBe('true')
  })

  it('falls back to all for invalid storage', () => {
    window.localStorage.clear()
    window.localStorage.setItem(SAVED_VIEW_KEY, 'invalid')
    const markup = renderToStaticMarkup(createElement(App))

    expect(markup).toContain('Current launch')
    expect(markup).toContain('Archived migration')
  })
})
