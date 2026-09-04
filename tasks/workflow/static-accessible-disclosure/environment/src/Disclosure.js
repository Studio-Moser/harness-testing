export function initializeDisclosure(root = document) {
  const trigger = root.querySelector('#faq-trigger')
  const panel = root.querySelector('#faq-panel')

  trigger.addEventListener('click', () => {
    panel.hidden = !panel.hidden
  })
}
