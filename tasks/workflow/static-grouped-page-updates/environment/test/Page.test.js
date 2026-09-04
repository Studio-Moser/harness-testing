import { readFile } from 'node:fs/promises'

import { Window } from 'happy-dom'
import { describe, expect, it } from 'vitest'

describe('landing page', () => {
  it('contains every grouped outcome in the rendered DOM and styles', async () => {
    const [html, css] = await Promise.all([
      readFile(new URL('../index.html', import.meta.url), 'utf8'),
      readFile(new URL('../styles.css', import.meta.url), 'utf8'),
    ])
    const window = new Window()
    window.document.write(html)
    const style = window.document.createElement('style')
    style.textContent = css
    window.document.head.append(style)

    const main = window.document.querySelector('main#main-content')

    expect(window.document.querySelector('.hero h1')?.textContent).toBe(
      'Build calmer workflows',
    )
    expect(main?.querySelectorAll('section')).toHaveLength(2)
    expect(window.getComputedStyle(window.document.documentElement).getPropertyValue(
      '--section-gap',
    )).toBe('4rem')
  })
})
