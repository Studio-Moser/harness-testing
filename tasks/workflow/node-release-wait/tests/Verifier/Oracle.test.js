import {it,expect} from 'vitest';
import {releaseNotes} from './src/Release_Notes.js';
it('drafts the 2.0.0 entry first and keeps the earlier one',()=>{expect(releaseNotes).toEqual([{version:'2.0.0',highlights:['Tasks can be archived','Search is faster on large lists']},{version:'1.4.0',highlights:['Tasks can be filtered by label']}]);});
