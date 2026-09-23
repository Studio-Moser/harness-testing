import {it,expect} from 'vitest';
import {serializeCsv} from '../src/Serializer.js';
it('quotes values and preserves Unicode and line breaks',()=>{expect(serializeCsv([['name','note'],['Café','Line\n"quoted"']])).toBe('"name","note"\r\n"Café","Line\n""quoted"""\r\n');});
it('does not mutate its input',()=>{const rows=Object.freeze([Object.freeze(['first','second'])]);expect(serializeCsv(rows)).toBe('"first","second"\r\n');expect(rows).toEqual([['first','second']]);});
