# Harness Testing

Harness Testing answers one question: **does a coding-agent harness make the agent more correct, cheaper, faster, or less annoying on Studio Moser's kind of work?** It runs the same frozen tasks against Nothing (the bare provider runtime), Superpowers, and the full Skills-n-Stuff collection, then shows correctness, cost, time, and behavior side by side.

## Start here in a new conversation

Check `git status --short --branch` and recent commits in the intended checkout. Run commands through that checkout's `uv run`. Inspect retained local manifests and reports under `runs/` before claiming a run has happened; they are ignored and may be absent in a fresh clone. Planning and documentation requests do not authorize model execution: each exact manifest digest needs fresh approval before `run execute`.

## What we compare

| Contender | Delivered inputs |
| --- | --- |
| Nothing | Provider-native runtime with no added harness |
| Superpowers | Pinned Superpowers plugin |
| Studio Moser | Every plugin and skill in the pinned Skills-n-Stuff collection, its declared dependencies and a frozen rubric |

An optional `studio-personality` contender loads only the frozen house-style file, to isolate the writing guidance from the engineering skills.

The kickoff fixes the orchestrator's model and effort; normal child routing stays available. Everything the agent tree spends is measured together. Correctness comes first: a contender is eligible when it matches the best correctness observed in the cohort and its final-patch review found no confirmed remaining defects. Among eligible contenders, cost and time decide using plain ratio thresholds. One attempt per task on a declared scope is decision evidence; repetitions are optional.

## Which tasks exist

| Lane | Scope |
| --- | --- |
| `tasks/workflow/` | Nineteen controlled React/TypeScript, JavaScript, static-web and Rust fixtures, each with a neutral `Comparison Instruction.md`, a scripted user, a protected verifier and five model-free QA cases |
| DeepSWE research | Six pinned tasks from real open-source repositories, fetched into ignored `.cache/deepswe/` |

These are frozen benchmark projects. A harder test means selecting or authoring a frozen task with a protected verifier, not a more demanding prompt. See [Task Authoring](docs/Task_Authoring.md).

## Run a comparison

1. Copy a template from `runs/examples/`, set the harness commits, kickoff model and tasks, and put the reviewed personal rubric at ignored `runs/inputs/Model Rubric.yml`.
2. Plan: `uv run harness-test run plan --request 'runs/inputs/Experiment Request.json'`. This installs plugins and inspects images but starts no model.
3. Obtain approval of the printed manifest digest, then `uv run harness-test run execute --manifest … --approve sha256:…`.
4. Evaluate the retained submissions: `review prepare` and `review record` for the blinded final-patch review, `collaboration prepare` and `collaboration record` for the blinded automated work-quality grades. Grader sessions are model work and need their own approval.
5. For a full toolbox pass, bind the controlled and research manifests with `campaign plan`, then `campaign summarize` with the original lane reports followed by any recovery or correction reports in execution order. It fills every scheduled slot once and never replaces a completed trial unless the task itself was corrected.

The [Runbook](docs/Runbook.md) has the exact commands; [Methodology](docs/Methodology.md) explains the measurements and rules.

## Dashboard

The dashboard is a read-only Observable site built from local evidence:

```bash
npm ci --prefix dashboard --ignore-scripts
npm --prefix dashboard test
npm --prefix dashboard run build
```

Without a `dashboard-data/reports` directory the build reads `runs/evidence` directly, skipping files that are not public-safe run reports. The Results page shows the ranking, the quality trade-offs, and a Behavior section with transcript metrics and automated grades for every kickoff model and harness version side by side.

## Repository map

| Location | What to inspect |
| --- | --- |
| `src/harness_testing/CLI.py` | CLI entry and supported flags |
| `Experiments.py`, `Contenders.py`, `Comparison_Tasks.py` | Request compilation, frozen harness versions and neutral task materialization |
| `Runs.py`, `Materialize.py`, provider agents, `Native_Conversation.py`, `Simulated_User.py` | Execution, plugin delivery, native turns and the bounded simulated user |
| `Trial_Evidence.py`, `Experiment_Reports.py`, `Comparisons.py`, `Campaigns.py` | Whole-tree accounting, per-trial evidence, the per-task verdict and stitched campaigns |
| `Code_Reviews.py`, `Collaboration_Grading.py`, `Collaboration_Quality.py` | Blinded final-patch review, blinded automated grades and deterministic transcript metrics |
| `policy/`, `Versions.toml`, `runs/Profiles.toml` | Schemas, thresholds, pins and admission assumptions |
| `tests/`, task-local `tests/` | Python unit checks and protected model-free task QA |
| `dashboard/` | Read-only Observable UI |

Local artifacts are ignored: `runs/inputs/` (private requests and rubric), `runs/generated/<digest>/` (manifests and current `Run_Report.json`), `runs/evidence/` (immutable report revisions), `arms/materialized/` and `.cache/` (frozen bundles and task materializations), `jobs/raw/` and provider homes (raw traces), `dashboard/dist/`.

Never copy raw provider traces, hidden reasoning, tool output, session IDs, credentials or host paths into tracked files or dashboard assets. Reports carry only the normalized user-visible root conversation.

## Local development

```bash
uv sync --frozen
uv run harness-test validate --static-only
uv run pytest -q tests/unit
npm --prefix dashboard test
```

For a changed comparison fixture, prove the reference and no-op behavior first:

```bash
uv run harness-test task qa --task react-saved-view-feature --variant comparison --case oracle
uv run harness-test task qa --task react-saved-view-feature --variant comparison --case nop
```

Docker-backed QA is model-free but can be expensive; do not rerun every pack between small edits.
