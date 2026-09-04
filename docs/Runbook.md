# Runbook

## Prerequisites

- Docker
- Python 3.12.14
- `uv` 0.11.19
- Node 22.23.2 and npm
- Provider CLIs only when a manually approved model-backed run is intended

Install locked dependencies and run the fast static gate:

```bash
uv sync --frozen
uv run harness-test validate --static-only
```

## Surgical development checks

Use the smallest check that proves the change:

```bash
# One Python module and its test
uv run ruff check src/harness_testing/Results.py tests/unit/test_Results.py
uv run pytest -q tests/unit/test_Results.py

# One changed task while authoring
uv run harness-test task qa --task react-accent-polish --case oracle
uv run harness-test task qa --task react-accent-polish --case nop

# Dashboard-only change
npm --prefix dashboard test
npm --prefix dashboard run build
```

Run the full deterministic gates once at the checkpoint. `harness-test validate --changed-from COMMIT` uses the same policy in CI: it groups related unit modules into one pytest invocation and escalates only shared execution-contract changes.

## Materialize an arm

Arm materialization runs provider-native plugin tooling in an isolated build context but starts no model session:

```bash
uv run harness-test arm materialize --provider codex --arm A0
uv run harness-test arm materialize \
  --provider codex \
  --arm A2 \
  --harness-source https://github.com/Studio-Moser/skills-n-stuff.git \
  --harness-commit FULL_40_CHARACTER_COMMIT
```

Materialized bundles stay under ignored `arms/materialized/` and are mounted read-only in task containers. Claude copies immutable plugin directories and supplies each one with a repeatable `--plugin-dir`; materialization runs model-free `claude plugin validate --strict` and creates no plugin seed. Codex uses its native marketplace/plugin layout, with Superpowers recorded as skills-only, and writes a plugin inventory before agent dispatch.

## Plan before any model-backed run

This example creates a one-session subscription manifest and starts no model:

```bash
uv run harness-test run plan \
  --profile smoke \
  --billing-mode subscription \
  --cell codex:A0:baseline \
  --task react-grouped-ui-updates \
  --max-sessions 1 \
  --max-budget-usd 0
```

Use exactly one skill-evaluation mode when the run is about a skill. Capability
uses provider-native explicit invocation while preserving the task as skill
arguments:

```bash
uv run harness-test run plan \
  --profile smoke \
  --billing-mode subscription \
  --cell codex:A2:candidate:FULL_40_CHARACTER_COMMIT \
  --task missing-rubric \
  --invoke-skill harness:execute \
  --max-sessions 1 \
  --max-budget-usd 0
```

Discovery uses the unchanged task and needs at least five attempts:

```bash
uv run harness-test run plan \
  --profile smoke \
  --billing-mode subscription \
  --cell codex:A2:candidate:FULL_40_CHARACTER_COMMIT \
  --task missing-rubric \
  --observe-skill harness:execute \
  --attempts 5 \
  --max-sessions 5 \
  --max-budget-usd 0
```

After execution, `Skill_Evaluation.json` beside the ignored manifest contains
only per-trial invocation classifications and the aggregate rate. Discovery is
diagnostic; its rate is never converted into a release pass or failure.

For paired evidence, name both cells explicitly and keep concurrency one. A2 and A3 cell specifications include the exact Studio Harness commit as the fourth colon-separated field.

Review the printed provider/model/effort, tasks, attempts, session order, timeouts, incremental cost, API-equivalent estimate, input digests, manifest path, and manifest digest. Obtain a fresh explicit approval for that digest. Approval of an older manifest never authorizes a regenerated or duplicate run.

Execute only the approved file:

```bash
uv run harness-test run execute \
  --manifest runs/generated/MANIFEST_DIRECTORY/Manifest.json \
  --approve sha256:EXACT_APPROVED_DIGEST
```

Execution writes `Run_Report.json` beside the approved manifest, updates it after each
job, and rebuilds the ignored local dashboard once when the run completes or stops.
This report contains only allowlisted status, scores, timestamps, token totals, and
cost telemetry; it never copies raw prompts, trajectories, commands, or host paths.

After normal completion or a handled failure, execution makes one best-effort batch
publication attempt for every pending report. Publication failure does not erase or
mislabel the run; it leaves the reports pending and prints this retry:

```bash
uv run harness-test report sync
```

The first selected task runs as the delivery canary across every selected cell. A correctness zero is valid task evidence and continues the run. Any infrastructure or delivery failure stops execution before the second task; later delivery failures also stop immediately.

### Subscription authentication

Subscription mode forbids API fallback.

