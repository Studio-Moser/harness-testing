# Harness Comparison Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Tasks have dependencies; do not delegate edits to shared files concurrently.

**Goal:** Answer which of Nothing, Superpowers, and each Studio Moser version works best on the existing development tasks, and explain whether harness edits improve tested correctness, cost, or time.

**Architecture:** Extend the existing Harbor runner, native provider adapters, sanitized reports, and Observable dashboard. Freeze contender versions separately from evaluation conditions. Compile candidate-only experiments against exact reusable evidence. Compute conclusions in Python and render those conclusions in the read-only dashboard.

**Tech stack:** Python 3.12, Harbor 0.22.0, existing jsonschema/PyYAML, pytest, Observable Framework, native JavaScript and Node tests. No new service, database, evaluation framework, or statistical dependency.

**Spec:** [Harness Comparison Design](Harness%20Comparison%20Design.md), approved September 5, 2026. Code baseline: Harness Testing `58a470f`. Collection inspected: Skills-n-Stuff `dd318ec6f4c1c6d4e058378e306612a509efa46f`.

**Status:** P1–P7 implemented and verified; P8 implementation, documentation, review and offline QA are complete. Verification covered 491 Python tests, 24 dashboard tests, 45 protected task QA cases, desktop/mobile browser checks, Ruff, static validation and the production dashboard build. Three separately approved diagnostics ran on Codex 0.153.4. The first exposed cleanup/inventory defects; those were fixed and the failed evidence retained. The second passed protected correctness for all three contenders with complete usage accounting. The third proved one bounded scripted approval, two turns on the same Astra High root, and a real Sol High child after the frozen rubric was read; protected grading and whole-tree accounting passed. The trace proves direct native model selection, not execution of the Harness route resolver or a benefit from the rubric. Ordinary Studio trials chose direct implementation; the third diagnostic deliberately required delegation and is excluded from primary comparisons. The first 81-trial cohort remains separately unapproved; no reusable baseline or overall winner is established. The checklists below retain the original implementation specification.

## Global constraints

- Work from the current main worktree, not the older root checkout. Before code, create an isolated feature branch/worktree using the repository workflow and retain both planning documents. Do not commit on main.
- Keep existing exact-manifest approval, credential isolation, protected verifiers, quarantine, and publication allowlists. Changes to budgets or execution inputs invalidate approval.
- Studio Moser is the complete collection plus required dependencies and a valid frozen rubric. Historical Harness-plugin-only runs retain their actual identity.
- Same kickoff model/effort and common capabilities; native harness behavior decides whether and how to delegate. Do not force child execution in ordinary comparison trials.
- Reuse existing development fixtures and correctness oracles. Keep contract/workflow diagnostics separate from neutral outcome comparisons.
- No paid canary until deterministic checks pass and its concrete manifest receives the existing approval. Never use simulated executor results as evidence that a real harness works.
- A failure to reproduce required native behavior is a capability gap to report, not a reason to quietly test a different configuration.
- Use Title Case with spaces for new documents/data files; Python and JavaScript module names use Title_Case underscores. Preserve existing ecosystem filenames and paths.

## P1 — Runtime proof before promising chat fidelity

The current integration is not yet proof of the requested normal-chat behavior:

- `HarnessClaude.run` and `HarnessCodex.run` delegate to one-turn Harbor methods. Harbor has resume support, but a complete benchmark-user conversation controller does not exist.
- Harbor's Claude converter reads child transcripts; this is useful existing work, but aggregate token fields do not establish per-model, deduplicated tree accounting.
- Harbor's Codex converter selects a recent session directory. Selecting by recency cannot safely identify an orchestrator when children and resumed turns also create logs.
- The Claude adapter caps plugin directories at two. Materialization installs only the Harness plugin for the Studio Moser layer.
- `_job_document` grants network access for the kickoff provider. Normal cross-provider routing may need additional approved executors and hosts.
- Harbor can remap Claude child models to the kickoff model when a custom provider URL is used. Such remapping must not silently defeat the rubric.

