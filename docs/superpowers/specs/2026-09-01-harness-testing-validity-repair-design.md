# Harness Testing Validity Repair Design

**Status:** Approved
**Date:** 2026-09-01
**Scope:** Repair benchmark contract validity, Claude plugin delivery, and release fail-fast behavior before interpreting Harness quality results.

## Context

Harness Testing is intended to compare stock provider behavior with Superpowers,
Studio Harness, and their interaction while holding the model, effort, task, and
environment fixed. The first model-backed cohorts exposed benchmark defects
before they produced decision-quality Harness evidence.

The invalid contract cohort consumed more than 53 million recorded input tokens
and 199 agent-minutes while returning no usable correctness comparison. Two
independent failures caused that result:

1. Contract tasks asked every arm to emit a complete `HarnessResult`, but the
   exact result shape was visible only in protected expectations or the Studio
   Harness layer. A0 therefore had to guess a hidden serialization.
2. Claude A2 bundles were materialized as plugin seeds and selected through
   `CLAUDE_CODE_PLUGIN_SEED_DIR`, but Harbor 0.22.0's pinned Claude adapter does
   not forward that arbitrary environment variable into the provider launch.
   Recorded Claude startup events consequently reported `plugins: []`.

The Codex plugin path loaded Studio Harness, but its agents still produced
semantically plausible results with incompatible empty values, evidence shapes,
or artifact lists because the task contract was not exact. These are benchmark
validity failures, not evidence that either provider or Harness is poor.

This design amends the initial Harness Testing design wherever its Claude
plugin-seed assumption conflicts with the pinned Harbor adapter and current
provider tooling.

## Evidence and integration constraints

- Harbor 0.22.0 owns task execution, sandboxing, provider lifecycle, artifacts,
  and ATIF conversion. Harness Testing will not introduce another runner.
- `harbor.agents.installed.claude_code.ClaudeCode.run` fixes
  `CLAUDE_CONFIG_DIR` to Harbor's agent-session directory and explicitly copies
  configured `skills`, but it does not pass the benchmark's plugin-seed
  environment variable to the Claude process.
- Harbor's generic skills surface copies skill directories. That is insufficient
  for Studio Harness because its skills refer to sibling `references/` and
  `scripts/` paths outside each skill directory.
