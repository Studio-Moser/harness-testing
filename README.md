# Harness Testing

Harness Testing answers one question: **does a coding-agent harness make the agent more correct, cheaper, faster, or less annoying on Studio Moser's kind of work?** It runs the same frozen tasks against Nothing (the bare provider runtime), Superpowers, and the full Skills-n-Stuff collection, then shows correctness, cost, time, and behavior side by side.

## Results

**[Open the live dashboard →](https://studio-moser.github.io/harness-testing/)** Every trial, per-task result, cost, transcript metric and automated grade, rebuilt from the evidence in this repository on every push.

[![The Results page of the dashboard: quality against runtime, tokens and cost for every harness and kickoff model](docs/Images/Results%20Overview.png)](https://studio-moser.github.io/harness-testing/)

### Claude Opus 5.5, medium effort

19 workflow tasks, one attempt per task per harness, 133 trials. Each new harness version runs alone and is judged against the results already retained for the same model and effort.

| Harness | Correct | Avg cost | Avg time | Work-quality grade | Words per task |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Studio Moser v7** | **100%** | **$0.12** | 22s | 96% | **160** |
| Studio Moser v7 + personal instructions and skills | 100% | $0.13 | **21s** | 96% | 163 |
| Studio Moser v7 + personal instructions | 100% | $0.15 | 24s | 96% | 170 |
| Studio Moser v6 + time matters | 100% | $0.12 | 26s | 96% | 171 |
| Studio Moser v6 | 100% | $0.13 | 27s | 96% | 183 |
| Studio Moser v5 | 100% | $0.17 | 34s | 92% | 299 |
| Nothing | 95% | $0.12 | 29s | 91% | 247 |

Studio Moser v7 is the pick: as correct as anything tested and the least talkative, at the cost of the bare runtime. The two "personal" rows add the developer's own House Style, global instructions and personal skills to v7; on these small tasks they raised cost without improving correctness, grade or brevity, and the one-second time lead of the skills row leaves the formal verdict at no clear winner. Superpowers was skipped on this model: earlier testing showed it wasn't needed on newer models.

### GPT-6 Astra, medium effort

24 tasks, one attempt per task per harness, 72 trials. Every harness solved every task, so cost and time decide.

| Harness | Correct | Avg cost | Avg time | Work-quality grade |
| --- | ---: | ---: | ---: | ---: |
| **Nothing** | 100% | **$0.91** | **3m 11s** | 96% |
| Studio Moser v5 | 100% | $1.21 | 3m 29s | 94% |
| Superpowers | 100% | $1.83 | 4m 06s | **97%** |

Costs are API-equivalent estimates from list prices, not bills. Work-quality grades are blinded automated grades and never decide the ranking. One attempt per task is a real result, not a reliability guarantee: these cover the frozen tasks and kickoff conditions above, not every codebase.

## Start here in a new conversation

Check `git status --short --branch` and recent commits in the intended checkout. Run commands through that checkout's `uv run`. Inspect the tracked reports under `runs/evidence/` and the local manifests under `runs/generated/` before claiming a run has happened; manifests are ignored and may be absent in a fresh clone. Planning and documentation requests do not authorize model execution: each exact manifest digest needs fresh approval before `run execute`.

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
| `tasks/workflow/` | Nineteen active controlled React/TypeScript, JavaScript, static-web and Rust fixtures (three earlier ones are retired, replaced by `-committed` versions that also score house conventions, and kept so retained evidence stays reproducible), each with a neutral `Comparison Instruction.md`, a scripted user, a protected verifier and five model-free QA cases. Three `-committed` tasks also ask for a notes document and a commit, and score house conventions |
| DeepSWE research | Five pinned tasks from real open-source repositories, fetched into ignored `.cache/deepswe/`. pest-character-class-coalescing was dropped: its hidden test expects a side effect of the reference implementation that contradicts the instruction, so every harness failed it identically. |

These are frozen benchmark projects. A harder test means selecting or authoring a frozen task with a protected verifier, not a more demanding prompt. See [Task Authoring](docs/Task_Authoring.md).

## Run a comparison

1. Copy a template from `runs/examples/`, set the harness commits, kickoff model and tasks, and put the reviewed personal rubric at ignored `runs/inputs/Model Rubric.yml`.
2. Plan: `uv run harness-test run plan --request 'runs/inputs/Experiment Request.json'`. This installs plugins and inspects images but starts no model.
3. Obtain approval of the printed manifest digest, then `uv run harness-test run execute --manifest … --approve sha256:…`.
4. Evaluate the retained submissions: `review prepare` and `review record` for the blinded final-patch review, `collaboration prepare` and `collaboration record` for the blinded automated work-quality grades. Reviewer and grader sessions are model work covered by the run's approval, so an approved run continues through them without a second request.
5. For a full toolbox pass, run `campaign summarize` with each lane's original report followed by any recovery or correction reports in execution order. It fills every scheduled slot once, never replaces a completed trial unless the task itself was corrected, and writes the summary the dashboard reads.

The [Runbook](docs/Runbook.md) has the exact commands; [Methodology](docs/Methodology.md) explains the measurements and rules.

## Dashboard

The dashboard is a read-only Observable site built from local evidence:

```bash
npm ci --prefix dashboard --ignore-scripts
npm --prefix dashboard test
npm --prefix dashboard run build
```

The build reads the tracked `runs/evidence/` reports and `runs/campaigns/*/Summary.json` and fails on any report that is not schema-valid and public-safe. Every push to `main` rebuilds it and deploys it to [GitHub Pages](https://studio-moser.github.io/harness-testing/). The Results page opens with a plain-language read of each harness (pros, cons, one recommendation), then the per-task results by type and difficulty, then a Behavior section with transcript metrics, annoyance counts and automated grades for every kickoff model and harness version side by side.

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

Local artifacts are ignored: `runs/inputs/` (private requests and rubric), `runs/generated/<digest>/` (manifests and current `Run_Report.json`), `arms/materialized/` and `.cache/` (frozen bundles and task materializations), `jobs/raw/` and provider homes (raw traces), `dashboard/dist/`, and campaign `Plan.json` files. Run reports in `runs/evidence/` and campaign summaries are tracked and public; the dashboard build and the pre-commit hook reject any that fail the public-safety screen.

Never copy raw provider traces, hidden reasoning, tool output, session IDs, credentials or host paths into tracked files or dashboard assets. Reports carry only the normalized user-visible root conversation.

## Local development

```bash
git config core.hooksPath .githooks
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
