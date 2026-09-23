import {it,expect} from 'vitest';
import {exportRows} from './src/Export.js';
it('exports only visible records and allowed columns',()=>{expect(exportRows([{id:1,title:'One',email:'private',visible:true},{id:2,title:'Hidden',visible:false}])).toBe('"id","title"\r\n"1","One"\r\n');});
it('preserves quoting Unicode and source order without mutation',()=>{const rows=Object.freeze([Object.freeze({id:3,title:'Café, "yes"',visible:true}),Object.freeze({id:1,title:'Line\nbreak',visible:true})]);expect(exportRows(rows)).toBe('"id","title"\r\n"3","Café, ""yes"""\r\n"1","Line\nbreak"\r\n');});
it('emits header for empty input and excludes private values',()=>{expect(exportRows([])).toBe('"id","title"\r\n');expect(exportRows([{id:1,title:'x',email:'secret-email',visible:true}])).not.toContain('secret-email');});
