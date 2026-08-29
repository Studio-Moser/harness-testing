#!/usr/bin/env bash
set -euo pipefail

cd /app
cat > src/Disclosure.js <<'EOF'
export function initializeDisclosure(root = document) {
  const trigger = root.querySelector('#faq-trigger')
  const panel = root.querySelector('#faq-panel')

  const toggle = () => {
    const expanded = trigger.getAttribute('aria-expanded') !== 'true'
    trigger.setAttribute('aria-expanded', String(expanded))
    panel.hidden = !expanded
  }

  trigger.addEventListener('click', toggle)
  trigger.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      toggle()
    } else if (event.key === ' ') {
      event.preventDefault()
    }
  })
  trigger.addEventListener('keyup', (event) => {
    if (event.key === ' ') {
      event.preventDefault()
      toggle()
    }
  })
}
EOF
npm test -- test/Disclosure.test.js
npm test
