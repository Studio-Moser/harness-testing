import {describe,it,expect} from 'vitest';
import {Permissions} from '../src/Permissions.js';
import {RoleStore} from '../src/Role_Store.js';
import {updateInvoice} from '../src/Http.js';
import {runInvoiceJob} from '../src/Worker.js';
describe('shared authorization',()=>{
  it('isolates tenant roles in either access order',()=>{for(const reverse of [false,true]){const s=new RoleStore(); s.set('u','a','owner');s.set('u','b','viewer');const p=new Permissions(s);for(const w of reverse?['b','a']:['a','b']) expect(updateInvoice(p,'u',w)).toBe(w==='a'?200:403);}});
  it('revocation and promotion reach HTTP and jobs immediately',()=>{const s=new RoleStore();const p=new Permissions(s);for(const role of ['owner','viewer','none','owner']){s.set('u','a',role);expect(updateInvoice(p,'u','a')).toBe(role==='owner'?200:403);expect(runInvoiceJob(p,{user:'u',workspace:'a'})).toBe(role==='owner'?'updated':'denied');}});
  it('retains hits and isolates ambiguous composite keys',()=>{const s=new RoleStore();s.set('a:b','c','owner');s.set('a','b:c','none');const p=new Permissions(s);expect(p.can('a:b','c','write')).toBe(true);expect(p.can('a','b:c','write')).toBe(false);const before=s.reads;for(let i=0;i<5;i++)p.can('a:b','c','write');expect(s.reads).toBe(before);});
  it('grants read only to viewers and nothing to unknown users',()=>{const s=new RoleStore();s.set('v','a','viewer');const p=new Permissions(s);expect(p.can('v','a','read')).toBe(true);expect(p.can('v','a','write')).toBe(false);expect(p.can('unknown','a','read')).toBe(false);});
});
