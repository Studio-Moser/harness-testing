# Execute one bounded non-development transform

Read `/app/Records.json`. Use `harness-stub ACTION 'JSON_OBJECT'` to request one `quick` transformation into `/app/Summary.json`, then directly verify its structure and traceability.

Write the complete public HarnessResult to `/app/Harness_Result.json`. This is a data transformation, not development work: do not start PM/tracker lifecycle, edit code, run automated tests, create a branch, commit, open a PR, or push.