**Files:** inspect `Versions.toml`, `images/Node_Agent.Dockerfile`, `images/Rust_Agent.Dockerfile`, both provider adapters, and installed Harbor implementations. Extend `tests/unit/test_Claude_Agent.py` and `test_Codex_Agent.py`. Add a short runtime evidence section to `docs/Runbook.md` when implementation establishes the result.

- [ ] Read the pinned provider binaries' version/help and locally installed protocol definitions in the task image without starting model sessions. Record exact support for explicit session resume, native delegation, child model/effort selection, pending user requests, and transcript identities. Host CLI capabilities are not proof of image capabilities.
- [ ] For each supported provider, choose its documented native conversation mechanism. Prefer explicit session IDs. Do not use `resume --last` or implicit continuation across a directory containing child sessions. If an SDK/control mode is required, verify its pinned implementation before adapting the runner; do not infer support from the GUI application.
- [ ] Extend existing fake-environment tests to capture the actual adapter commands and simulate two turns plus a child session. Assert the second turn resumes the root session, the kickoff remains unchanged, all logs survive cleanup, and credentials disappear on exceptions as well as success.
- [ ] Record one capability result per runtime: `verified_offline`, `unsupported`, or `needs_live_confirmation`, with source version and evidence. An offline parser/command test never becomes a live capability claim.
- [ ] Reject a requested required capability with a named preflight error when the chosen adapter cannot provide it. Continue independent manifest, reporting, and dashboard work with deterministic fixtures; do not ship a successful full-comparison label through that gap.

Regression assertion to add to the existing command-capture fixture after implementing the provider-specific resume path:

```python
assert root_session_id in resumed_command
assert child_session_id not in resumed_command
assert "resume --last" not in resumed_command
assert captured_root_models == [requested_model, requested_model]
assert all(path.exists() for path in retained_turn_logs)
```

Run `uv run pytest tests/unit/test_Claude_Agent.py tests/unit/test_Codex_Agent.py`. Before implementation, the new root-session assertion must fail against the current one-turn adapter. P1 resolves the transport choice for P4; this plan intentionally does not invent an unavailable provider protocol.

## P2 — Freeze versions and compile explicit experiment requests

**Files:** add `src/harness_testing/Experiments.py`, `policy/Experiment Request.schema.json`, and `tests/unit/test_Experiments.py`; extend `Materialize.py`, `Runs.py`, `CLI.py`, `tests/unit/test_Materialize.py`, `test_Runs.py`, and `test_CLI.py`.

Use the existing manifest compiler and content-hashing patterns. `Experiments.py` owns request validation, contender identity, compatibility checks, and reference selection; it is not another job executor.

The version-1 request has these required top-level fields:

| Field | Contract |
| --- | --- |
| `schema_version`, `label`, `purpose` | Version `1`; purpose `baseline`, `candidate`, or `diagnostic` |
| `contenders` | Nonempty list of versions to execute, with stable family/label, immutable source and dependency references, delivery inputs, and rubric snapshot or explicit disabled state |
| `conditions` | Kickoff runtime/version/model/effort; task IDs and all task/evaluator digests; image/resources/toolchains; common executor inventory and authority; scripted-user digest; attempts, schedule, timeouts/retries; accounting and decision policy IDs |
| `baseline_result_ids` | Exact Nothing and Superpowers evidence revisions for candidate mode; explicit empty list in baseline mode |
| `predecessor_result_ids` | Exact previous candidate evidence revisions, or empty list plus `first_version: true` |
| `change` | Hypothesis, verified summary, source/config diff references, and explicit rerun reason if version identity is unchanged |
| `limits` | Billing route, maximum attempted sessions, total tree budget, timeout and interaction bounds |
| `publication` | Existing destination and mode, including local-only |

Request paths are local preparation inputs. Public outputs contain only safe content identities and reviewed summaries, never those paths or raw rubric contents. JSON Schema rejects unknown fields, invalid enums, empty identifiers, nonfinite/negative numeric values, and contradictory mode combinations. Semantic validation returns all actionable missing/mismatch reasons together before materialization or execution.

