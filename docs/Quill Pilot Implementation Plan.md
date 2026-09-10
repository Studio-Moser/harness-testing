# Quill Pilot Implementation Plan

> Required execution: use subagent-driven development for the bounded runner integration; the parent independently verifies the actual environment and grader.

**Goal:** prepare the queued Quill task for one sequential native trial each of Nothing, Superpowers and full Studio Moser, using Astra High at kickoff and normal child routing.

**Architecture:** extend the existing DeepSWE materializer and versioned comparison path. Preserve upstream task/grader bytes and immutable source/image provenance. Keep existing local fixtures and six-task research behavior compatible. Use the existing Harbor, native conversation, scripted user and whole-tree report mechanisms; add no framework or dependencies.

**Delivery slice:** the versioned request compiler produces three Quill jobs whose artifacts reach the hidden verifier and whose reports distinguish correctness, protected-state evidence and complete usage. Blockers are the current local-only compiler and unverified model-free grading. The highest stable proof is actual no-op/reference Harbor grading on the pinned environment plus request/job/report integration tests. This proof is currently unproven.

1. Add explicit task selection to `Materialize.py` and the DeepSWE CLI. Reject unknown/duplicate selections, isolate subset cache identities, and retain exact original image and source verification. Test subset preparation/reuse and full-cohort compatibility in `test_Materialize.py`.
2. Extend `Experiment Request.schema.json`, `Experiments.py` and `Runs.py` to accept the selected DeepSWE diagnostic task, freeze actual task images/resources/policy, and use the existing native contender path. Keep ordinary comparison requests unchanged. Test planning and execution-input validation.
3. Preserve the exact upstream instruction and hidden grader. Supply a frozen scripted-user policy for routine local implementation/plan approval without adding forced delegation. Ensure final patch collection includes committed and uncommitted changes relative to the pinned base.
4. Verify reward and protected-state semantics in `Experiment_Reports.py`; never infer protected state from an unfamiliar grader's pass alone. Keep incomplete/unknown evidence explicit. Test reward/report behavior with representative upstream output.
5. Prepare only Quill in ignored cache; run actual model-free no-op/reference checks and inspect artifacts. Do not expose solutions or hidden tests to benchmark agents. Investigate failures before model execution.
6. Run targeted tests, then the full Python suite once; review a frozen diff and resolve findings. Update the existing agent guide/capability queue only where actual commands or status changed.
7. Compile a fresh exact three-root diagnostic manifest with subscription billing, concurrency one, bounded timeout and stated normalized allowance. Follow the exact-manifest execution gate; preserve prior runs and leave the 81-trial cohort unexecuted.

Local image download/build and model-free verification are part of preparation. No publication, new baseline cohort, extra repetition or unrelated cleanup is included.
