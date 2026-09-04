// @vitest-environment happy-dom

import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App from './App.tsx'

function customProperty(name: string): string {
  const css = readFileSync('src/index.css', 'utf8')
  const sheet = new CSSStyleSheet()
  sheet.replaceSync(css)
  const rootRule = Array.from(sheet.cssRules).find(
    (rule): rule is CSSStyleRule =>
      rule instanceof CSSStyleRule && rule.selectorText === ':root',
  )

  return rootRule?.style.getPropertyValue(name).trim() ?? ''
}

describe('grouped dashboard updates', () => {
  it('uses the requested accent token', () => {
    expect(customProperty('--accent')).toBe('#6d28d9')
  })

  it('renders the requested empty-state heading', () => {
    expect(renderToStaticMarkup(<App />)).toContain('No projects yet')
  })

  it('uses the requested card spacing token', () => {
    expect(customProperty('--card-gap')).toBe('12px')
  })
})