- [ ] Write failing tests for a candidate-only request scheduling just the candidate, missing baseline IDs, a wrong baseline family, and unknown fields. Mock the existing execution boundary and assert no model subprocess is called while preparing a request.
- [ ] Add `harness-test run plan --request PATH` as an alternative to legacy cell arguments, preserving legacy commands for historical/diagnostic use. Make argument modes mutually exclusive; request limits must not be silently overridden by CLI defaults. Continue emitting an ordinary frozen manifest accepted by `run execute --manifest ... --approve ...`.
- [ ] Introduce content-derived contender identity. Hash immutable source trees, full skill/plugin inventory, dependencies, injected startup rules, rubric bytes/disabled state, and provider delivery settings. Labels and hypotheses are descriptive metadata; identical effective content shares a version even when rerun.
- [ ] Enumerate the pinned collection from its manifests and installation rules. Resolve dependencies once, validate namespaced skill collisions, account for every skill and required surface, and reuse `_delivery_surfaces`/bundle validation. Replace the two-plugin restriction with validated paths and actual complete inventory. Never copy a developer home or private memory.
- [ ] Extend new manifest cells with contender identity/family/label. Keep legacy arm decoding as a compatibility path; do not force new families into A0–A3 or relabel old A2.
- [ ] Give the comparison conditions a separate digest. Include repetitions and semantic execution/evaluator inputs. Exclude contender sources and selected rubric routes; include the common available child-model pool. Reuse existing identity helpers where semantics match; never hash the entire repo simply because a documentation file changed.
- [ ] Resolve exact reference IDs and verify report identity, compatible condition fields, requested task/trial coverage, contender family, and evidence revision. Fail with field-specific differences; never substitute the latest run. Frozen reports, not mutable directory names, identify reference evidence.
- [ ] Create immutable change records from verified source/config diffs before execution. Require an explicit predecessor; branch ancestry is not timestamp adjacency. Preserve original hypotheses through reruns and regrades.

Define these concrete entry points in `Experiments.py`:

```python
def validate_experiment_request(document: dict) -> list[str]:
    """Return schema and semantic errors; no subprocess or network side effects."""

def comparison_mismatches(left: dict, right: dict) -> list[str]:
    """Return sorted differing condition field paths, excluding contender metadata."""

def resolve_reference_reports(request: dict, reports: list[dict]) -> list[dict]:
    """Return only exact validated requested IDs, or raise ValueError with reasons."""
```

Test the intentional-variable boundary without involving a model:

```python
from harness_testing.Experiments import comparison_mismatches

def test_attempt_count_changes_conditions_but_rubric_does_not():
    first = {"kickoff": {"model": "fixture-model", "effort": "high"},
             "attempts": 3, "executor_inventory_digest": "pool-one"}
    assert comparison_mismatches(first, dict(first)) == []
    assert comparison_mismatches(first, first | {"attempts": 1}) == ["attempts"]
    # Rubric belongs in contender identity, never in this conditions object.
```

Also mutate actual rubric bytes in the materialization fixture: contender ID must change, conditions must not. Run targeted tests for Experiments, Materialize, Runs, and CLI; preserve existing tamper/approval tests.

## P3 — Neutral task prompts and a bounded scripted user

**Files:** add `Comparison Instruction.md` and `Scripted User.json` under each of the nine existing `tasks/workflow/<task-id>/` directories; extend task materialization in `Materialize.py`, task validation in `Validate.py`, `QA.py`, and related tests. Add `src/harness_testing/Scripted_User.py`, `policy/Scripted User.schema.json`, and `tests/unit/test_Scripted_User.py`.

