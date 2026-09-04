# Independently review one immutable target

Review the current repository commit through the synthetic Harness endpoint. Its public contract is available through `harness-stub describe` if needed; dispatch with:

```text
harness-stub ACTION 'JSON_OBJECT'
```

Freeze the commit before dispatch. The independent-review cost is already approved for this synthetic task. Request the `independent` route with fresh context, read-only source authority, and no builder conclusions. Write the returned report to `/app/Review.md`, reproduce the report seam against the unchanged target, and write the complete public HarnessResult to `/app/Harness_Result.json`.

Do not edit the source, change the target, or use a conclusion from the implementing agent. Do not branch, commit, push, or run a repository-wide suite.
