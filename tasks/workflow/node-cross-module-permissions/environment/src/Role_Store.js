export class RoleStore {
  constructor() { this.records = new Map(); this.reads = 0; }
  key(user, workspace) { return JSON.stringify([user, workspace]); }
  set(user, workspace, role) { const key=this.key(user,workspace); this.records.set(key,{role,revision:(this.records.get(key)?.revision??0)+1}); }
  role(user, workspace) { this.reads++; return this.records.get(this.key(user,workspace))?.role ?? 'none'; }
  revision(user, workspace) { return this.records.get(this.key(user,workspace))?.revision ?? 0; }
}
