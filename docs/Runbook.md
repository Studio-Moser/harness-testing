# Runbook

## Prerequisites

- Docker
- Python 3.12 and `uv`
- Node 22.23.2 and npm
- Provider CLIs only when a manually approved model-backed run is intended

```bash
uv sync --frozen
uv run harness-test validate --static-only
```

## Development checks

Use the smallest check that proves the change, and the full gates once at the checkpoint:

```bash
uv run pytest -q tests/unit/test_Comparisons.py       # one module
uv run harness-test task qa --task react-accent-polish --case oracle
uv run harness-test task qa --task react-accent-polish --case nop
npm --prefix dashboard test && npm --prefix dashboard run build
uv run pytest -q tests/unit                            # checkpoint
```

## Prepare a request

Copy `runs/examples/Baseline Comparison.json` or `Candidate Comparison.json` into ignored `runs/inputs/`, then set:

- every contender's source commits and the reviewed rubric path (`runs/inputs/Model Rubric.yml`);
- the kickoff provider, runtime, model and effort, and the callable child inventory;
- task IDs and variant, attempts, timeout, provider recovery allowance and resources;
- `purpose` (`baseline` for fresh evidence, `candidate` with exact baseline and predecessor report IDs for a later Studio Moser version);
- the change summary and hypothesis, written before results are seen.

Plan without starting a model:

```bash
uv run harness-test run plan --request 'runs/inputs/Experiment Request.json'
```

Review the printed tasks, versions, model and effort, child inventory, trial count, timeouts, credentials, estimate and manifest digest. The estimate is an admission guard, not a forecast or a hard stop; subscription runs still consume quota and wall time.

## Execute an approved manifest

Only after explicit approval of that exact digest:

```bash
uv run harness-test run execute \
  --manifest runs/generated/MANIFEST_DIRECTORY/Manifest.json \
  --approve sha256:EXACT_APPROVED_DIGEST
```

The first task runs as a delivery canary across every cell; an infrastructure or delivery failure stops before the second task, while a correctness zero continues. Execution writes `Run_Report.json` beside the manifest after each job and rebuilds the local dashboard once at the end. A report holds allowlisted status, scores, timestamps, usage and cost plus the normalized user-visible root conversation; never hidden reasoning, tool output, raw trajectories, session IDs or host paths.

### Subscription authentication

Subscription mode forbids API fallback and requires `--max-budget-usd 0`.

- Codex: unset `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_API_BASE`. The default credential is `~/.codex/auth.json`, or set `CODEX_AUTH_JSON_PATH`.
- Claude: unset `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL`. On macOS store a subscription token once with `claude setup-token` then `uv run harness-test auth claude`; elsewhere use `CLAUDE_CODE_OAUTH_TOKEN`. The adapter passes the token through mode-0600 temporary files and deletes every copy after use.

The execution preflight rejects missing or wrong-mode credentials before Harbor starts.

### Recovering an interrupted run

Do not resume an approved manifest with changed inputs. Prepare a new request covering only the unstarted or failed slots (a recovery), or the corrected tasks for every contender (a correction), and approve it separately. `campaign summarize` stitches those reports back into the original lane.

## Evaluate the finished code

Final-patch review, model-free preparation then one fresh reviewer session per packet:

```bash
uv run harness-test review prepare \
  --report runs/generated/DIGEST/Run_Report.json \
  --protocol 'policy/Code Review Protocol.json'
uv run harness-test review record \
  --plan runs/reviews/PLAN/Plan.json --results /private/reviewer/Results.json
```

Packets are blinded and frozen; reviewers must attest a fresh session without the tested harness. Confirmed findings need a separate confirming session with a reproduction and an evidence file. Review is advisory: a missing review leaves the verdict provisional and flagged, unconfirmed claims are listed as a warning, and confirmed remaining defects disqualify a contender.

Automated work-quality grades, same shape:

```bash
uv run harness-test collaboration prepare \
  --report runs/generated/DIGEST/Run_Report.json \
  --protocol 'policy/Quality Grading Protocol.json'
uv run harness-test collaboration record \
  --plan runs/collaboration/PLAN/Plan.json --results runs/inputs/Grades.json
```

Grades and the deterministic transcript metrics are descriptive evidence beside the verdict; they never decide it.

## Full toolbox campaign

```bash
uv run harness-test campaign plan --manifest CONTROLLED_MANIFEST --manifest RESEARCH_MANIFEST
uv run harness-test campaign summarize --plan runs/campaigns/DIGEST/Plan.json \
  --report CONTROLLED_REPORT --report CONTROLLED_RECOVERY … \
  --report RESEARCH_REPORT --report RESEARCH_CORRECTION …
```

List each lane's frozen report first, then its recovery and correction reports in execution order. A later report may replace a slot only when the earlier trial did not complete or the task digest changed, and a corrected task must be rerun for every contender. The summary reports per-lane verdicts, superseded trials, corrected adapters and whether the current policy still matches the frozen plan.

## Inspect and classify

Use Harbor's local viewer and the raw job directory. Sample passes, failures and outliers, assign the infrastructure state before interpreting a score, and quarantine a broken or unfair task. Raw jobs and provider homes are ignored local data; never copy them into docs, issues or dashboard assets.

## Dashboard

```bash
npm ci --prefix dashboard --ignore-scripts
npm --prefix dashboard test
npm --prefix dashboard run build
```

The build emits ignored `dashboard/dist/`. Without a `dashboard-data/reports` directory it reads `runs/evidence` directly and skips files that are not public-safe run reports.

## DeepSWE research lane

```bash
uv run harness-test deepswe materialize --task quill-shared-toolbar-focus --confirm-download
```

An explicit `--task` fetches only that pinned selection into ignored `.cache/deepswe/` and builds separate `linux/amd64` images. Do not track or redistribute the fetched source, derived wrappers or images.
