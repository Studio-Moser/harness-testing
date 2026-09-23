#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Permissions.js' <<'FIXTURE_EOF'
export class Permissions {
  constructor(store) { this.store = store; this.cache = new Map(); }
  can(user, workspace, action) {
    const key = JSON.stringify([user, workspace]);
    const revision = this.store.revision(user, workspace);
    if (this.cache.get(key)?.revision !== revision) this.cache.set(key, {revision, role: this.store.role(user, workspace)});
    const role = this.cache.get(key).role;
    return role === 'owner' || (action === 'read' && role === 'viewer');
  }
}
FIXTURE_EOF
cat > test/Revocation.test.js <<'FIXTURE_EOF'
import {it,expect} from 'vitest';
import {Permissions} from '../src/Permissions.js';
import {RoleStore} from '../src/Role_Store.js';
it('invalidates a warmed role after revocation',()=>{
  const store=new RoleStore(); store.set('u','a','owner'); const permissions=new Permissions(store);
  expect(permissions.can('u','a','write')).toBe(true);
  store.set('u','a','none'); expect(permissions.can('u','a','write')).toBe(false);
});
FIXTURE_EOF
npm test
