import { readFile } from 'node:fs/promises'

import { Window } from 'happy-dom'
import { expect, it } from 'vitest'

it('uses a native button connected to the controlled panel', async () => {
  const window = new Window()
  window.document.write(
    await readFile(new URL('../index.html', import.meta.url), 'utf8'),
  )
  const trigger = window.document.querySelector('button#faq-trigger')

  expect(trigger?.getAttribute('aria-controls')).toBe('faq-panel')
  expect(window.document.querySelector('#faq-panel')).not.toBeNull()
})
