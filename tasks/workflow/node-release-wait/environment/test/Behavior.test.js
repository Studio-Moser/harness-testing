import {it,expect} from 'vitest';
import {releaseNotes} from '../src/Release_Notes.js';
it('keeps the earlier release entry',()=>expect(releaseNotes.at(-1)).toEqual({version:'1.4.0',highlights:['Tasks can be filtered by label']}));
