#!/usr/bin/env sh
set -eu
cd /app
cat > 'src/Permissions.js' <<'FIXTURE_EOF'
export class Permissions {
  constructor(store) { this.store = store; this.cache = new Map(); }
  can(user, workspace, action) {
    const key = JSON.stringify([user, workspace]);
    const revision = this.store.revision(user, workspace);
    if (!this.cache.has(key)) this.cache.set(key, {revision, role: this.store.role(user, workspace)});
    const role = this.cache.get(key).role;
    return role === 'owner' || (action === 'read' && role === 'viewer');
  }
}
FIXTURE_EOF
