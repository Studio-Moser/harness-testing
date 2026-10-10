import { readFile } from 'node:fs/promises'

import { Window } from 'happy-dom'
import { describe, expect, it } from 'vitest'

const fixtureUrl = new URL('../', import.meta.url)

describe('pricing card', () => {
  it('renders the requested sentence and applies the frozen gap token', async () => {
    const [html, css] = await Promise.all([
      readFile(new URL('index.html', fixtureUrl), 'utf8'),
      readFile(new URL('styles.css', fixtureUrl), 'utf8'),
    ])
    const window = new Window()
    window.document.write(html)
    const style = window.document.createElement('style')
    style.textContent = css
    window.document.head.append(style)

    const card = window.document.querySelector('.pricing-card')

    expect(card?.querySelector('p')?.textContent).toBe(
      'Everything your team needs to ship.',
    )
    expect(window.getComputedStyle(card).gap).toBe('1.5rem')
    expect(window.getComputedStyle(window.document.documentElement).getPropertyValue(
      '--pricing-card-gap',
    )).toBe('1.5rem')
  })
})
