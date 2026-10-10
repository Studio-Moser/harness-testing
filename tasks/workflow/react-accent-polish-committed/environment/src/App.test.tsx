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

describe('dashboard accent polish', () => {
  it('uses the requested call-to-action token', () => {
    expect(customProperty('--cta-background')).toBe('#6d28d9')
  })

  it('keeps rendering the dashboard', () => {
    expect(renderToStaticMarkup(<App />)).toContain('New project')
  })
})
