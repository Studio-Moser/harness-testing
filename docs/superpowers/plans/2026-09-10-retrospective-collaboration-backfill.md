# Retrospective Collaboration Backfill Plan

**Goal:** Re-evaluate the completed Quill harness comparison with the new collaboration metrics without rerunning its coding trials.

**Architecture:** Read only the finalized source report, its named Harbor job directories, retained ATIF trajectories, one explicit communication contract, and the original task instruction. Reconstruct the root-visible transcript deterministically, record every input digest in an ignored evidence plan, and write an immutable superseding report with an explicit retrospective limitation. The existing blind-grading path then consumes the backfilled transcript and falls back to its first user message for research tasks that do not live in the workflow pack.

## Steps

1. Add failing tests for ATIF transcript reconstruction, mismatched task instructions, immutable source handling, and research-task grading packets.
2. Add the narrow backfill module and `harness-test collaboration backfill` command.
3. Backfill the reviewed three-contender Quill report from retained local Harbor artifacts.
4. Prepare the exact blinded grading plan without starting a model.
5. Run focused and full validation, then update PR #8.
