import {it,expect} from 'vitest';
import {pageOf} from '../src/Pagination.js';
it('paginates in order without mutation',()=>{const rows=Object.freeze([1,2,3,4,5]);expect(pageOf(rows,1,2)).toEqual({items:[1,2],total:5,pages:3});expect(pageOf(rows,3,2)).toEqual({items:[5],total:5,pages:3});expect(pageOf(rows,4,2).items).toEqual([]);});
it('handles empty and exact-boundary collections',()=>{expect(pageOf([],1,10)).toEqual({items:[],total:0,pages:0});expect(pageOf([1,2],1,2).pages).toBe(1);});
it('rejects invalid pages and sizes',()=>{for(const [page,size] of [[0,1],[-1,2],[1.5,2],[1,0],[1,101],[1,2.5],[NaN,1],[1,Infinity]])expect(()=>pageOf([],page,size)).toThrow(Error);});