- [ ] Read all nine current prompts, protected-file manifests, and correctness criteria. For each task, preserve product behavior, writable scope, and security/protected-state boundaries in its comparison prompt. Remove prescribed command order/counts and harness invocation instructions. Do not weaken the oracle or expose its hidden expectations.
- [ ] Materialize a distinct comparison dataset using existing environments and verifiers, replacing only its selected prompt and evaluator policy. Preserve legacy task paths and workflow scores. Add `--variant comparison` to the existing workflow QA/materialization path; hash the chosen variant.
- [ ] Main correctness requires the existing behavioral reward and protected-state checks. Exact workflow commands and testing churn remain diagnostics. Ensure the contract pack cannot enter the main comparison denominator.
- [ ] Define frozen task facts and scoped routine approvals. Responses must be deterministic, reviewable, and available equally to all contenders. Match explicit provider user-request events where possible. For final-text clarification requests, use only bounded authored rules established from the task facts; ambiguous unmatched requests become `task_definition_gap`, not guessed answers.
- [ ] A generic approval response is allowed only for a recognized routine gate whose requested action is within the frozen task authority. Never approve by matching a lone word such as “proceed.” Solution requests, additional spending, external messages, deployment, or expanded edits receive no grant.
- [ ] Return typed decisions `reply`, `complete`, `task_definition_gap`, `authority_denied`, or `interaction_limit`; record rule ID, question/reply locally, and safe aggregate counts. Cap interactions at 12 for this policy version. Exhaustion is not task success.

Proposed interface and authority regression:

```python
def select_reply(request: dict, policy: dict, interactions: int) -> dict:
    """Resolve a normalized runtime user request using frozen rules only."""

def test_unlisted_authority_is_never_approved():
    from harness_testing.Scripted_User import select_reply
    policy = {"interaction_limit": 12, "facts": {}, "rules": []}
    decision = select_reply(
        {"kind": "approval", "text": "Publish this externally", "actions": ["publish"]},
        policy, 0,
    )
    assert decision["status"] == "authority_denied"
    assert decision.get("reply") is None
```

The normalized `actions` must come from a supported structured event or an explicit authored rule; model prose alone does not prove scope. Test ambiguous mixed-scope questions, unknown facts, hidden-test requests, repeated gates, normal completion, and policy digest changes.

Run `uv run pytest tests/unit/test_Scripted_User.py tests/unit/test_Materialize.py tests/unit/test_Validate.py tests/unit/test_QA.py tests/unit/test_Workflow_Criteria.py`, then `uv run harness-test task qa --pack workflow --variant comparison --all-cases`. The latter command is a planned extension. Oracle solutions must pass; no-op, near-miss, tampering, and adversarial cases must still fail for the intended reasons.

## P4 — Execute full conversations and capture complete attempted work

**Files:** extend `Claude_Agent.py`, `Codex_Agent.py`, `Runs.py`, `Metrics.py`, `Trajectory_Events.py`, and their tests; add `src/harness_testing/Trial_Evidence.py` and `tests/unit/test_Trial_Evidence.py`. Modify images only for verified required runtime capabilities.

P4 depends on the P1 transport proof and P2/P3 frozen contracts. Keep provider-specific lifecycle code in the existing adapters; shared accounting belongs in Trial_Evidence, not a new generic agent framework.

- [ ] Implement the chosen native turn/resume mechanism. Feed the ordinary request once, reply to supported user requests using P3, and retain a single root trial identity through every turn. Grade only after completion/terminal failure. Stage scoped credentials per lifecycle and clean them in `finally`.
- [ ] Deliver the same common executor inventory to every contender. Make any necessary child-provider credentials/network access explicit in the approved manifest. Do not inherit proxy model overrides that change selected routes. Preflight both startup model and callable child executors; a configured name is not proof of availability.
- [ ] Track root and descendant session IDs, parent relationships, actual model/effort when reported, provider request/message IDs, and terminal status. An unreported effort stays unknown. Detect unresolved child starts, missing transcripts, and interrupted calls.
- [ ] Normalize usage into per-call leaf records. Use provider-scoped request/message identity plus session identity; merge streaming updates using final authoritative usage, not by summing chunks. Root aggregate summaries are reconciliation evidence, never additional leaf calls. Retain cache-read/write categories and avoid adding reasoning tokens again when included in output.
- [ ] Account for all retained turns, agent repairs, failed attempts, descendants, and internal retries. Reuse provider parsing helpers where they preserve identity. Keep incomplete usage as incomplete rather than imputing zero. Reconcile aggregate totals only when the provider documents equivalent scope.
- [ ] Bound the whole tree by approved budget/time/session policy. Where live usage/cancellation is available, cancel the tree at limits. If a required hard monetary bound cannot be enforced for an executor, preflight must explain that limitation and reject that policy rather than claim a guaranteed cap. Do not issue new work after the bound is reached.
- [ ] Schedule reset trials in a deterministic, frozen balanced order across task/contender/repetition for new cohorts. Candidate-only runs naturally contain no baseline jobs. Record actual order and concurrency. Do not treat separately collected baseline rounds as simultaneously paired trials.
- [ ] Record root wall-clock start/end once, excluding provisioning and external grading, including conversations, internal tests and child waiting. Retain provisioning/grading separately. Do not add parallel child durations.

