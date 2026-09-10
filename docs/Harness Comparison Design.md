# Harness Comparison Design

Status: approved for implementation planning; no runner or dashboard implementation changes.

Source baseline: Harness Testing `58a470f`; Skills-n-Stuff `dd318ec6f4c1c6d4e058378e306612a509efa46f`.

## Product goal

Answer: **Which harness should I use for my development work, and why?**

Compare correctness first, then the cost and elapsed time required to obtain correct results. Explain token usage, delegation, and workflow behavior as supporting evidence. Show whether each Studio Moser revision improves on its predecessor and on reusable Nothing and Superpowers baselines.

An agent prepares and executes experiments. The dashboard is a read-only report with filters and drill-down navigation. It does not configure runs, approve budgets, launch agents, or edit harnesses.

## Agreed decisions

| Reference | Decision |
| --- | --- |
| D1 | Studio Moser means the full Skills-n-Stuff collection, including its required dependencies, rather than only `plugins/harness`. |
| D2 | A harness version freezes code, dependencies, startup instructions, and routing configuration. Rubric edits or disabling routing create new candidate versions. |
| D3 | Fix the kickoff orchestrator model and effort; allow each harness to choose its normal delegation process within the same available capabilities and resource limits. |
| D4 | Reuse compatible Nothing and Superpowers baselines across Studio Moser iterations. Establish new baselines for new kickoff configurations or incompatible evaluation conditions. |
| D5 | Document and validate all required experiment inputs before execution. |
| D6 | Every conclusion identifies its candidate, baselines, dates, measurements, and limitations. |
| D7 | Every candidate experiment records a verified change summary, intended benefit, and diff from its previous tested version. |
| D8 | Compare each candidate both with its predecessor and with the reference harnesses. |
| D9 | History explains what changed, what was expected, and what was observed; distinguish improvement, regression, mixed results, and insufficient evidence. |

Trials run unattended. A scripted benchmark user supplies predefined task clarifications and routine workflow approvals, with interactions retained as evidence. This does not expand the experiment's approved tools, destinations, spending, or execution scope.

## Contenders and versions

The initial contenders are Nothing, Superpowers, and Studio Moser. Internal A0–A3 identifiers remain interpretable for historical reports, but new comparison logic must not assume that every contender fits those four arms.

Nothing is the stock provider runtime with the common task environment and tools, without added harness skills or custom workflow instructions. It retains the runtime's native capabilities. Superpowers adds the pinned Superpowers distribution. Studio Moser adds the full pinned Skills-n-Stuff collection, its required dependencies, and a valid frozen rubric.

All contenders receive the same task resources, available executors, credentials appropriate to the approved billing route, and common authority limits. A harness decides whether and how to use them. Never force subagents merely to exercise the rubric or disable native delegation in the baseline to favor Studio Moser.

A version has a stable family, human-readable label, and content-derived identity. Its identity covers source commits, plugin/skill inventory, dependency versions, injected rules, rubric contents or explicit disabled state, and provider delivery configuration. All repository skills must be accounted for in the inventory; task relevance determines activation. An unsupported required surface is reported before an experiment can claim to test the complete configuration.

The active personal rubric is not supplied by the public repository: its bundled seed deliberately lacks working routes. Capture the approved routing configuration separately. Do not mount a developer's normal provider home, private memory, or unrelated personal configuration. Credentials remain execution-only inputs.

The kickoff model/effort is an experiment input. The selected harness may route its children normally, but must not silently replace the requested kickoff model. Log the actual runtime, model, effort, and delivery inventory.

## Existing test suite

Reuse the existing fixtures and protected behavior tests:

| Suite | Existing coverage | Role |
| --- | --- | --- |
| Development workflow | Nine tasks: React accent polish, active badge count, grouped UI updates, saved views; static pricing polish, grouped page updates, accessible disclosure; Rust quoted-value parsing and workspace warning summary | Primary harness comparison |
| Harness contracts | Eight tasks covering routing, missing capabilities, independent review, PM execution, research fan-out, and computer-use contracts | Separate Studio Moser regression evidence |
| DeepSWE capability | Six pinned TypeScript, JavaScript, and Rust tasks | Existing optional longer-running comparison lane |

