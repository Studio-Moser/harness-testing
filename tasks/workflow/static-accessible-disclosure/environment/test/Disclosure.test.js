import { readFile } from 'node:fs/promises'

import { Window } from 'happy-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { initializeDisclosure } from '../src/Disclosure.js'

let window
let trigger
let panel

beforeEach(async () => {
  window = new Window()
  window.document.write(
    await readFile(new URL('../index.html', import.meta.url), 'utf8'),
  )
  initializeDisclosure(window.document)
  trigger = window.document.querySelector('#faq-trigger')
  panel = window.document.querySelector('#faq-panel')
})

function expectCollapsed(collapsed) {
  expect(trigger.getAttribute('aria-expanded')).toBe(String(!collapsed))
  expect(panel.hidden).toBe(collapsed)
}

describe('FAQ disclosure', () => {
  it('keeps ARIA and visibility synchronized after a click', () => {
    trigger.click()
    expectCollapsed(false)

    trigger.click()
    expectCollapsed(true)
  })

  it('toggles with Enter', () => {
    trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter' }))
    expectCollapsed(false)
  })

  it('toggles with Space without changing state on keydown alone', () => {
    trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: ' ' }))
    expectCollapsed(true)
    trigger.dispatchEvent(new window.KeyboardEvent('keyup', { key: ' ' }))
    expectCollapsed(false)
  })
})