Local evidence shape (raw text stays local):

```python
trial = {
    "trial_id": "fixture-trial", "task_id": "fixture-task", "attempt": 1,
    "contender_id": "fixture-version", "root_session_id": "root",
    "status": "completed", "correctness": True, "protected_state": True,
    "duration_seconds": 14.0, "usage_complete": True,
    "calls": [
        {"session_id": "root", "parent_session_id": None,
         "provider": "fixture", "request_id": "one", "model": "large",
         "input_tokens": 100, "cache_read_tokens": 0,
         "cache_write_tokens": 0, "output_tokens": 20},
        {"session_id": "child", "parent_session_id": "root",
         "provider": "fixture", "request_id": "two", "model": "small",
         "input_tokens": 50, "cache_read_tokens": 0,
         "cache_write_tokens": 0, "output_tokens": 10},
    ],
}
assert sum(call["output_tokens"] for call in trial["calls"]) == 30
assert trial["duration_seconds"] == 14.0
```

Use this shape in fixture tests, then add duplicate stream chunks, a root inclusive summary, repeated collection, missing child logs, one failing child, and timeout with usage. Verify totals remain stable and missing data disables complete cost claims. Run provider, Runs, Metrics, Trajectory_Events, and Trial_Evidence unit tests. No fixture is a substitute for the later native canary.

## P5 — Versioned conclusions and uncertainty policy

**Files:** add `src/harness_testing/Comparisons.py`, `policy/Comparison Policy.json`, and `tests/unit/test_Comparisons.py`. Reuse pricing conversion in `Metrics.py`; do not calculate decisions independently in JavaScript.

Freeze policy `development-comparison-v1` before collecting new results:

1. **Coverage:** nine selected development tasks, three reset repetitions each by default. All contenders need the exact scheduled coverage. One-trial smoke is diagnostic. Agent failure/timeout is an attempted result; infrastructure failure, missing grading, task-definition gaps, or incomplete scheduling prevent an overall recommendation. Show their counts explicitly.
2. **Eligibility:** every scheduled trial passes behavioral and protected-state checks. Report exact success fractions for everyone. A sole eligible contender can be recommended for tested correctness; no eligible contender yields no quality-qualified winner. This is an observed fixed-suite judgment, not a universal reliability claim.
3. **Accounting:** failed attempts contribute to total attempted-work cost. Cost per success is total attempted cost divided by successful trials, or unavailable at zero successes. Unknown pricing or any unresolved descendant usage makes cost comparison unavailable. Reprice from retained per-model usage using one frozen price table, preserving original estimates and their pricing identity.
4. **Efficiency effect:** for eligible contenders, compare equally task-weighted mean trial cost and mean root duration. Report overall cost per success as well. A practical advantage is at least **10%**; practical noninferiority allows at most **10%** worse. These are explicit product defaults, not thresholds established by the cited research.
5. **Uncertainty:** independently resample repetitions within each fixed task and contender, 20,000 draws using stdlib `random.Random` with a seed derived from the evidence IDs and policy digest. Keep the nine tasks fixed; do not resample different tasks or pair noncontemporaneous repetition numbers. Form percentile intervals for the ratio of task-weighted means. For `K` selected contender pairs and two metrics, use two-sided intervals with per-tail probability `0.05 / (4*K)`. Determine `K` from the selected cohort before inspecting results, not from whichever comparisons look favorable. Reused evidence is resampled once per draw and shared across its comparisons.
6. **Recommendation:** with several eligible contenders, recommend one only when it has a supported practical advantage in cost or time against every other eligible contender and supported noninferiority on the other metric: ratio upper bound `<= 0.90` for advantage, `<= 1.10` for noninferiority. Missing efficiency evidence prevents this recommendation. If cost and speed favor different contenders, say so and show no clear overall winner.
7. **Limits:** intervals describe variation observed in three repetitions of this fixed suite. They do not capture model drift, provider load changes, new tasks, or broad software quality. Historical time comparisons are observational. Identical repetitions can produce narrow intervals without proving universal stability; show repetitions and this limitation beside the conclusion.

