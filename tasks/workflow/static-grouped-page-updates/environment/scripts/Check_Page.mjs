import { readFile } from 'node:fs/promises'

const check = process.argv[2]
const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
const css = await readFile(new URL('../styles.css', import.meta.url), 'utf8')

const checks = {
  hero: html.includes('<h1>Build calmer workflows</h1>'),
  spacing: css.includes('--section-gap: 4rem'),
  main:
    html.includes('<main id="main-content" class="page-shell">') &&
    html.includes('</main>'),
}

if (!(check in checks) || !checks[check]) {
  throw new Error(`page check failed: ${check}`)
}
