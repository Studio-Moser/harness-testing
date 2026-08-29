Work in `/app` and fix `selectActiveCount` so archived projects never contribute to
the active badge, even when their `active` field is true.

Add the regression test `src/domain/Active_Count.test.ts` and run it with
`npm test -- src/domain/Active_Count.test.ts` while working. After the fix and its
regression test are complete, run the package unit suite with `npm test` exactly once.

Do not modify the project tests, package metadata, build configuration, or check
scripts. Keep the production change limited to the active-count behavior.