The current development instructions frequently prescribe exact test commands and timing. Create a versioned comparison form of those tasks that preserves requested behavior, trust boundaries, and protected verification while allowing each harness to select its normal process. Preserve the original workflow tests as diagnostic/regression evidence. Do not silently reinterpret old scores under new task definitions.

The contract suite must not contribute to the general contender winner: reproducing Studio Moser-specific calls is not a neutral measure of another harness's development effectiveness. Keep DeepSWE optional; do not add stacks or a replacement task suite for this work.

Passing the existing tests demonstrates tested correctness, not a universal claim about maintainability or design quality. The initial verdict should use that precise language. A subjective code-quality judge would require a separate validated evaluation policy.

## Required agent-run contract

This table defines semantic requirements for the future validated request. It is not a claim that the existing CLI already accepts these fields.

| Input | Required content and validation |
| --- | --- |
| Purpose | Baseline establishment, candidate comparison, or an explicitly selected diagnostic run; human-readable experiment label |
| Contenders | Family, label, immutable source/dependency references, complete installation inventory, startup rules, rubric snapshot or explicit disabled state |
| Kickoff | Provider runtime and version, exact model identifier and effort, adapter version; callable capability preflight |
| Task selection | Existing pack and explicit task IDs; frozen prompts, fixtures, oracle/verifier, scorer, and dataset digests |
| Environment | Images/toolchains, resource allocation, common tools, available child executors/models, authority and network policy |
| Scripted user | Versioned task facts, clarification responses, routine approval rules, and interaction limit; no hidden solution access |
| Trial policy | Explicit repetitions per task, reset behavior, scheduling policy, timeout and retry rules; distinguish internal agent retries from new benchmark trials |
| Usage policy | Billing route, cost estimate and approved maximum, pricing snapshot, token accounting convention, limits covering the entire agent tree |
| Baselines | Exact Nothing and Superpowers result IDs for reuse, or an explicit baseline-establishment request; never silently substitute another cohort |
| Predecessor | Previous tested Studio Moser version and result IDs, or explicit first-version state |
| Change record | Source/configuration diffs, short verified summary, hypothesis, and intentionally varied settings; explicit rerun state when no version changed |
| Decision policy | Versioned quality eligibility, practical cost/time thresholds, uncertainty rules, and treatment of incomplete/failed trials |
| Publication | Existing approved destination/mode and allowlisted output policy |

Missing information produces an actionable list before model execution. The preparing agent resolves configuration, computes digests, identifies compatible reference evidence, and presents the concrete manifest and budget for the existing exact-digest approval. Preparing a request does not authorize its execution.

## Scripted user

A trial starts with the same ordinary task request for every contender. Explicit skill invocation is reserved for a separately labeled capability experiment; the main comparison lets the installed skills activate normally.

The scripted user answers from the frozen task facts and grants only the routine approvals covered by that task's authority. It may approve a proposed plan within scope, but cannot supply a solution, reveal hidden tests, coach a failing agent, authorize extra expenditure, or change success criteria.

Record each question, applied response rule, reply, and interaction count locally. Publish only safe structured counts and classifications. Repeated approval requests contribute to measured work. A required clarification absent from the response policy is a task-definition issue, not an invented answer or an automatic coding failure. Bound repeated interactions using the declared limit.

## Baseline reuse and compatibility

Separate the **evaluation conditions** from the **contender version**. The comparison key binds the kickoff runtime/model/effort, adapter behavior, task selection and digests, evaluator, environment/resources, available capabilities, scripted-user policy, trial policy, and scoring/accounting conventions. Harness instructions, dependencies, and rubric are the intentional variables and belong to the contender identity.

Changing Studio Moser's child-model selection does not invalidate an otherwise compatible baseline. Changing the common available model pool, task semantics, kickoff effort, or runtime does require a compatibility check. Versioned hashes must reflect semantic runtime inputs rather than unrelated documentation edits.

