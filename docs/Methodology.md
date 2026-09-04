# Methodology

## Measurement question

Harness Testing asks one bounded question: with the provider, model, effort, task, environment, and attempt policy held fixed, does a harness arm improve correct coding behavior without adding avoidable workflow, testing, time, or token churn?

The benchmark is comparative, not a universal model leaderboard. Results remain meaningful only within a compatibility series.

## Frozen inputs

Every tracked workflow or contract task contains a frozen starting project, instruction, oracle, protected-file manifest, deterministic verifier, and five QA cases. Dependencies, toolchains, container images, upstream repositories, provider agents, models, and actions are pinned in `Versions.toml`.

The repository schema versions manifests and public methodology. The separate
image version keeps unchanged local runtime images pinned when only reporting or
run-control semantics advance.

Tasks use no live product repositories or private project data. Workflow projects begin as clean Git worktrees with deterministic baseline commits; arm-injected instruction files, dependencies, and build output remain outside that baseline. The environment and separate verifier have no network. The agent receives only the provider hosts required by the selected billing route. `/app` and `/logs/agent/trajectory.json` are retained as local Harbor artifacts for verification and regrading, while `.git` remains excluded.

The research profile uses a separately materialized six-task DeepSWE cohort. The pinned upstream tree has no license file, so the fetched tasks and derived images remain in ignored local storage and are never redistributed. See [Capability Pack](Capability_Pack.md).

## Arms and provider surfaces

| Arm | Ordered layers |
| --- | --- |
| A0 | None |
| A1 | Superpowers |
| A2 | Studio Harness |
| A3 | Superpowers, then Studio Harness |

Each arm is materialized into an immutable, read-only bundle with source commits, delivery surfaces, and a byte digest. Claude receives immutable plugin directories through repeatable `--plugin-dir` flags; model-free materialization runs `claude plugin validate --strict` and creates no plugin seed. Codex retains native marketplace and plugin materialization and records a plugin inventory before dispatch. Codex Superpowers is skills-only. Reports preserve that distinction rather than implying equivalent runtime hooks.

## Run profiles

| Profile | Packs | Attempts | Timeout | Maximum sessions | Intended use |
| --- | --- | ---: | ---: | ---: | --- |
| smoke | workflow | 1 | 900 s | 8 | One sentinel or narrow integration check |
| checkpoint | contract, workflow | 1 | 1,200 s | 64 | A bounded development checkpoint |
| release | contract, workflow | 1 | 1,800 s | 128 | Fresh paired release evidence |
| calibration | contract, workflow | 3 | 1,800 s | 512 | A0–A3 variance and interaction calibration |
| research | local DeepSWE cache | 1 | 3,600 s | 24 | Manual capability evidence only |

Every manifest names explicit cells and tasks. No matrix is implicit. Baseline and candidate cells force concurrency one and are ordered deterministically by provider, role, and arm so paired evidence is not mixed by parallel quota or load effects. Release evidence uses a fresh baseline in the same evaluation window as its candidate.

The dry run records the session count, order, timeouts, task/image/arm/adapter digests, estimated API-equivalent usage, billing route, and approval digest. It starts no model. Execution revalidates every digest and accepts only the exact approval string. The first selected task runs across every selected cell as the delivery canary. A correctness score of zero continues execution; an infrastructure or delivery failure stops before the next task.

Skill capability runs add the provider-native explicit invocation marker and
retain the original task as its arguments. Skill discovery runs retain the raw
task, require at least five attempts, and report the observed invocation rate
without a release threshold. Ordinary runs declare no skill evaluation.

## Score dimensions

### Correctness

Deterministic behavior tests and protected state decide correctness. A plausible response or edited output cannot pass without the required behavior and, for contract tasks, protected sidecar evidence of the expected calls.

### Workflow

Workflow criteria evaluate task-specific sequence requirements, such as grouping several requested edits before a final gate. The score does not reward verbosity, plans, or tool use by themselves.

### Efficiency policy

ATIF commands are normalized and classified as direct checks, targeted tests, package tests, comprehensive tests, lint, typecheck, build, browser, or format. Named package scripts such as `npm run test:saved-view` are targeted tests, while `test:all` and `gate` remain comprehensive. The verification envelope decides whether a final comprehensive gate is required and flags comprehensive suites run before the final mutation. Duplicate successful commands and unnecessary lifecycle events remain visible.

Efficiency never overrides correctness. Reports show the three dimensions separately and expose nullable counters for agent/verifier time, input/output/cache tokens, cost, turns, tool calls, commands, check/test classes, test time, premature suites, duplicate commands, plans, reviews, subagents, worktrees, context events, changed/generated files, diff lines, retries, timeouts, and infrastructure errors. Missing telemetry is **unavailable**, never zero.

## Infrastructure classification

A reviewed result assigns one explicit state: `passed`, `agent-task-failure`, `verifier-failure`, `task-definition-failure`, `provider-failure`, `authentication-failure`, `rate-limited`, `timeout`, `sandbox-failure`, or `unknown`.

Provider, authentication, rate-limit, timeout, sandbox, verifier-infrastructure, and task-definition failures are not counted as coding-task failures. Partial runs stay local. Reviewers retain the raw local job when a classification is uncertain.

## QA and human review

Task authors prove five deterministic cases: oracle, no-op, near miss, adversarial, and source tamper. During implementation, a changed task runs only schema/static checks plus oracle and no-op. Full deterministic gates run once at the checkpoint, not after each file edit.

For model-backed release evidence, a human samples passes, failures, unusually efficient trials, and outliers in Harbor’s local viewer. Review checks the instruction, workspace diff, verifier evidence, command classification, and infrastructure state. Raw prompts, reasoning, tool output, trajectories, credentials, and host paths remain local.

An unfair, ambiguous, contaminated, or broken task is quarantined before finalization. Quarantined and partial results cannot be published.

## Regrading and compatibility

A verifier or scorer repair does not authorize another model session. If the source job retained `/app` and `/logs/agent/trajectory.json`, run Harbor’s verifier-only regrade through `harness-test regrade`. The wrapper records the immutable source-job digest and new job identity; it never overwrites the source.

The trend compatibility key binds the task digest, dataset composition, scorer, classifier, environment image, provider-agent major contract, methodology schema, and skill-evaluation mode/name. Schema `0.3.0` separates ordinary runs, explicit capability, and automatic discovery; the observed discovery outcome does not split its own series. The earlier repaired model-visible contract began at schema `0.2.0` without a reviewed mapping to the invalid series. Old hidden-contract and plugin-seed cohorts remain local, partial, and quarantined because their agents did not receive the repaired public contract.

## Publication boundary

Public results are constructed from an allowlist and validated against `policy/Public_Result.schema.json`; raw Harbor objects are never recursively copied and filtered. `finalized=true` requires task review, infrastructure review, complete coverage, and no quarantine. Publication under `results/` additionally requires the result methodology and content-valid generated run manifest to use the current repository schema, with no reviewed compatibility mapping. The content-derived result identity makes later mutation visible.

Only schema-valid JSON under `results/` reaches the static dashboard. Skill results expose only mode, canonical name, and invocation classification; raw prompts and trajectories stay local. The loader fails closed on unknown fields and reads no `jobs/` path. The dashboard offers no analytics SDK, API server, database, prompt view, or trajectory view.
