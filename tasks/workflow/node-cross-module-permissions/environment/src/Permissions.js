export class Permissions {
  constructor(store) { this.store = store; this.cache = new Map(); }
  can(user, workspace, action) {
    if (!this.cache.has(user)) this.cache.set(user, this.store.role(user, workspace));
    return this.cache.get(user) === 'owner' || (action === 'read' && this.cache.get(user) === 'viewer');
  }
}
