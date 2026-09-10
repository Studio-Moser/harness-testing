# Harness Testing

Harness Testing asks whether a coding-agent harness helps: **does it complete the task correctly, what does that cost in time, tokens and money, and is the agent easier to work with?** It compares Nothing, Superpowers and Studio Moser's full Skills-n-Stuff collection, including its declared Superpowers dependency. The dashboard presents the answers, supporting evidence and uncertainty; agents prepare runs through the CLI.

## Start here in a new conversation

Check `git status --short --branch` and recent commits in the intended checkout. Run commands through that checkout's `uv run`; the CLI resolves its repository from the installed Python module. Read the [Agent Experiment Guide](docs/Agent%20Experiment%20Guide.md) for the current run contract and [Next Queued Experiment](docs/Capability_Pack.md#next-queued-experiment) for pending work. Inspect retained local manifests and reports before claiming a run has happened; they are ignored and may be absent in a fresh clone. Missing local artifacts are not proof that no prior runs exist and do not justify rerunning them automatically.

The queued next step is **Q1 — a three-trial Quill shared-toolbar pilot**, one trial per harness. It needs preparation to connect the existing DeepSWE task to the newer comparison path. It takes priority over the prepared, unapproved 81-trial fixture cohort. The queue entry is not execution approval.

## What we compare

| Contender | Delivered inputs |
| --- | --- |
| Nothing | Provider-native runtime with no added harness |
| Superpowers | Pinned Superpowers plugin |
| Studio Moser | Every plugin and skill in the pinned Skills-n-Stuff collection, its declared dependencies and frozen rubric |

An optional `studio-personality` diagnostic contender loads only a frozen startup-instruction file. Use it to isolate Studio's communication guidance from the full harness; it is not one of the three primary engineering baselines.

Studio Moser means the full collection, not only its `harness` plugin. A future version can change the rubric, disable it or remove/replace Superpowers; declare and freeze those inputs explicitly.

The kickoff fixes only the orchestrator's model and effort—currently GPT-6 Astra High in the comparison templates. Normal native delegation stays available. Measure the root, subsequent turns and children together. Proving that a child was routed successfully does not prove the rubric improves outcomes; that requires a controlled version comparison.

Protected correctness comes first. Report cost, time and tokens separately, retain failures and missing measurements, and do not substitute workflow compliance for working code. Version history records the change, hypothesis, predecessor and evidence for improvement or regression. Reuse Nothing/Superpowers baselines only by exact retained report IDs under matching conditions; a new model or incompatible task/evaluator change needs fresh baselines.

## Which tasks exist

| Lane | Current scope | Use |
| --- | --- | --- |
| `tasks/workflow/` | Nine synthetic React/TypeScript, static-web and Rust fixtures | Small development changes; neutral `Comparison Instruction.md` and bounded `Scripted User.json` support versioned comparisons |
| `tasks/contract/` | Eight deterministic Harness contract scenarios with local stubs | Delivery, routing, missing-dependency and other protocol diagnostics |
| DeepSWE research | Six pinned tasks from real open-source repositories | Substantial capability work; fetched content stays in ignored `.cache/deepswe/` |

These are frozen benchmark projects, not task definitions connected to our live product repositories. Asking for a harder task means selecting a suitable frozen task or authoring one with a fixed starting repository, clear requirements and a protected verifier. Merely making the prompt more demanding does not establish a fair test.

The versioned request compiler resolves the queued Quill task through the `deepswe` diagnostic variant, using selected cached inputs, native conversations and whole-tree reports. Other DeepSWE tasks remain in the manual research lane. Select Quill explicitly when materializing it. See [Capability Pack](docs/Capability_Pack.md) before using it and [Task Authoring](docs/Task_Authoring.md) for local fixtures.

## Prepare a run, then obtain exact approval

Use [Agent Experiment Guide](docs/Agent%20Experiment%20Guide.md) and the strict [request schema](policy/Experiment%20Request.schema.json). The examples in `runs/examples/` are templates, not instructions to spend compute. Start with the smallest representative pilot; the nine-task, three-repetition policy is a requirement for an overall recommendation, not a requirement to launch 81 trials immediately.

```bash
uv run harness-test run plan --request 'runs/inputs/Experiment Request.json'
```

