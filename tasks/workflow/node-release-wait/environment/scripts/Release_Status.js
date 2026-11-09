import { appendFileSync, readFileSync } from 'node:fs';

const read = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const { version } = read('../release.json');
const status = read('../release/Registry.json').published.includes(version) ? 'published' : 'pending';
appendFileSync(new URL('../Release Status.log', import.meta.url), `${new Date().toISOString()} ${version} ${status}\n`);
console.log(`Release ${version}: ${status}`);