Zero-valued comparator means do not produce an infinite JSON number: if both are zero, report no practical ratio advantage; if only one is zero, report an absolute difference and withhold that ratio-based recommendation. Require finite nonnegative inputs at validation.

History uses the same comparisons against the explicitly selected predecessor. An eligibility recovery with no task-level correctness regression is Improved; loss of eligibility with no recovery is Regressed; simultaneous task recoveries and regressions are Mixed. Other incomplete or ineligible comparisons show observed task changes without a supported improvement claim. When both are eligible, supported efficiency gains with noninferiority are Improved, the reverse Regressed, opposing cost/time changes Mixed, and otherwise No clear change. First version, missing/insufficient evidence, and incompatible conditions are separate states. Never translate “No clear change” into equivalence.

Define a single entry point:

```python
def build_comparison(request: dict, reports: list[dict], policy: dict) -> dict:
    """Validate exact evidence, then return safe verdict, reasons, leaders and limits."""
```

- [ ] First test that a cheap failing contender cannot beat one passing all required trials; contract scores cannot affect the result.
- [ ] Implement exact coverage/eligibility/accounting before uncertainty. Assert a failed $2 attempt plus successful $3 attempt costs $5 per success, not $3. Missing child usage yields `null`, never zero.
- [ ] Add deterministic bootstrap tests for stable ratios, reproducible seeds, independent baseline/candidate resampling, selected-family multiplicity, and threshold boundaries. Test tradeoffs, absent data, and insufficient repetitions.
- [ ] Add predecessor tests for first version, rerun, branch lineage, mixed task changes, incompatible conditions, and regraded evidence. Preserve the pre-run hypothesis verbatim.

Run `uv run pytest tests/unit/test_Comparisons.py tests/unit/test_Metrics.py`. Store machine reason codes alongside human explanations, for example `quality_ineligible`, `usage_incomplete`, `practical_advantage_supported`, and `cost_time_tradeoff`. Every sentence must be reconstructible from the selected evidence and policy.

## P6 — Publish safe comparison evidence without rewriting history

**Files:** extend `Run_Reports.py`, `Run_History.py`, `Report_Publication.py`, `Results.py`, `policy/Run_Report.schema.json`, `dashboard/src/data/Public_Results.json.js`, and existing report/publication/safety/loader tests. Add versioned fixtures under `tests/Fixtures/Run_Reports/`.

- [ ] Add a new report schema branch containing sanitized contender/condition identities, scheduled and completed trial rows, outcomes, per-model usage summaries/completeness, pricing provenance, exact reference evidence IDs, change record, and P5 conclusion. Keep old schema branches accepted as historical evidence without invented fields.
- [ ] Publish safe ordinal agent IDs and model/effort/usage breakdowns. Keep provider session/request IDs, user dialogue, raw traces, local paths, credentials, raw configuration, and private diffs local. Public diff links require an allowlisted public destination; otherwise publish a reviewed description and digest.
- [ ] Include the new fields in report identity and tamper checks. A changed grade creates a new evidence revision linked to the original, with original outcomes retained; derived comparisons point to the revision used.
- [ ] Refresh dependent conclusions from explicit reference identities, never implicit latest selection. A prior comparison remains inspectable even when a newer correction exists; mark it superseded and link the replacement.
- [ ] Preserve the current single publication batch, idempotent receipt, provisional/finalized distinction, and quarantine. Validate every new output with the strict schema and public-safety checks before publication.
- [ ] Extend the loader to retain new comparison records and safely coexist with historical runs. Reject missing references, identity tampering, unknown fields, and forbidden text; do not silently discard invalid evidence and compute a winner from the remainder.

