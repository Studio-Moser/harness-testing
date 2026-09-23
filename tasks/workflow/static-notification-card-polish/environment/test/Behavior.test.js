import {it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
it('retains the save control and live status',()=>{const text=readFileSync('index.html','utf8');expect((text.match(/<button\b/g)||[]).length).toBe(1);expect(text).toContain('role="status"');});
