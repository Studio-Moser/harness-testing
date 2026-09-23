import {it,expect} from 'vitest';
import {toggleDone} from '../src/Completion.js';
it('exports a callable helper',()=>expect(typeof toggleDone).toBe('function'));
