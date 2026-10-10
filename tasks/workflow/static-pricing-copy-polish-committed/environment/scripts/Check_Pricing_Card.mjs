import { readFile } from 'node:fs/promises'

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
const css = await readFile(new URL('../styles.css', import.meta.url), 'utf8')

if (!html.includes('Everything your team needs to ship.')) {
  throw new Error('pricing-card copy is not updated')
}
if (!css.includes('--pricing-card-gap: 1.5rem')) {
  throw new Error('pricing-card gap token is not updated')
}
