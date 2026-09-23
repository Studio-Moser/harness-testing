import {it,expect} from 'vitest';
import {isAtCapacity} from '../src/Capacity.js';
it('distinguishes below and above capacity',()=>{expect(isAtCapacity(1,3)).toBe(false);expect(isAtCapacity(4,3)).toBe(true);});
