import {it,expect} from 'vitest';
import {isAtCapacity} from './src/Capacity.js';
it('treats the exact boundary as full including zero capacity',()=>{for(const limit of [0,1,2,9,100])for(let count=0;count<=limit+1;count++)expect(isAtCapacity(count,limit)).toBe(count>=limit);});
