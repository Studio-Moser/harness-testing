import {it, expect} from 'vitest';
import {pageOf} from './src/Pagination.js';

it('applies the corrected error contract without changing pagination', () => {
  for (const [page,size] of [[0,1],[-1,2],[1.5,2],[1,0],[1,101],[1,2.5],[NaN,1],[1,Infinity]]) {
    expect(() => pageOf([],page,size)).toThrow(RangeError);
  }
});
