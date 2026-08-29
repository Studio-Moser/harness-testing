import { readFileSync } from 'node:fs'

const [filePath, ...tokens] = process.argv.slice(2)

if (!filePath || tokens.length === 0) {
  console.error('usage: Check_Token.mjs FILE TOKEN [TOKEN...]')
  process.exit(2)
}

const contents = readFileSync(filePath, 'utf8')
const missing = tokens.filter((token) => !contents.includes(token))

if (missing.length > 0) {
  console.error(`missing expected token(s) in ${filePath}: ${missing.join(', ')}`)
  process.exit(1)
}
