# Approval Handling Fix Plan

Outcome: continue through routine local plan/design approvals, classify unanswered
requests as incomplete work, and distinguish missing review from failed checks.

Blockers: none. The user requested continuation after the interrupted session.
Proof so far: all five stopped pilot trials reproduce without model calls; four
imperative approval requests become completed while one question becomes a gap.
Testing seam: scripted-user and native-conversation unit tests, dashboard render
tests, and replay of retained pilot terminal messages without model execution.

1. Add regression cases for a plan followed by an approval question or request,
   including imperative requests with no question mark and actual completion text.
2. Keep replies constrained to authored policy facts. Support routine approvals
   under frozen task rules; do not grant tool actions or broader authority. Preserve
   ambiguity, unknown requests, interaction limits, and the 8192-character limit.
3. Update the narrow workflow policy rules as needed and make unanswered approval
   requests produce `task_definition_gap`, regardless of terminal punctuation.
   Preserve original cached task definitions and reports; new inputs receive new
   digests through normal planning.
4. Correct the dashboard labels: missing review is not failed task checks, and
   a failed protected-state check does not necessarily prove files were changed.
5. Reproduce targeted checks, run repository tests/static checks/build, inspect
   the real dashboard, and obtain a normal Harness review of a pinned patch.
6. Commit the verified fix locally and prepare a fresh 12-trial Sol Low request
   with identical harnesses, tasks and kickoff. Execution requires approval of the
   new manifest; the completed original experiment is retained as diagnostic data.

Delegation: one bounded implementation worker owns runner/policy code and Python
tests; the parent owns dashboard labels, documentation and run preparation. File
ownership is disjoint. No new dependencies or benchmark model calls are needed
to prove the fixes.
