// @vitest-environment happy-dom

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App from './App.tsx'

describe('dashboard shell', () => {
  it('renders the existing project view controls', () => {
    const markup = renderToStaticMarkup(<App />)
    expect(markup).toContain('<main class="dashboard-shell">')
    expect(markup).toContain('aria-label="Project views"')
  })
})