Planning starts no model session, but may install/validate plugins and inspect Docker images. Review the exact tasks, versions, model/effort, child inventory, root trial count, timeouts, credentials, estimate and publication scope before requesting approval. Only execute the exact approved digest using the [Runbook](docs/Runbook.md#plan-before-any-model-backed-run). A request to investigate, document or queue work does not authorize a benchmark run.

Subscription-only `$0` incremental spending still consumes quota, time and compute. The current comparison admission estimate uses generic token allowances from `runs/Profiles.toml`; it is neither an empirical forecast nor a whole-tree hard spending stop. Use measured pilot usage to explain likely scale, with its uncertainty. [Comparison Pricing](docs/Comparison%20Pricing.md) distinguishes API-equivalent token estimates from bills.

Legacy A0–A3 arm commands, explicit skill invocation and discovery modes remain available for earlier diagnostics. They are not interchangeable with the full-collection comparison request.

## Repository map

| Location | What to inspect |
| --- | --- |
| `src/harness_testing/CLI.py` | CLI entry and supported flags |
| `Experiments.py`, `Contenders.py`, `Comparison_Tasks.py` in that package | Request compilation, frozen harness versions and neutral task materialization |
| `Runs.py`, provider agents, `Native_Conversation.py`, `Scripted_User.py` | Execution, authentication boundaries, turns and scripted replies |
| `Trial_Evidence.py`, `Experiment_Reports.py`, `Comparisons.py` | Whole-tree accounting, safe evidence and engineering conclusions |
| `Communication_Contracts.py`, `Collaboration_Quality.py`, `Collaboration_Grading.py` | Visible conversation contracts, deterministic metrics, blinded grading and personal calibration |
| `policy/`, `Versions.toml`, `runs/Profiles.toml` | Schemas, recommendation policy, pins and admission assumptions |
| `tests/`, task-local `tests/` | Python unit/contract checks and protected model-free task QA |
| `dashboard/` | Read-only Observable UI: harness comparison, version history and task evidence; earlier diagnostics are separate |
| `docs/Agent Experiment Guide.md`, `docs/Runbook.md` | Current agent pipeline and operational details |
| `docs/Harness Comparison Design.md`, `docs/Harness Comparison Implementation Plan.md` | Approved design and implementation background; verify current status against code and evidence |

Local reproducibility artifacts are intentionally untracked:

| Location | Contents |
| --- | --- |
| `runs/inputs/` | Private request copies and rubric snapshots |
| `runs/generated/<digest>/` | Exact manifests, job configuration and current `Run_Report.json` |
| `runs/evidence/` | Immutable retained report revisions |
| `arms/materialized/`, `.cache/` | Frozen harness bundles and task materializations |
| `jobs/raw/`, provider homes | Private execution artifacts and raw traces |
| `runs/history/`, `dashboard/dist/` | Reconstructed local history and built dashboard |

For new comparisons, inspect version-3 experiment trial/comparison evidence for whole-tree measurements; legacy per-job efficiency summaries are not a substitute. Original reports remain retained when corrected. Missing or unreviewed evidence must remain visibly limited.

Passing tests does not mean the final code passed an independent review. Use [Code Review Evaluation](docs/Code%20Review%20Evaluation.md) to prepare blinded reviews of retained submissions and record confirmed remaining defects, unresolved claims and separate evaluation cost. The dashboard distinguishes this from test outcomes and internal review activity; older test-only results cannot establish reviewed-code superiority.

Collaboration quality is also separate from correctness. Each workflow task carries a communication contract, and complete runs retain the root session's user-visible messages. Use the [collaboration workflow](docs/Agent%20Experiment%20Guide.md#a7--evaluate-collaboration-quality) to generate blinded grades and Tim's A/B preference labels. The dashboard can then answer who was easier to work with, who talked most, which progress updates were useful, and which exact messages violated the contract.

Never copy raw provider traces, hidden reasoning, commands, tool output, session IDs, credentials or host paths into tracked docs or dashboard assets. Collaboration reports may contain only the normalized user-visible root conversation after public-safety validation. Public development-history reports are allowlisted evidence and may include failures; reviewed finalized `results/` remain a separate evidence lane. Publication is bound to the approved manifest destination: local-only runs stay local. See the [Runbook](docs/Runbook.md) before syncing or publishing anything.

## Local development

Use the versions in `Versions.toml`, `pyproject.toml` and `dashboard/package.json`. The commands below start no models; dependency installation may use the network, and builds/QA consume local compute.

```bash
uv sync --frozen
uv run harness-test validate --static-only
uv run harness-test --help
npm ci --prefix dashboard --ignore-scripts
npm --prefix dashboard test
npm --prefix dashboard run build
npm --prefix dashboard run dev
```

For code changes, choose the targeted Python tests in `tests/unit/`; use `uv run pytest -q` at the required checkpoint. For a changed comparison fixture, prove the reference and no-op behavior first:

```bash
uv run harness-test task qa --task react-saved-view-feature --variant comparison --case oracle
uv run harness-test task qa --task react-saved-view-feature --variant comparison --case nop
```

Docker-backed QA is model-free but can be expensive. The [Task Authoring](docs/Task_Authoring.md) guide defines the full five-case gate; do not rerun every pack between small edits. For verifier-only corrections to existing evidence, inspect the Runbook's regrade path before buying another model run.

Shelby is future-only in this repository: [Shelby Adapter Contract](docs/Shelby_Adapter_Contract.md) describes a proposed integration, not an executable adapter or source of private benchmark memory.