- Claude Code 2.1.236 exposes repeatable `--plugin-dir <path>` session-local
  plugin loading and `claude plugin validate --strict <path>`. This preserves a
  complete plugin directory, including hooks, references, and scripts, without
  installing it into a mutable provider home. See the
  [Claude plugin documentation](https://code.claude.com/docs/en/plugins).
- Codex 0.150.1 already supports the pinned marketplace/plugin materialization
  used by the current Codex arms.
- Harbor's native skills facility remains appropriate for self-contained skill
  bundles, but it is not a substitute for hook-capable or companion-bearing
  plugins. See [Harbor skills](https://www.harborframework.com/docs/run-jobs/skills).

## Goals

1. Make every scored contract requirement discoverable by every arm without
   exposing protected answers.
2. Preserve strict `HarnessResult` conformance as part of contract correctness.
3. Deliver complete Claude plugins through a documented provider boundary.
4. Preserve the real provider distinction: Claude Superpowers is hook-capable;
   Codex Superpowers is skills-only.
5. Detect missing, contaminated, or incorrectly loaded arms before a large run
   consumes the remaining sessions.
6. Produce concise failure diagnostics that distinguish task outcome, result
   schema, result semantics, protected state, workflow, and infrastructure.
7. Split repaired evidence from every prior incompatible cohort.
8. Keep implementation verification surgical until one final checkpoint.

## Non-goals

- Changing Studio Harness behavior based on the invalid cohorts.
- Declaring whether Studio Harness or Superpowers improves development quality.
- Replacing Harbor, RewardKit, Claude Code, or Codex plugin systems.
- Implementing Shelby's future Harbor adapter.
- Adding live repositories, mutable external services, private memory, or
  provider homes to benchmark tasks.
- Publishing raw trajectories, prompts, reasoning, tool output, credentials, or
  provider configuration.
- Building a general plugin manager inside Harness Testing.

## Decision 1: strict, public HarnessResult contract

Add one canonical package resource:

```text
src/harness_testing/Harness_Result.schema.json
```

It is a Draft 2020-12 JSON Schema with exact top-level and nested keys,
`additionalProperties: false`, enum constraints, array item constraints, and
status/evidence conditions. Unavailable scalar values use JSON `null`; an empty
string is not an unavailable value. Empty collections remain valid where the
contract permits no attempts, artifacts, checkpoints, or blockers.

The schema covers:

```text
status
route.requested
route.actual_model
route.effort
route.provider
route.executor
route.resolution
route.attempted
route.fallback_reason
artifacts.files
artifacts.report
evidence.fixed_target
evidence.checks
evidence.outcome
telemetry.attempts
telemetry.elapsed
telemetry.verification_failures
telemetry.token_or_quota_usage
shelby.project_id
shelby.run_id
shelby.checkpoint_ids
blockers
```

Accepted results require `evidence.outcome: proven` and no blockers. Blocked
results require `evidence.outcome: unproven` and at least one typed blocker.

`harness-stub describe` will return both the task-specific action contract and
this complete result schema:

```json
{
  "actions": [],
  "harness_result_schema": {}
}
```

The schema exposes structure, types, nullability, and universal invariants. It
does not expose protected action payloads, expected artifact contents,
task-specific evidence, routes returned by the stub, or oracle answers. Those
values remain derivable from public fixture inputs, task instructions, and
successful stub responses.

The deterministic scorer will load the same package resource. The existing
hand-written complete-shape check will be replaced by JSON Schema validation so
the served contract and the enforced contract cannot drift.

Correctness remains all-or-nothing for contract tasks: the task outcome,
protected inputs, declared artifacts, and semantically conforming result are all
required. We will not move result conformance into workflow or award a passing
correctness score for an invalid Harness result envelope.

## Decision 2: actionable verifier diagnostics

`Contract_Criteria` will expose a diagnostic function that returns stable,
bounded error codes and paths. The boolean RewardKit criterion remains the
public score, while local verifier output identifies the first relevant failures
in these groups:

1. `result-json` — missing or malformed `Harness_Result.json`.
2. `result-schema` — exact JSON Schema violations.
3. `protected-state` — modified source or protected inputs.
4. `result-semantics` — wrong status, route, attempts, artifacts, evidence,
   telemetry, Shelby state, or blocker codes.
5. `artifact` — missing or incorrect declared output.

Diagnostics run only after the agent phase and never become an oracle available
to the model. They remain in raw local verifier artifacts and are not added to
the public dashboard schema.

## Decision 3: direct Claude plugin delivery

Claude materialization will stop building plugin caches, marketplace registries,
enabled-plugin settings, and `CLAUDE_CODE_PLUGIN_SEED_DIR` state. Instead, each
selected pinned plugin is copied intact into the immutable arm bundle:

```text
claude/plugins/superpowers/
claude/plugins/harness/
```

Before the bundle is sealed, the pinned Claude CLI runs
`claude plugin validate --strict` against each copied plugin in the isolated,
network-disabled materialization container. Validation starts no model session.

Add `harness_testing.Claude_Agent:HarnessClaude`, a narrow subclass of Harbor's
pinned `ClaudeCode` adapter. It will:

- accept zero to two `plugin_dirs` supplied only by generated benchmark jobs;
- require unique absolute paths below `/harness-arm/claude/plugins/`;
- shell-quote each path and append one official `--plugin-dir` flag per plugin;
- otherwise delegate installation, authentication, model selection, execution,
  timeout behavior, logging, and ATIF conversion unchanged to Harbor.

It will not implement plugin discovery, installation, settings, hooks, task
execution, or retries. The adapter exists only because Harbor 0.22.0 does not
expose Claude's documented repeatable flag.

Generated Claude jobs use the adapter import path and immutable mounted paths:

| Arm | Claude plugin directories |
| --- | --- |
| A0 | none |
| A1 | `superpowers` |
| A2 | `harness` |
| A3 | `superpowers`, then `harness` |

The A3 ordering remains part of provenance. Studio Harness keeps its full
references and scripts. Superpowers keeps its session-start hook.

Codex retains the current native marketplace/plugin materialization. Codex A1
and A3 remain explicitly `skills-only` when the pinned Codex manifest exposes no
hooks.

Arm provenance surface names become:

- `claude-plugin-dir`
- `codex-plugin`

Each surface records the layer, ordered path, and observed capabilities. A
claimed hook capability requires a hooks directory or manifest declaration in
the exact pinned plugin tree.

## Decision 4: delivery and contamination gates

Static validation will prove that generated job configuration and materialized
provenance agree:

- the bundle digest and source commits match;
- Claude plugin paths exist inside the read-only arm mount;
- Claude jobs contain no plugin-seed environment variable;
- the Claude adapter receives exactly the ordered plugin paths declared by the
  arm;
- Codex config, marketplace, cache, and native plugin inventory agree;
- A0 contains none of the benchmark layers;
- A1, A2, and A3 contain exactly their declared layers;
- both custom adapter source digests are included in the approved run manifest.

Model-backed execution remains task-major and paired. The first selected task is
also the delivery canary shard. Execution runs that task once for every selected
cell, then checks local provider startup evidence before continuing:

- Claude's `system/init` stream event must list exactly the expected benchmark
  plugin names and expected skill names for the arm. A0 must list neither
  Superpowers nor Studio Harness.
- The existing Codex adapter records a model-free native plugin inventory before
  dispatch. The inventory must match the arm provenance and mounted provider
  home.
- Harbor must report a completed, non-infrastructure-error trial with readable
  agent and verifier artifacts. A task correctness score of zero is not itself
  an infrastructure failure and does not stop the run.

Any delivery, contamination, authentication, sandbox, provider, or verifier
infrastructure failure stops execution before the second task. The original
manifest approval already authorizes the canary and remaining sessions, so the
gate adds no approval round trip and no duplicate model session.

The same delivery assertion is retained for later jobs as cheap post-run
evidence, but the first shard is the point that prevents large invalid runs.

## Decision 5: compatibility and quarantine

This repair changes the model-visible task contract, scorer, Claude adapter,
arm materializer, and verifier image. It therefore starts a new compatibility
series.

- Increment the arm materializer schema.
- Increment the repository/methodology schema used by generated images and run
  manifests.
- Let task, scorer, image, adapter, and methodology digests flow into the normal
  compatibility key.
- Do not create a reviewed compatibility mapping to the invalid series.
- Keep every previous contract cohort and every Claude plugin-seed cohort local,
  partial, and quarantined.
- Do not regrade old contract trajectories against the newly public schema: the
  original agents did not have that model-visible input.

Prior workflow data may remain exploratory local evidence, but it is not release
evidence for the repaired series.

## Decision 6: execution and testing sequence

Implementation follows the repository's surgical-testing policy:

1. Add or change one focused test before each behavior change.
2. Run only the affected unit module while editing.
3. For contract changes, run one representative task's `oracle` and `nop` cases.
4. For arm changes, materialize one Claude A2 fixture and compile one generated
   job without starting a model.
5. At the implementation checkpoint, run static validation, the complete Python
   unit suite, and each all-case task pack once.
6. Run dashboard tests only if public result or dashboard code changes. This
   design does not require a dashboard schema change.
7. After deterministic review passes, run one paired A0/A2 contract smoke on
   Codex and one on Claude: four model sessions total.
8. Inspect delivery evidence, result diagnostics, trajectories, and task output
   before planning any larger release cohort.

No full model-backed release is part of the implementation itself. It requires a
new content-addressed manifest and its normal explicit approval after the smoke
is reviewed.

## Expected code boundaries

The implementation is expected to touch these existing seams:

```text
src/harness_testing/Claude_Agent.py                 # narrow Harbor flag adapter
src/harness_testing/Contract_Criteria.py            # shared schema + diagnostics
src/harness_testing/Contract_Stub_Server.py         # public schema delivery
src/harness_testing/Harness_Result.schema.json      # canonical result contract
src/harness_testing/Materialize.py                  # direct Claude plugin bundles
src/harness_testing/Runs.py                         # jobs, provenance, fail-fast gate
src/harness_testing/Codex_Agent.py                  # model-free plugin inventory receipt
images/Verifier.Dockerfile                          # include canonical schema resource
tests/unit/                                         # focused deterministic coverage
docs/Methodology.md                                 # corrected delivery and compatibility
docs/Runbook.md                                     # canary and smoke procedure
docs/Task_Authoring.md                              # public contract requirement
README.md                                           # accurate provider surfaces
Versions.toml                                       # repaired compatibility series
```

The implementation plan may narrow this list after tracing the exact interfaces.
It must not expand into production Harness changes, dashboard redesign, or a
general provider abstraction.

## Acceptance criteria

The repair is ready for its four-session smoke only when all of the following are
true:

1. A0 and A2 receive the identical public action and HarnessResult contracts.
2. Protected expected payloads and artifacts remain inaccessible to the agent.
3. The scorer and stub load the same canonical result schema bytes.
4. A semantically correct nullable result passes; empty-string substitutes and
   unknown fields fail with bounded diagnostics.
5. Claude A2 startup evidence lists Studio Harness and its expected skills.
6. Claude A1/A3 startup evidence lists Superpowers and proves hook-capable local
   plugin delivery.
7. Codex arms retain their declared native plugins and skills-only capability
   labels.
8. A0 startup evidence proves neither benchmark layer leaked into the baseline.
9. A forced delivery mismatch stops an approved multi-task run after the first
   shard.
10. A genuine task correctness failure does not masquerade as infrastructure
    failure or stop the remainder of an otherwise valid run.
11. Old incompatible cohorts cannot be finalized into the repaired series.
12. The final deterministic checkpoint runs once, not between implementation
    tasks.
