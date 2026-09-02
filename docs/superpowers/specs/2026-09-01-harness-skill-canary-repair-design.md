# Harness Skill Canary Repair Design

**Status:** Approved
**Date:** 2026-09-01
**Scope:** Repair Studio Harness skill activation, terminal-result encoding, and
reference-loading churn exposed by the repaired Harness Testing delivery canary.

## Context

The approved `missing-rubric` canary completed four Claude/Codex A0/A2 sessions
without infrastructure errors. Delivery isolation worked: A0 had no benchmark
plugin, and A2 loaded only Studio Harness 0.8.1. Every cell performed the
required lookup, but every correctness score was zero.

The first inspection classified the task as unfair because the protected result
expects exact evidence and blocker prefixes. Repository authoring rules show
that strict prefix scoring is deliberate: contract correctness is all-or-
nothing, and decisive evidence must begin a distinct check. The scorer and task
prompt therefore remain unchanged.

The observed failures instead identify three Studio Harness defects:

1. The `execute` skill description names implementation requests but not typed
   routing or pre-dispatch blockers. Claude A2 received the plugin but never
   invoked the skill.
2. The skill does not define the stable terminal encoding required for a typed
   pre-dispatch blocker: exact reason propagation, a fixed-path locator,
   decisive evidence first, and a reason-prefixed blocker.
3. The skill tells agents to read six references unconditionally. Codex A2 read
   625 lines / 30,907 bytes before one lookup. Its provider-reported prompt
   usage rose from 76,846 tokens in A0 to 130,345 in A2, and its API-equivalent
   trajectory cost rose from $0.0512 to $0.0987.

Current Anthropic guidance confirms that only skill metadata should load at
startup, `SKILL.md` should load after a request matches, and supporting
references should load individually as needed. The current unconditional read
instruction defeats that progressive-disclosure boundary.

## Goals

1. Make Claude discover `harness:execute` for explicit Harness routing and
   pre-dispatch blocker requests.
2. Give Claude and Codex one deterministic positive recipe for a blocked
   `HarnessResult` without revealing benchmark answers.
3. Load only references required by the active execution path.
4. Preserve every existing authority, routing, fallback, verification, and
   Shelby invariant.
5. Validate the repair with the smallest model-backed comparison that can prove
   the two observed provider failures.

## Non-goals

- Relaxing contract correctness, evidence-prefix matching, protected workflow,
  or efficiency scoring.
- Changing the `missing-rubric` instruction, protected expectation, fixture, or
  model-visible task digest.
- Redesigning Harness routing, adapters, setup, review, computer use, or Shelby.
- Merging unrelated work from the existing `fix/narrow-harness-delegation`
  checkout.
- Re-running A0 cells whose delivery and behavior are already preserved.
- Running a full benchmark before the repaired A2 canary passes.

## Decision 1: fix the production skill, not the benchmark

Studio Harness owns the missing semantics. Keep the Harness Testing scorer and
task unchanged. Update the production `execute` skill so an agent can derive
the protected result from the task-visible typed response and documented path.

The skill description will cover only explicit Harness work: bounded execution,
semantic routing, and typed pre-dispatch blockers such as a missing rubric or
executor. Ordinary repository work remains outside Harness unless the caller
explicitly delegates it.

## Decision 2: publish one positive blocker recipe

The shared Harness contract will define these generic encodings:

- Copy a typed pre-dispatch `reason` to `route.fallback_reason`.
- Leave resolution/provider/executor/model fields empty and keep both dispatch
  attempt collections at zero when no dispatch occurred.
- Identify a checked absolute path as `path:<absolute-path>` in
  `evidence.fixed_target`.
- Begin each evidence entry with the exact decisive result; append the command
  or procedure afterward only when useful.
- Begin each blocker with `<reason>:` and follow it with the concrete recovery
  condition or setup action.

This is a reusable result contract, not a `missing-rubric` answer. The stub still
owns the actual path, reason, evidence text, and remediation returned to the
agent.

## Decision 3: conditional reference routing

Replace the unconditional six-reference read with explicit path predicates:

- Read `harness-contract.md` when validating a request or constructing any
  terminal result.
- Read `routing.md` only after preflight succeeds and route selection is needed.
- Read `handoff.md` only before delegated dispatch.
- Read `verification.md` only when an artifact or review claim must be accepted.
- Read `context.md` only when context mode must be selected.
- Read `shelby-integration.md` only when callable Shelby or an enabled memory
  request is present.

The existing reference files remain authoritative. This repair changes their
loading boundary, not their unrelated contents.

## Decision 4: immutable cross-repository release

Create an isolated Skills-n-Stuff worktree from `origin/main`; do not reuse the
shared checkout, which currently contains the separate
`fix/narrow-harness-delegation` branch and an untracked `.DS_Store`.

Release the production repair as Harness `0.8.2`, including the marketplace and
plugin manifests. Commit and push that branch before Harness Testing pins its
exact commit.

Then update Harness Testing's version ledger and every test fixture that models
the pinned Harness version or commit. Let existing validation identify derived
digests; do not hand-wave or reuse stale arm/manifest identities.

## Decision 5: surgical verification and canary

The failed 0.8.1 run is the behavioral RED fixture:

- Claude A2 did not invoke `harness:execute`.
- Codex A2 loaded every reference and returned the wrong terminal encoding.

Verification proceeds in this order:

1. Run only the Skills-n-Stuff tests selected by the changed skill, contract,
   and release manifests; run the repository checkpoint once before its commit.
2. In Harness Testing, run affected static/unit/materialization checks and one
   checkpoint after all pin changes settle.
3. Compile an A2-only, two-session subscription manifest for
   `missing-rubric`: Claude Sonnet 4.6 high and Codex GPT-5.6 Terra high.
4. Obtain content-addressed approval before starting either session.
5. Require correctness, workflow, and efficiency `1.0` in both cells.
6. Inspect trajectories to prove Claude invoked the skill and neither provider
   loaded unrelated references. Compare tokens, cached tokens, wall time, and
   API-equivalent cost with the preserved 0.8.1 A2 cells.

If either provider fails, stop at the two-session canary and diagnose it. Do not
expand to more tasks or a full release run.

## Completion criteria

- Harness `0.8.2` is committed from an isolated Skills-n-Stuff worktree.
- Harness Testing pins the exact 0.8.2 commit and has no stale 0.8.1 fixture.
- Both repositories pass their single final checkpoint with clean tracked
  status.
- The approved A2-only canary passes all three score dimensions for both
  providers.
- Startup receipts show only Studio Harness, Claude invokes `harness:execute`,
  and no trajectory reads all six references.
- No raw trajectory, credential, provider home, or ignored run artifact is
  committed or published.
