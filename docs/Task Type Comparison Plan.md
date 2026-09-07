# Task Type Comparison Plan

Outcome: show how the selected harness comparison performed within each existing
task class, with direct links to its trial evidence. User approved this addition.

1. Map the nine workflow task IDs to their existing `task.toml` change classes;
   classify the documented Quill pilot as a feature. Preserve frozen task and
   report bytes. New IDs remain explicitly unclassified until mapped.
2. Aggregate only the selected comparison and its explicitly attached baselines,
   using scheduled task/repetition slots. Missing or ambiguous evidence and
   incomplete usage remain unknown.
3. Add a compact “By task type” section with observed test/review outcomes, cost,
   time, tokens, and task coverage. Keep untested types visible. These descriptive
   summaries do not create category winners or change the runner's decision policy.
4. Link each type and harness to filtered task evidence; preserve the selected
   comparison and show explicit empty/invalid selections.
5. Verify mixed categories, missing/duplicate evidence, unknown usage, review
   limitations, baseline isolation, and filter behavior with dashboard tests.
   Build and inspect the real reviewed Quill report in the browser.
6. Run repository checks and a normal Harness review of a pinned patch; address
   findings and commit locally. No benchmark execution or publication is needed.

Blockers: none. Existing dashboard styling and task definitions supply the design
and classification. Small changes include both bug fixes and focused behaviors;
do not describe all small tasks as bug fixes.

Testing seam: `npm test` and `npm run build` in `dashboard`; repository Python
suite and static checks; live comparison and task evidence views.

Proof: the Quill comparison shows feature results and explicitly untested other
types; clicking its type or harness link preserves the exact evidence selection.