- Codex: unset `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_API_BASE`. The default credential is `~/.codex/auth.json`, or set `CODEX_AUTH_JSON_PATH` to another local ChatGPT-auth JSON file.
- Claude: unset `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL`. For local macOS runs, create a subscription token once and store it in Keychain:

  ```bash
  claude setup-token
  uv run harness-test auth claude
  ```

  CI and non-macOS runs use `CLAUDE_CODE_OAUTH_TOKEN`. Neither the Keychain nor environment path authorizes API billing.

  The runner passes the resolved value only in Harbor's child environment. The
  Claude adapter then uses mode-`0600` temporary files rather than Harbor's
  per-exec environment interface, because that interface expands values into
  Docker argv. The adapter also removes the token from Harbor's trial-scoped
  agent environment. It deletes the host copy immediately after upload and the
  container copy before Claude starts, with final cleanup on failures. This
  adapter supports direct Claude trials only; ACP remains disabled until its
  pre-run bridge can use the same secret-safe handoff.

The execution preflight rejects missing or wrong-mode credentials before Harbor starts. Subscription mode requires `--max-budget-usd 0`; the report still shows an API-equivalent usage estimate because subscription quota is not a dollar hard stop.

API mode requires a positive maximum. That maximum is an admission guard based on the conservative estimate, not a provider-enforced mid-session cutoff.

## Inspect and classify

Use Harbor’s local viewer and raw job directory. Sample passes, failures, unusually efficient trials, and outliers. Assign the infrastructure state before interpreting a score. Quarantine a broken or unfair task; do not finalize partial or quarantined evidence.

Raw jobs and provider homes are ignored local data. Never copy them into `results/`, docs, issues, or dashboard assets.

## Regrade without another agent run

When only verifier/scorer logic changes, preserve the source job and run:

```bash
uv run harness-test regrade \
  --job jobs/raw/SOURCE_JOB \
  --tasks tasks/workflow
```

The command requires the source workspace and trajectory artifacts, runs Harbor’s regrade path with the Docker verifier, verifies the source tree stayed byte-identical, and writes a local provenance receipt in the new ignored job. A verifier/scorer-only change does not buy new model sessions.

## Finalize a public result

Prepare a complete reviewed candidate matching the public schema, then construct the allowlisted output:

```bash
uv run harness-test result sanitize \
  --job runs/generated/Reviewed_Result.json \
  --output results/Reviewed_Result.json
```

`results/` accepts finalized, reviewed, non-partial, non-quarantined data only. It resolves `run.manifest_digest` only through the matching content-addressed `runs/generated/` manifest, revalidates that manifest’s digest, and requires both manifest and methodology schema to match the current repository series with no reviewed mapping. Use `runs/generated/` for inspectable local staging. The sanitizer rejects raw trajectories, reasoning, command/tool output, environment variables, auth-looking fields, home paths, arbitrary Harbor extras, unknown telemetry, and mismatched identities.

Old hidden-contract and plugin-seed cohorts stay local and quarantined. Do not regrade them or create a reviewed mapping into current schema `0.3.0`.

## Dashboard

The dashboard has two evidence lanes:

- Development history is every schema-valid, public-safe run report, including
  incomplete, failed, unreviewed, quarantined, and historical reports. It is useful
  for diagnosing progress but is not automatically decision-grade.
- Decision-grade results are still created only by the strict, unchanged
  `harness-test result sanitize` path described above.

Reconstruct historical reports without opening raw job artifacts or starting a
model session:

```bash
uv run harness-test report backfill \
  --source-root "$HARNESS_HISTORY_ARCHIVE_ROOT" \
  --source-root "$PWD" \
  --mapping runs/Historical_Backfill.toml \
  --output runs/history
```

The output and its publication receipts are ignored local files. Backfill accepts
only manifest/config/top-level result summaries, fails closed on ambiguous matches,
and labels legacy, partial, failed, or missing-provenance evidence explicitly.

Publish every pending live or historical report in one batch:

```bash
uv run harness-test report sync
```

The publisher validates the complete batch, uses a temporary checkout of the fixed
`dashboard-data` branch, makes at most one data commit, and dispatches
`Publish_Pages.yml` once. It never switches the caller's worktree, never
force-pushes, and retries once only after a non-fast-forward rejection. A local
receipt beside each report records the report ID and data commit, so an unchanged
report is not republished. Run the sync command again after any other failure.

Dashboard code and reviewed results stay on `main`; `dashboard-data` contains only
its README and `reports/*.json`. Charts retain unavailable measurements as null,
and cross-run deltas require exactly equal, non-null series keys.

```bash
npm ci --prefix dashboard --ignore-scripts
npm --prefix dashboard test
npm --prefix dashboard run build
```

The build emits ignored `dashboard/dist/`. A model-backed execution invalidates the
local result-loader cache and performs this build once at the end. GitHub Pages
checks out dashboard code and reviewed results from `main`, reads run reports from
`dashboard-data`, validates both inputs, and deploys the combined static site. A
report sync dispatches that workflow even though it does not mutate `main`.

## DeepSWE research lane

First print the exact download/build plan:

```bash
uv run harness-test deepswe materialize
```

Materialization requires `--confirm-download`. It fetches only the pinned six-task cohort into ignored `.cache/deepswe/` and builds separate `linux/amd64` images. Do not track or redistribute the fetched source, derived task wrappers, or images.
