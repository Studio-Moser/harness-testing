# Fan out and synthesize a local Product Pulse

Read `/app/Sources.json`. The public contract is available through `harness-stub describe` if needed. Use the synthetic Harness endpoint through `harness-stub ACTION 'JSON_OBJECT'`.

Dispatch each local source branch on the `bulk` route, then pass only accepted, proven branch evidence to one `taste` synthesis. Preserve source citations, caveats, the recommendation cap, deduplication, and the publication boundary. Reproduce both source and synthesis seams, write the returned report to `/app/Product_Pulse.md`, and write the complete public HarnessResult to `/app/Harness_Result.json`.

The domain owns the research questions and source rules; do not select providers or models. Do not use PM lifecycle, branch, commit, push, or run a repository-wide test suite.
