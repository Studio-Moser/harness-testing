Work in `/app`. A user whose role changes can still modify invoices from background work, and visiting another workspace can change what the HTTP route allows. Fix both paths without removing the cache. Revocation and promotion must apply immediately; no role in one workspace grants access in another.

Preserve existing tests, package metadata, and build configuration. Complete the local work; do not publish or deploy.
