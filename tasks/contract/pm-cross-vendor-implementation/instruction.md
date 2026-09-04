# Implement one ready PM slice through Harness

`/app/Ready_Slice.json` is the only ready item. Its public contract is available through `harness-stub describe` if needed. Use the synthetic Harness endpoint through:

```text
harness-stub ACTION 'JSON_OBJECT'
```

Dispatch one provider-neutral `bulk` Harness request for that slice. Preserve the exact working directory, allowed paths, tools, approvals, and verification seam from the input. Do not select a provider or model yourself. Materialize the returned artifact, reproduce the returned proof in the parent, and write the complete public HarnessResult to `/app/Harness_Result.json`.

Do not read or act on backlog items outside the ready slice. Do not branch, commit, push, or run a repository-wide test suite.
