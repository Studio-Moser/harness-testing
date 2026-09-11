# Agent Experiment Guide

Use this contract to turn a harness change into a reviewable, reproducible comparison. The dashboard is read-only; the agent prepares and executes runs through the CLI. Read [Experiment Request.schema.json](../policy/Experiment%20Request.schema.json) for the strict field contract and [Runbook](Runbook.md) for credentials, exact-manifest approval, quarantine and publication.

## A1 — Choose the experiment

Check [Next Queued Experiment](Capability_Pack.md#next-queued-experiment) before choosing a run. Prefer a small representative pilot before repeating a broad cohort. The current nine-task, three-repetition recommendation policy does not require starting with 81 trials. A diagnostic subset can expose failures and measure exploratory overhead without supporting an overall winner.

[Baseline Comparison.json](../runs/examples/Baseline%20Comparison.json) is the full-cohort template for first baselines or a new kickoff model. It schedules Nothing, Superpowers and the full Skills-n-Stuff collection plus its pinned Superpowers dependency: nine neutral development tasks, three repetitions each, 81 root task trials. The startup model is `gpt-6-astra`, effort `high`; native child routing stays available. Adapt a private copy for a smaller diagnostic rather than executing the full template by default. The queued Quill pilot uses the `deepswe` diagnostic variant, which accepts only its selected cached task and does not establish an overall comparison winner.

Use [Candidate Comparison.json](../runs/examples/Candidate%20Comparison.json) for later Studio Moser edits: 27 root trials, with the two baselines reused. Replace both zero-filled reference IDs with exact retained `report_id` values. They may point to the same first-cohort report. Never select “latest” or silently substitute a different baseline.

The examples are preparation templates, not approved runs. Copy the reviewed personal rubric into ignored `runs/inputs/Model Rubric.yml` before planning. Do not commit personal configuration. Update contender labels, exact source commits and rubric path; write the change summary and hypothesis before seeing results. Set `first_version: true` only without a predecessor. An unchanged version needs `change.rerun_reason`.

## A2 — Freeze the inputs

Required inputs are the purpose/label; contender family and display label; every source's kind, location and full 40-character commit; rubric mode and local snapshot path; additional startup files; kickoff provider/runtime/model/effort; actually callable child model/effort inventory; task IDs/variant; repetitions, concurrency, timeout, provider recovery allowance, resources and retry policy; exact baseline/predecessor IDs; hypothesis; billing/session/interaction limits; and publication mode.

A `collection` includes every marketplace plugin and checks that every `SKILL.md` is accounted for. A `plugin` is one dependency. Studio Moser currently includes the entire Skills-n-Stuff collection and the separately pinned Superpowers plugin. Future versions may remove/replace that dependency or disable the rubric; change the declared inputs and label accordingly. Nothing has no extra harness inputs.

Contender identity hashes effective source contents, skill inventory, rubric, startup instructions and delivery configuration. Labels do not create new versions. Planning retains a file-hash diff against the explicit predecessor, including added/removed files, in `Verified Changes.json`. Keep the exact predecessor bundle so this diff can be verified.

The planner computes task, evaluator, actual built-image, scripted-user, authority and adapter digests. Image identity includes platform and installed contents; execution rechecks it after approval. Build recipes are retained separately. Reused reports must match all comparison conditions, including kickoff, executor inventory, tasks, grading, repetition count and resources. A new model/runtime or incompatible test change requires fresh baselines. A diagnostic subset can prove transport or delivery, but cannot support a primary recommendation.

## A3 — Preserve normal routing

The kickoff selects the orchestrator only. Do not rewrite every child model to match it. Deliver the frozen rubric through `XDG_CONFIG_HOME`; list callable executors, not every model mentioned in the rubric. For a Codex kickoff, the native runtime supplies OpenAI children. Non-native Claude rows without an available adapter are skipped by Harness's normal fallback rules. For a Claude kickoff, its native children and the existing external Codex route require their approved credentials and linked telemetry.

A model alias in a config is not proof of availability. Native preflight checks the pinned CLI and its model/effort catalog; unavailable executors fail with a typed reason. Never repair availability by silently changing models, effort, credentials or baseline IDs.

Each task has frozen facts and bounded scripted replies for recognized clarification and routine local approval gates. Unknown questions become `task_definition_gap`; they are not invented answers or harness successes. The scripted user cannot grant publication, spending or broader task authority. Fix a defective task policy, version the evaluation conditions and refresh baselines when needed.

Workflow tasks opt into the shared `local-development-approval` matcher instead of duplicating a list of approved sentence endings. It recognizes terminal requests about the local plan, design, approach, or continuation and returns only the existing frozen task-authority fact. This restates the original local scope; it does not approve additions in the proposed plan. Explicit external or broader-authority language in the approval request is denied, as are tool-permission requests. The matcher is not a semantic review of the proposed plan; authority remains limited by the frozen task. Other questions and ambiguous requests remain unanswered. Legacy `pattern` rules retain their exact-match behavior. Before another model-backed diagnostic, replay retained approval messages and check completion prose, unknown questions, external requests, interaction limits, and same-root continuation without model calls.

A finished model turn is not necessarily finished work: a final message may request plan or design approval. The runner must answer a recognized routine gate from the frozen task facts or retain an unanswered request as `task_definition_gap`, including requests without a question mark. After changing these rules or the conversation adapter, prepare a new manifest; do not resume an old approved manifest with changed inputs or rewrite its original result. Validate the approval round trip without model calls before a rerun.

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

New Codex plans freeze `conditions.provider_recovery_seconds`, defaulting to 600 seconds. Set it explicitly to zero to disable it, or an integer up to 3600. The first structured provider transport error activates this one fixed extension to the original deadline; repeated errors and child errors cannot renew it. The native runtime continues its existing session and reconnect process. Normal slow responses without a reported transport error still count toward the task timeout. The printed plan shows both the task timeout and maximum wall time; the controller, adapter and outer job reserve matching limits. Legacy manifests without this field receive no extension. This recovery policy currently supports the Codex native protocol; Claude plans default to zero and reject a positive allowance.

The task evidence records transport-error count and whether the allowance activated. Actual elapsed time includes connection waits, and all recorded root/child usage is retained. A terminal transport failure or a deadline reached after transport disruption is `infrastructure_failure`, with `provider_transport_interrupted`; it cannot establish harness quality or an efficiency winner. A recovered completed trial can still be graded normally, with its full elapsed time visible. Failed checks, authority denials and ordinary task timeouts do not become recovery opportunities. A terminal failure preserves artifacts and incomplete usage rather than restarting or silently replaying the task. Changing the allowance changes comparison conditions and requires a new manifest; old reports remain unchanged.

Zero incremental dollars does not mean free compute: subscription runs consume quota and wall time. The current comparison planner uses the calibration profile's generic allowance of 1,000,000 input and 100,000 output tokens per root trial from `runs/Profiles.toml`. This is not a forecast learned from previous runs. Present observed pilot usage separately, explain task-size uncertainty, and do not describe the admission estimate as a charge or a guaranteed ceiling.

Comparison `retry_policy` is `none`: Harbor's automatic transport retry deletes the failed attempt directory. Preserve that attempt and prepare a separately identified rerun instead. Internal model repairs remain part of the trial's recorded work.

## A5 — Inspect evidence and iterate

Use the dashboard's conclusion, three-harness table, version history and task evidence. A winner must clear every required task's protected correctness checks; failures cannot be offset by cheap execution. Cost includes recorded failed attempts, turns and children. Missing grading, infrastructure errors, incomplete usage, incompatible conditions, quarantined evidence and insufficient repetitions remain explicit.

For these comparisons, read the version-3 experiment trial/comparison evidence and the report's observed whole-tree cost. Legacy per-job `efficiency` summaries can describe a narrower scope and must not replace the native root-plus-children ledger.

[Comparison Pricing](Comparison%20Pricing.md) defines standardized token estimates. Original estimates are retained; new comparisons reprice retained token evidence using one shared snapshot. Unreported child effort and missing token counts stay unavailable. Raw prompts, reasoning, traces, session IDs, credentials and local paths never enter public reports.

Version-3 reports are content-addressed. Corrected evidence retains earlier revisions; reference IDs never move to a newer result. Keep `arms/materialized`, `runs/generated`, and `runs/evidence` for local reproducibility. Publication remains bound to the existing approved destination and privacy checks. Pending sync includes retained revisions only when their original manifest authorizes that destination; local-only evidence cannot acquire publication approval through a later revision.

Improved/regressed/mixed/no-clear-change describe the selected fixed test suite. They do not establish universal reliability or isolate the rubric causally. To test the rubric itself, make a version whose only deliberate change is the rubric and compare it with its explicit predecessor under matching conditions.

## A6 — Evaluate the finished code

Test success is not a code-review result. After a run finishes, use the [Code Review Evaluation](Code%20Review%20Evaluation.md) pipeline to prepare frozen, blinded packets from its existing final submissions. This needs no coding-task rerun. Prepare every contender under the same versioned review protocol, reviewer model/effort/runtime and time budget; dispatch one fresh session per packet without the contender harness, cost, labels or internal review transcript. Keep the private mapping with the coordinator. The code itself may reveal its origin; do not promise perfect blinding.

Require reproducible findings with severity and affected source location. A separate confirming session must check a finding on the same frozen target before it counts as confirmed. Retain the procedure, expected/actual result and hashed evidence locally. Recording validates the supplied evidence and session attestations; it does not run submitted commands or prove a reproduction happened. Do not mark a claim confirmed merely because the reviewer says it is a bug. Record blocked/incomplete reviews and unresolved claims explicitly.

Compare confirmed **remaining** defects by severity, then execution cost and time. A completed review finding no defects is not proof of defect-free code. The added `final-patch-review-v1` decision gate retains the frozen test/efficiency thresholds and is included in the comparison policy digest. It requires completed reviews under one matching protocol, no unresolved claims, and no confirmed remaining defects for an efficiency recommendation. Historical comparisons require compatible reviews on both versions. Old test-only reports remain readable and retain their original identities; their conclusions do not establish reviewed-code superiority.

Optional internal review evidence records findings caught, fixed and left unresolved during the original coding run. Without evidence those counts remain unknown, including for Nothing: no harness does not mean no testing or iteration. Internal repair counts explain process and never replace the independent final-patch result.

Evaluation cost is separate from original harness execution cost and includes review/confirmation work. Missing usage remains unknown. Record returns a new retained report revision, preserving the original test scores, costs and publication authority. A new review protocol needs new reviews of the retained baseline submissions; it does not itself require rerunning the coding agents. Preparing/recording is model-free; obtain explicit authorization for any additional benchmark review sessions using the exact prepared plan and its compute scope.

## A7 — Evaluate collaboration quality

Every workflow task has a versioned `Communication Contract.json`. The ten additional inexpensive patterns in [Communication Scenarios.json](../policy/Communication%20Scenarios.json) freeze prompts, follow-ups and expectations for repository questions, edits, ambiguity, status, corrections, disagreement, failure recovery, routine authority, consequential authority and completion. Add or change a contract before running; its digest becomes part of the trial evidence. Keep collaboration judgments separate from protected correctness and final-patch review.

For Opus 5, start from [Opus Personality Comparison.json](../runs/examples/Opus%20Personality%20Comparison.json). It fixes one model and effort across Nothing, Studio personality-only and Studio Moser Lite. Copy `House Style.md` and the model rubric into ignored `runs/inputs/`, update the exact Studio commit when needed, plan the request, and obtain approval for that exact coding-run manifest. The template schedules 27 task sessions; use a smaller diagnostic copy first when that is enough.

Completed trials already contain deterministic measures and a public-safe root transcript. Preparing blind grades starts no model:

```bash
uv run harness-test collaboration prepare \
  --report 'runs/generated/DIGEST/Run_Report.json' \
  --protocol 'policy/Collaboration Grading Protocol.json'
```

For a finalized, single-task version-3 report created before transcript capture, reuse the
coding work only when its exact Harbor job directories still retain both
`agent/trajectory.json` and `agent/Native_Requests.jsonl`. Apply one explicit current
communication contract and the original frozen task instruction:

```bash
uv run harness-test collaboration backfill \
  --report 'runs/evidence/SOURCE_REPORT.json' \
  --jobs-dir 'jobs/raw' \
  --contract 'tasks/workflow/TASK/Communication Contract.json' \
  --instruction 'PATH/TO/FROZEN/instruction.md'
```

The command verifies the report-to-job mapping and task request, records source digests in
ignored local evidence, and writes an immutable superseding report. Its comparison
limitations explicitly say that the transcript was retrospectively reconstructed and
evaluated with the current contract. It starts no model. Do not backfill when either raw
artifact is absent; leave collaboration unavailable instead.

The returned plan freezes randomized identity-blind packets and requires one fresh grader session per packet. Review that exact plan, session count, model, effort and time budget, then obtain explicit approval before starting any grader. Put the returned results in the checked schema shape and import them without another coding run:

```bash
uv run harness-test collaboration record \
  --plan 'runs/collaboration/PLAN_DIGEST/Plan.json' \
  --results 'runs/inputs/Collaboration Grades.json'
```

Calibrate the grader against Tim's preference with same-scenario A/B packets:

```bash
uv run harness-test collaboration calibration-prepare \
  --report 'runs/evidence/REPORT_DIGEST.json'
uv run harness-test collaboration calibration-record \
  --plan 'runs/calibration/PLAN_DIGEST/Plan.json' \
  --labels 'runs/inputs/Collaboration Labels.json'
```

Choose one side blindly and optionally record the concrete annoyance. Automated preference remains advisory until 15 choices are labeled. The dashboard uses Tim's calibrated preference when available; otherwise it labels a complete automated result as uncalibrated. Missing transcripts or grades remain unknown, and no collaboration result changes the engineering winner.
