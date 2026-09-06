# Agent Experiment Guide

Use this contract to turn a harness change into a reviewable, reproducible comparison. The dashboard is read-only; the agent prepares and executes runs through the CLI. Read [Experiment Request.schema.json](../policy/Experiment%20Request.schema.json) for the strict field contract and [Runbook](Runbook.md) for credentials, exact-manifest approval, quarantine and publication.

## A1 — Choose the experiment

Check [Next Queued Experiment](Capability_Pack.md#next-queued-experiment) before choosing a run. Prefer a small representative pilot before repeating a broad cohort. The current nine-task, three-repetition recommendation policy does not require starting with 81 trials. A diagnostic subset can expose failures and measure exploratory overhead without supporting an overall winner.

[Baseline Comparison.json](../runs/examples/Baseline%20Comparison.json) is the full-cohort template for first baselines or a new kickoff model. It schedules Nothing, Superpowers and the full Skills-n-Stuff collection plus its pinned Superpowers dependency: nine neutral development tasks, three repetitions each, 81 root task trials. The startup model is `gpt-6-astra`, effort `high`; native child routing stays available. Adapt a private copy for a smaller diagnostic rather than executing the full template by default. The current request compiler accepts only local workflow comparison tasks; the queued DeepSWE pilot needs the integration described in the queue before it can use this contract.

Use [Candidate Comparison.json](../runs/examples/Candidate%20Comparison.json) for later Studio Moser edits: 27 root trials, with the two baselines reused. Replace both zero-filled reference IDs with exact retained `report_id` values. They may point to the same first-cohort report. Never select “latest” or silently substitute a different baseline.

The examples are preparation templates, not approved runs. Copy the reviewed personal rubric into ignored `runs/inputs/Model Rubric.yml` before planning. Do not commit personal configuration. Update contender labels, exact source commits and rubric path; write the change summary and hypothesis before seeing results. Set `first_version: true` only without a predecessor. An unchanged version needs `change.rerun_reason`.

## A2 — Freeze the inputs

Required inputs are the purpose/label; contender family and display label; every source's kind, location and full 40-character commit; rubric mode and local snapshot path; additional startup files; kickoff provider/runtime/model/effort; actually callable child model/effort inventory; task IDs/variant; repetitions, concurrency, timeout, resources and retry policy; exact baseline/predecessor IDs; hypothesis; billing/session/interaction limits; and publication mode.

A `collection` includes every marketplace plugin and checks that every `SKILL.md` is accounted for. A `plugin` is one dependency. Studio Moser currently includes the entire Skills-n-Stuff collection and the separately pinned Superpowers plugin. Future versions may remove/replace that dependency or disable the rubric; change the declared inputs and label accordingly. Nothing has no extra harness inputs.

Contender identity hashes effective source contents, skill inventory, rubric, startup instructions and delivery configuration. Labels do not create new versions. Planning retains a file-hash diff against the explicit predecessor, including added/removed files, in `Verified Changes.json`. Keep the exact predecessor bundle so this diff can be verified.

The planner computes task, evaluator, actual built-image, scripted-user, authority and adapter digests. Image identity includes platform and installed contents; execution rechecks it after approval. Build recipes are retained separately. Reused reports must match all comparison conditions, including kickoff, executor inventory, tasks, grading, repetition count and resources. A new model/runtime or incompatible test change requires fresh baselines. A diagnostic subset can prove transport or delivery, but cannot support a primary recommendation.

## A3 — Preserve normal routing

The kickoff selects the orchestrator only. Do not rewrite every child model to match it. Deliver the frozen rubric through `XDG_CONFIG_HOME`; list callable executors, not every model mentioned in the rubric. For a Codex kickoff, the native runtime supplies OpenAI children. Non-native Claude rows without an available adapter are skipped by Harness's normal fallback rules. For a Claude kickoff, its native children and the existing external Codex route require their approved credentials and linked telemetry.

A model alias in a config is not proof of availability. Native preflight checks the pinned CLI and its model/effort catalog; unavailable executors fail with a typed reason. Never repair availability by silently changing models, effort, credentials or baseline IDs.

Each task has frozen facts and bounded scripted replies for recognized clarification and routine local approval gates. Unknown questions become `task_definition_gap`; they are not invented answers or harness successes. The scripted user cannot grant publication, spending or broader task authority. Fix a defective task policy, version the evaluation conditions and refresh baselines when needed.

## A4 — Plan, inspect, approve, execute

```bash
uv run harness-test run plan --request 'runs/inputs/Experiment Request.json'
```

Planning performs native plugin installation/validation without sending a model prompt. Inspect the generated `Manifest.json`, its digest, selected contenders, reference IDs, session count, timeouts, pricing estimate, publication destination and verified changes. Retain the input request beside your private experiment records.

Run a small `purpose: diagnostic` canary first for a new runtime/delivery path. It still requires its own exact manifest approval. Confirm a real clarification round trip, root continuity, child routing, usage completeness and cancellation before spending on the cohort.

Only after the user approves that exact manifest:

```bash
uv run harness-test run execute --manifest 'runs/generated/DIGEST/Manifest.json' --approve 'sha256:DIGEST'
```

`max_sessions` limits scheduled root task trials, not a promised bound on native child calls. Timeout covers agent work and child waiting. API budget is an admission estimate; providers do not guarantee a whole-tree dollar stop. A request requiring `budget_enforcement: hard-stop` is rejected. Subscription mode uses zero incremental dollar budget while retaining API-equivalent estimates.

Zero incremental dollars does not mean free compute: subscription runs consume quota and wall time. The current comparison planner uses the calibration profile's generic allowance of 1,000,000 input and 100,000 output tokens per root trial from `runs/Profiles.toml`. This is not a forecast learned from previous runs. Present observed pilot usage separately, explain task-size uncertainty, and do not describe the admission estimate as a charge or a guaranteed ceiling.

Comparison `retry_policy` is `none`: Harbor's automatic transport retry deletes the failed attempt directory. Preserve that attempt and prepare a separately identified rerun instead. Internal model repairs remain part of the trial's recorded work.

## A5 — Inspect evidence and iterate

Use the dashboard's conclusion, three-harness table, version history and task evidence. A winner must clear every required task's protected correctness checks; failures cannot be offset by cheap execution. Cost includes recorded failed attempts, turns and children. Missing grading, infrastructure errors, incomplete usage, incompatible conditions, quarantined evidence and insufficient repetitions remain explicit.

For these comparisons, read the version-3 experiment trial/comparison evidence and the report's observed whole-tree cost. Legacy per-job `efficiency` summaries can describe a narrower scope and must not replace the native root-plus-children ledger.

[Comparison Pricing](Comparison%20Pricing.md) defines standardized token estimates. Original estimates are retained; new comparisons reprice retained token evidence using one shared snapshot. Unreported child effort and missing token counts stay unavailable. Raw prompts, reasoning, traces, session IDs, credentials and local paths never enter public reports.

Version-3 reports are content-addressed. Corrected evidence retains earlier revisions; reference IDs never move to a newer result. Keep `arms/materialized`, `runs/generated`, and `runs/evidence` for local reproducibility. Publication remains bound to the existing approved destination and privacy checks. Pending sync includes retained revisions only when their original manifest authorizes that destination; local-only evidence cannot acquire publication approval through a later revision.

Improved/regressed/mixed/no-clear-change describe the selected fixed test suite. They do not establish universal reliability or isolate the rubric causally. To test the rubric itself, make a version whose only deliberate change is the rubric and compare it with its explicit predecessor under matching conditions.