Run `uv run pytest tests/unit/test_Run_History.py tests/unit/test_Report_Publication.py tests/unit/test_Results.py tests/unit/test_Public_Safety.py tests/unit/test_Runs.py` and `npm test` from `dashboard`. Include a report containing a secret path in the new change-summary field and verify rejection. No public raw-log route is introduced.

## P7 — Read-only answers, history, and evidence

**Files:** add `dashboard/src/components/Comparisons.js`, `dashboard/test/Comparisons.test.js`, and `dashboard/src/Version_History.md`; update `index.md`, `Comparisons.md`, `Run_Detail.md`, `components/Run_History.js`, and `observablehq.config.js`. Update the old Trends, Task_Matrix, and Quality_Versus_Efficiency pages only for valid navigation or historical labeling.

Primary navigation: **Comparison**, **Version history**, **Evidence**. Existing URLs continue to open historical evidence. No setup form, launch button, approval control, or harness editor.

The comparison page reads in this order:

```text
Studio Moser · selected version      kickoff model · effort

[Verdict or “No clear winner”]
[One sentence explaining correctness, then cost/time evidence]
[Provisional/finalized · exact baseline dates and reused state]

Harness          Tests passed      Cost/success      Time/trial
Nothing          numerator/total   value/unavailable value/unavailable
Superpowers      numerator/total   value/unavailable value/unavailable
Studio Moser     numerator/total   value/unavailable value/unavailable

What changed: verified edits → hypothesis → observed result
Why: task recoveries/regressions, usage, and comparison limits
[Version history] [Inspect supporting evidence]
```

This is an information hierarchy, not fake benchmark data. Use clearly labeled deterministic fixtures during UI development.

- [ ] Render P5's conclusion without recalculating winner logic. Show task/trial denominators, eligibility, reason codes translated into plain language, and missing data. Completion status is never a passing-test badge.
- [ ] Add URL parameters for selected comparison/version/run/task. Validate values against loaded records, preserve selections across links, and handle missing IDs visibly. The initial selection is the latest valid comparison, not simply the latest unrelated diagnostic job.
- [ ] Build version history around explicit predecessor links. Show verified edits, original hypothesis, result label and changes against predecessor and each baseline. Group reruns under unchanged version identity; label branches and evidence corrections.
- [ ] Evidence detail exposes compact task rows and expandable trial/agent usage summaries. Numeric values remain numbers until display formatting; use numeric/date sorting and explicit null handling.
- [ ] Make the verdict and four-column core comparison usable at 390px without page-level horizontal scrolling. Provide accessible table headers, focus-visible links, text status labels, and adequate contrast. Put secondary details behind labeled expansion controls.
- [ ] Test pure selection/navigation helpers and numeric ordering in Node. Drive the actual dashboard in the available browser at desktop and small-screen widths; inspect screenshots and exercise links, sorting, keyboard focus, and history selection.

Proposed display helper regression:

```javascript
import assert from "node:assert/strict";
import {sortNumericRows} from "../src/components/Comparisons.js";

assert.deepEqual(
  sortNumericRows([{time: 102.8}, {time: 38.5}, {time: null}], "time")
    .map(row => row.time),
  [38.5, 102.8, null]
);
```

`sortNumericRows(rows, field, ascending = true)` returns a copy, sorts finite values numerically, and always places nulls last. Test descending order too. Use this helper only if the existing table's numeric comparator cannot provide the behavior directly.

Required live states: supported recommendation, split cost/time leaders, no eligible harness, no baselines, incompatible references, incomplete child usage, partial run, empty history, provisional evidence, rerun, and regrade. Run `npm test` and `npm run build` from `dashboard`; retain fresh local screenshots and concise observed results.

