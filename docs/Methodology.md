# Methodology

## Measurement question

With the provider, model, effort, task, environment and attempt policy held fixed, does a harness make the agent more correct, cheaper, faster, or less annoying? The benchmark is comparative, not a universal leaderboard: results are meaningful only for the fixed task suite and kickoff they were measured on.

## Frozen inputs

Every workflow task contains a frozen starting project, a neutral comparison instruction, a scripted user with authored facts, an oracle solution, a protected-file manifest, a deterministic verifier and five model-free QA cases (oracle, no-op, near miss, adversarial, source tamper). Dependencies, toolchains, container images, upstream repositories, provider agents and models are pinned in `Versions.toml`.

Tasks use no live product repositories or private data. Workflow projects begin as clean Git worktrees with a deterministic baseline commit; the environment and the separate verifier have no network. `/app` and the agent trajectory are retained as local artifacts for verification. The research lane uses five pinned DeepSWE tasks materialized into ignored local storage; the upstream tree has no license file, so nothing fetched is redistributed.

Each contender is an immutable, content-addressed bundle: source commits, plugin and skill inventory, injected startup instructions, rubric bytes and delivery configuration. Changing any of those creates a new harness version. Claude receives plugin directories through `--plugin-dir`; Codex receives its native marketplace layout, where plugins are skills-only.

## Runs

A request names the contenders, the kickoff provider, runtime, model and effort, the callable child inventory, exact task IDs, attempts, timeouts, resources, billing route and limits. Planning computes task, image, scripted-user and adapter digests, and a manifest digest that must be approved verbatim before execution. The first task runs across every cell as a delivery canary; an infrastructure failure stops the run, a correctness zero does not.

A bounded simulated user answers clarifications from the authored task facts and grants only routine local approvals. It cannot reveal hidden tests, supply solutions or widen authority; an unanswerable question is a task-definition gap, not a harness failure.

The whole agent tree is measured: root, subsequent turns and children, with model, effort, token categories and API-equivalent cost under one frozen pricing snapshot. Wall time runs from kickoff to the final deliverable. Missing telemetry is unavailable, never zero.

## Verdict

Correctness is decided by the protected verifier and protected state, per task. A contender is eligible when its coverage is complete, it matches the best correctness observed in the cohort, and its final-patch review completed with no confirmed remaining defects. A task that no contender solved is listed and cannot separate them.

Among eligible contenders, cost and time are compared as ratios of per-task means. A contender is recommended when it is clearly better on cost or time (ratio at or below the policy's advantage threshold) and not worse on the other (at or below the noninferiority threshold) against every other eligible contender. Otherwise the leaders are shown and the verdict is no clear winner. Confirmed defects disqualify; unconfirmed reviewer claims are listed as warnings.

One attempt per task on a declared scope is decision evidence. Repetitions are optional and only narrow the variation; one flaky trial can change the verdict, and the limitations say so. A `diagnostic` purpose label never blocks a verdict; scope coverage does.

A campaign binds the controlled and research lanes. Recovery and correction reports are stitched into the original lane in execution order: a later report may replace a slot only when the earlier trial did not complete or the task digest changed, a corrected task must be rerun for every contender, and superseded trials are listed.

Version history compares a Studio Moser version with its explicit predecessor on the same conditions: improved, regressed, mixed, no clear change, or insufficient evidence.

## Behavior and quality

Every completed trial retains the normalized user-visible root conversation. Deterministic metrics count words, messages, slop phrases, repeated sentences, prompt restatement, unnecessary questions and approvals, useful progress updates, formatting density and contract violations against the task's communication contract. Blinded automated graders score six work-quality dimensions from 1 to 5. Both are descriptive evidence beside the verdict, shown per kickoff model and harness version; they never decide the ranking, and there is no human preference lane.

## Infrastructure classification

Each trial carries one state: passed, agent-task failure, verifier failure, task-definition failure, provider failure, authentication failure, rate-limited, timeout, sandbox failure, or unknown. Only agent-task failures count as coding failures. A run that stops on an infrastructure failure is marked failed with its unstarted slots pending; a recovery run fills them and the campaign summary stitches the lane back together.

## Evidence

Reports are content-addressed and immutable. Corrections add a new revision or a recovery run; nothing rewrites retained evidence. Reports contain only allowlisted status, scores, usage and the normalized root conversation. Raw jobs, provider homes, prompts, reasoning, tool output, session IDs and host paths stay local and never enter tracked files or the dashboard.
