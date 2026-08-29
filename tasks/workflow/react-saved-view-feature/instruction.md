Work in `/app` and complete saved dashboard views for the `all`, `active`, and
`archived` states. Persist the current view under `dashboard.saved-view`, restore it
on reload, and fall back to `all` when the stored value is absent or invalid.

Use `npm run test:saved-view` and `npm run test:view-filter` for focused checks while
working. After the feature is complete, run `npm run gate` exactly once as the final
checkpoint.

Do not modify the project tests, package metadata, build configuration, or check
scripts. Keep storage access behind the existing saved-view functions.