Baseline reuse is explicit and pinned. Do not rerun Nothing or Superpowers for every candidate edit, and do not silently advance their source versions. When a baseline is missing or incompatible, planning names the mismatch and offers a separately approved baseline run. Existing evidence remains visible but cannot produce an unsupported comparison.

Show baseline dates and reused status. Elapsed-time comparisons with old baselines are observational: provider load and an upstream model changing behind an unchanged identifier may remain unknown. No automatic age-based rerun is required. A suspicious shift can motivate a user-approved baseline refresh.

Use the same frozen pricing table for a cost comparison. If stored per-model usage supports repricing, recompute comparable estimates without rerunning agents and retain the original values. Never mix differently priced totals silently.

## Measurements and verdicts

Retain per-trial outcomes; do not reduce the evidence to one aggregate row per job. Repeated trials are independent ordinary requests from reset environments, not opportunities to select the best answer.

Measure:

- Correctness and protected-state preservation, with task/trial denominators.
- End-to-end wall-clock time from kickoff to the final deliverable, including the harness's own testing, reviews, delegation, retries, and scripted-user interactions. External benchmark grading is measured separately.
- All orchestrator and descendant model calls, with model, effort, input/output/cache categories, usage completeness, and pricing provenance. Avoid counting child usage twice when parent telemetry already aggregates it.
- Total attempted-work cost, mean cost per trial, and cost per successful trial: total cost across the evaluated attempts divided by successful attempts. With zero successes, report no successful outcome rather than zero cost per success.
- Delegation, repair loops, testing churn, and clarification counts as explanations rather than automatic rewards for a preferred process.

Parallel child durations are not added together as user waiting time. Missing descendant telemetry prevents a complete cost/token claim. Subscription execution may report API-equivalent cost; never label it actual incremental subscription spending or infer quota consumption from token counts alone.

Compare effectiveness before efficiency. Show the observed most reliable, cheapest eligible, and fastest eligible contenders. Recommend one only when the declared decision policy supports that conclusion. When cost and speed favor different contenders, explain the tradeoff rather than inventing a weighted score. Incomplete or incompatible evidence cannot create a winner. Unreviewed comparisons remain explicitly provisional and distinct from finalized release evidence.

History judgments compare a candidate with its selected predecessor: Improved, Regressed, Mixed, or No clear change. Also support First comparison, Insufficient evidence, and Incompatible evidence. Report exact changes and denominators next to those labels; absence of detected change is not proof of equivalence.

### Approved starting defaults

These starting defaults were included in the approved design. The implementation plan specifies the decision policy before any new comparison results are collected:

1. Use the existing three-repetition calibration policy for the initial full comparison; retain one-trial smoke checks as diagnostic only.
2. Start with strict quality eligibility: all required development behavior/protected-state checks pass on every scheduled trial. If no contender qualifies, report the observed most reliable contender and unmet requirements without recommending a quality-qualified winner. This conservative rule applies to the small development suite, not automatically to the harder optional DeepSWE lane.
3. Show API-equivalent cost and end-to-end time separately. A quality-eligible contender must have sufficiently supported practical advantages under the recorded decision policy to receive an overall recommendation; otherwise show the leaders and say No clear winner. Exact statistical and practical-difference rules must be specified in the implementation plan before verdict code is written, rather than selected after results are seen.

## Dashboard experience

Preserve Observable Framework and the static public-data publication architecture. The primary surface is an answer with evidence, not a collection of charts.

### Comparison overview

Lead with the selected kickoff configuration, candidate version, and an explained verdict. Immediately show a compact contender table: tested correctness, successful/scheduled trials, cost per success, and end-to-end time. Identify whether results are provisional and whether baselines were reused. Tokens and delegation details are secondary.

Follow with why the result changed: task regressions or recoveries, measured usage differences, and limitations. Distinguish measured associations from causal explanations. Provide links to the supporting tasks, runs, and source/configuration diffs. Charts are optional supporting detail.

### Version history

