import {it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {join} from 'node:path';
const pages=(dir)=>readdirSync(dir,{withFileTypes:true}).flatMap((entry)=>entry.isDirectory()?pages(join(dir,entry.name)):entry.name.endsWith('.md')?[join(dir,entry.name)]:[]);
it('gives every docs page a title',()=>{const found=pages('docs');expect(found.length).toBe(6);for(const page of found)expect(readFileSync(page,'utf8')).toMatch(/^# \S/);});
