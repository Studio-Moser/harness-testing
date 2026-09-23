import {it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
it('retains four routes and live feedback',()=>{for(const name of ['overview','projects','settings','activity']){const html=readFileSync(name+'.html','utf8');expect(html).toContain('aria-current="page"');expect(html).toContain('role="status"');}});