Each entry contains the harness label, source/configuration identity, previous tested version, change summary, hypothesis, associated runs, result classification, and changes versus both the predecessor and selected baselines. Repeated experiments on unchanged code attach to the same version with their run reason. Branches identify their explicit predecessor rather than assuming adjacent timestamps imply ancestry.

The preparing agent writes the change summary before execution and verifies it against the source and configuration diff. Results do not rewrite the hypothesis. A bundled revision supports a version-level conclusion, not attribution to one of several edits. Corrected grading creates a new linked evidence revision and recomputes affected conclusions without overwriting the original run.

### Evidence detail

Offer a compact task comparison with expandable trial and agent-tree information, safe usage breakdowns, infrastructure classification, provenance, and limitations. Keep machine hashes and sparse counters in detail views. Use numeric/date values for sorting and display formatters for presentation. Selection is linkable and survives navigation through URL state. Preserve historical URLs or redirect them to their corresponding evidence views.

Support empty history, missing baselines, incomplete runs, unavailable usage, provisional comparisons, incompatible cohorts, and corrections explicitly. The first screen must not imply that an execution finishing successfully means its task tests passed. A small-screen reader must be able to read the verdict and core comparison without traversing a 25-column table.

## Implementation boundaries

Extend the existing materialization, manifest planning/execution, provider adapters, result validation, and publication paths. Do not add a new evaluation framework, dashboard server/database, public raw-trace viewer, or run-control UI.

Likely work areas are `Materialize.py` for complete contender delivery; `Runs.py` and provider adapters for versioned experiment inputs, real delegation, and scripted-user interactions; reporting/schema code for trial/tree usage and comparison provenance; shared dashboard components for verdicts, navigation, and history. Actual runtime support for multi-turn input and child-agent accounting must be verified before selecting an adapter implementation. A missing capability must be reported, not simulated as successful real delegation.

Existing public data remains a historical lane. Earlier runs that installed only the Harness plugin or used different task instructions cannot be relabeled as full Skills-n-Stuff comparisons. The first valid experiment under this design establishes new reference evidence. Existing raw-job privacy, exact approval, quarantine, and reviewed-publication boundaries remain intact.

## Acceptance checks

| Check | Required proof |
| --- | --- |
| AC1 | Studio Moser materialization accounts for the complete pinned collection and dependencies, with a valid frozen rubric and actual delivery inventory. |
| AC2 | The same kickoff configuration starts every contender; real child routes execute and their usage is included without double counting. |
| AC3 | Existing development fixtures remain verifiable, neutral comparison prompts are versioned, and contract scores do not influence the general winner. |
| AC4 | The scripted user handles ordinary approvals/clarifications consistently and cannot reveal answers or expand authority. |
| AC5 | Candidate-only planning reuses exact compatible baseline IDs and starts no baseline sessions; mismatched conditions are identified before execution. |
| AC6 | Changing a rubric creates a candidate version; changing attempt count or other common evaluation conditions cannot silently reuse incompatible aggregates. |
| AC7 | Failed attempts count toward attempted-work cost; missing child usage, zero successes, and partial coverage produce honest unavailable/limited conclusions. |
| AC8 | Each history entry links verified edits and the original hypothesis to predecessor and baseline comparisons; reruns and regrades preserve provenance. |
| AC9 | Live desktop and small-screen checks prove the verdict, comparison, history, numeric sorting, deep links, and insufficient-evidence states. |
| AC10 | Public outputs pass allowlist and identity validation; tests use deterministic fixtures before any separately approved model-backed canary. |

## Research informing the design

- [Harness-Bench](https://arxiv.org/html/2605.27922v1) compares complete configurations under shared external conditions while retaining native behavior. Its results are configuration-level diagnostics, which supports preserving delegation without claiming to isolate the rubric's individual effect.
- [Princeton HAL](https://hal.cs.princeton.edu/about) evaluates agent accuracy alongside cost and supports agent implementations without imposing a common internal framework.
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) recommends realistic isolated trials, repeated measurements, outcome-oriented grading, and inspecting evaluation failures. This supports separating preferred workflow compliance from the main development verdict.