## P8 — Agent pipeline documentation, review, and first valid experiment

**Files:** update `docs/Runbook.md`; add `docs/Agent Experiment Guide.md` and non-sensitive request examples in `runs/examples/`. Extend `Validate.py` affected-file routing only where needed so these new schemas, modules, task variants and dashboard tests are covered by existing CI.

- [ ] Document the full preparation sequence: choose purpose and exact kickoff; freeze contender inventory/rubric; choose existing tasks and neutral variant; set common capabilities and bounds; select exact baseline and predecessor evidence; verify diffs; write hypothesis; validate; compile; inspect the frozen manifest; obtain its existing digest approval; execute; inspect evidence; publish through the existing route.
- [ ] Provide schema-valid baseline, candidate-only, unchanged-version rerun, and rubric-disabled examples using explicit fixture identities. Examples must be clearly non-executable templates until their references are resolved by the preparing agent. Do not embed personal paths or credentials.
- [ ] Explain when to reuse baselines and when condition differences require a new baseline request. Show how to attach a new harness version and how to preserve/recompute evidence after corrected grading. Document all preflight errors and runtime capability limitations discovered in P1/P4.
- [ ] Run the full deterministic checks once the integrated implementation is ready:

```sh
uv run pytest
uv run ruff check src tests
uv run harness-test validate --static-only
uv run harness-test task qa --pack workflow --variant comparison --all-cases
```

Run `npm test` and `npm run build` in `dashboard`. Run affected deterministic validation with the feature branch's actual base SHA. Do not repeat a passing suite without a new change or unresolved concern.

- [ ] Review a pinned implementation diff against AC1–AC10, including the capability proof and fresh UI evidence. Resolve material findings and rerun affected checks. Keep separate logical commits for request/delivery, runtime/evaluation, reporting/verdicts, and dashboard/docs; follow the repository's required pre-commit/review gates.
- [ ] Prepare a minimal native canary manifest that proves a resumed approval and real descendant usage. Diagnostic tasks may deliberately request delegation for this proof; ordinary main-comparison tasks must not force it. Present exact scope and tree budget for approval, then run only that approved manifest. Validate actual kickoff/child models and all usage against local traces.
- [ ] Only after canary evidence establishes required capability, prepare the initial three-contender comparison using the approved three-repetition policy. Nine tasks × three repetitions × three contenders = **81 scheduled task trials**, before separately recorded infrastructure retries and child calls. A later candidate-only version schedules **27 task trials** and references the two unchanged compatible baselines. Compile actual estimates rather than guessing spend.

Implementation can be reviewed with deterministic fixtures while live execution remains separately unapproved. Do not mark the full comparison operational until the native canary proves AC2/AC4 and the first valid cohort establishes reusable evidence.

## Coverage and handoff

| Acceptance | Implementation and evidence |
| --- | --- |
| AC1 | P1/P2: complete collection inventory, dependencies, rubric identity and actual delivery |
| AC2 | P1/P4/P8: fixed kickoff, real native child routes, tree accounting and approved canary |
| AC3 | P3/P5: neutral variant, unchanged protected oracle, separate contract scoring |
| AC4 | P3/P4/P8: deterministic bounded replies, authority regressions, native resume |
| AC5 | P2: exact baseline resolution and candidate-only schedule assertions |
| AC6 | P2: independent version/condition hashes and attempt-count mismatch |
| AC7 | P4/P5: failed work, deduplication, missing usage, partial coverage and zero success |
| AC8 | P2/P5/P6/P7: predecessor, verified changes, immutable hypothesis, reruns and revisions |
| AC9 | P7: desktop/mobile browser evidence, deep links, sorting and failure states |
| AC10 | P6/P8: identity/safety tests, deterministic QA, existing approval boundary |

Critical path: P1 → P2/P3 → P4 → P5/P6 → P7 → P8. P5 fixture development and P7 information hierarchy can progress while a native capability is unresolved, but fixture success must remain labeled as such. Self-review this plan against the approved design before implementation; replan a transport choice if P1 disproves its feasibility.
