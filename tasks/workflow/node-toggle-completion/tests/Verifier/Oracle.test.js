import {it,expect} from 'vitest';
import {toggleDone} from './src/Completion.js';
it('toggles both ways without mutation or losing unrelated values',()=>{for(const done of [false,true]){const nested={owner:'team'};const key=Symbol('metadata');const task=Object.freeze({id:3,title:'Review',done,nested,[key]:7});const result=toggleDone(task);expect(result).not.toBe(task);expect(result).toEqual({...task,done:!done});expect(result.nested).toBe(nested);expect(result[key]).toBe(7);expect(task.done).toBe(done);expect(toggleDone(result)).toEqual(task);}});
