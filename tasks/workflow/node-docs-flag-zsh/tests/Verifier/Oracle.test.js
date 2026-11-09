import {it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
const read=(path)=>readFileSync(new URL(path,import.meta.url),'utf8');
it('uses the replacement flag in the pages and keeps the history',()=>{for(const page of ['docs/Getting_Started.md','docs/guides/Offline_Mode.md','docs/reference/cli/Sync.md','docs/reference/Configuration.md']){expect(read(page)).not.toContain('--legacy-sync');expect(read(page)).toContain('--sync=full');}expect(read('docs/History.txt').match(/--legacy-sync/g)).toHaveLength(2);});
