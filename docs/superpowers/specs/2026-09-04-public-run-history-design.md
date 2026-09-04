# Public Run History and Automatic Dashboard Publication Design

**Status:** Approved
**Date:** 2026-09-04
**Scope:** Publish every recoverable, public-safe benchmark run to the Harness
Testing dashboard without weakening the separate decision-grade result gate.

## Context

The public dashboard is structurally healthy but empty. Its Pages build checks
out tracked repository content, while model-backed execution writes
`Run_Report.json` only beneath ignored `runs/generated/`. The dashboard can show
that report in a local build, but GitHub Actions cannot receive it. The only
tracked dashboard input is `results/`, whose intentionally strict sanitizer
accepts reviewed, finalized, current-methodology evidence. No result has crossed
that boundary.

That split protects formal benchmark conclusions but hides the development
history the dashboard is supposed to explain. The local archive currently holds
21 recoverable result-bearing cohorts: 19 run-ID cohorts plus the archived
two-job smoke and the pre-run-ID 34-job release. Together they contain 182
top-level Harbor job summaries. They span complete, partial, failed,
quarantined, and obsolete-methodology attempts and therefore cannot all be
presented as decision-grade evidence, but they can be presented honestly as
development history.

## Goals

1. Make every recoverable result-bearing run visible on the public dashboard.
2. Keep development history distinct from reviewed, decision-grade results.
3. Show refinement over time without calculating misleading cross-methodology
   deltas.
4. Publish one safe report automatically when a run completes or stops.
5. Backfill the existing 21 cohorts without starting another model session.
6. Preserve the raw-artifact privacy boundary and fail closed on unknown data.
7. Use GitHub, GitHub Actions, GitHub Pages, and the existing CLI rather than a
   new hosted service or reporting dependency.
8. Avoid per-job commits, repeated Pages builds, and repeated comprehensive
   validation while implementing or operating the feature.

## Non-goals

- Publishing prompts, trajectories, reasoning, command or tool output,
  credentials, environment variables, raw Harbor extras, or host paths.
- Retroactively declaring historical or unreviewed evidence decision-grade.
- Inventing comparability mappings for changed tasks, scorers, environments,
  provider contracts, or methodology versions.
- Replacing the existing `result sanitize` review and finalization path.
- Plotting planned manifests that have no result artifact as if a model ran.
- Re-running any provider session to fill historical metadata gaps.
- Introducing a database, analytics service, dashboard API server, or scheduled
  polling job.

## Decision 1: keep two evidence lanes

The dashboard will expose two explicit lanes:

- **Development history** contains every schema-valid, allowlisted run report,
  including complete, partial, failed, quarantined, legacy, and unreviewed
  evidence.
- **Decision-grade results** retains the existing reviewed and finalized public
  result contract.

Development history is the default landing view because it answers whether the
harness is improving. Decision-grade results remain available as a stricter
filter and retain their existing release-decision semantics. A historical score
never silently becomes a pass/fail decision.

## Decision 2: use one canonical public-safe run report

Advance `Run_Report.schema.json` to version 2 and use it for both local and
published reports. The report remains an allowlist, not a recursively filtered
copy of Harbor output. Version 2 adds the evidence needed to interpret history:

- manifest and methodology schema versions;
- source classification (`current`, `identified-historical`, or
  `legacy-historical`);
- review state (`unreviewed`, `reviewed`, or `quarantined`);
- comparability state (`comparable` or `diagnostic-only`);
- constrained limitation codes such as partial coverage, obsolete methodology,
  legacy identity, missing provenance, or infrastructure failure;
- a nullable per-job series key and an explicit reason when no defensible key
  can be constructed.

The existing identity, timestamps, profile, completion counts, provider, model,
effort, arm, role, harness commit, task, score dimensions, runtime, token totals,
and cache totals remain. Unknown fields are rejected. Version 2 separates the
manifest's conservative admission estimate from observed API-equivalent usage:
`admission_estimate_usd` records the former, while nullable
`observed_api_equivalent_cost_usd` sums only measured job telemetry. The UI must
never present the estimate as incurred usage. Published reports must be version
2. The local loader may normalize a version 1 report long enough to regenerate
it; it may not publish version 1.

A series key is derived only from known compatibility inputs: task/dataset
identity, environment and scoring identity, provider-agent contract, model and
effort, skill-evaluation mode, and methodology schema. Missing input makes the
job diagnostic-only. The dashboard may plot diagnostic points, but it computes
deltas only for equal, non-null series keys. A0/A2 jobs from the same manifest
may be shown as a paired observation without claiming compatibility with other
runs.

## Decision 3: backfill only recoverable evidence

Add a model-free backfill path that reads only generated manifests and Harbor's
top-level `result.json` job summaries. It must not read trial prompts,
trajectories, logs, workspaces, command output, or provider homes.

Nineteen cohorts map directly through their `run-<id>` job-name prefix and
manifest `provenance.run_id`. Two legacy cohorts use explicit operator-supplied
mappings: the archived two-job smoke and the pre-run-ID 34-job release. The
backfill fails on ambiguous mappings, duplicate jobs, malformed timestamps,
unknown provider/arm/task labels, or schema-invalid output. Missing provenance
is represented as unavailable and diagnostic-only, never guessed.

The initial backfill must produce 21 reports covering exactly 182 top-level job
summaries. Those counts are acceptance checks, not permanent assumptions in the
runtime implementation.

## Decision 4: publish reports through a dedicated data branch

Create an orphan `dashboard-data` branch containing only a short README and
`reports/<run-id>.json`. The branch is append-only by run identity; a newer
terminal report may replace an earlier snapshot of the same run only when its
`updated_at` is later. Git history preserves prior snapshots.

The local publisher validates every outgoing report, copies no surrounding
directory, and updates the data branch from a temporary checkout. It never
switches or dirties the developer's current worktree. One publish invocation
creates at most one data commit, even when `harness-test report sync` batches
multiple pending reports.

Model-backed planning copies the publication mode, exact public repository,
data branch, and workflow name from a tracked policy file into manifest
provenance and the content-derived run identity. Existing manifests without
that provenance remain local-only. The approval summary states that the
allowlisted report will be public. Canonical repository runs default to public
reporting; an explicitly planned local-only run remains possible. Execution
never infers a different destination from ambient Git state.

After a successful data push, the publisher invokes the existing
default-branch `Publish_Pages.yml` through GitHub's `workflow_dispatch`
interface. The workflow checks out dashboard code from `main` and reports from
`dashboard-data`, validates both schemas, and deploys one static build.
Main-branch dashboard changes use the same build path. Existing Pages
concurrency cancels superseded builds.

This branch design avoids benchmark-data commits and pull requests on `main`
while retaining a public, auditable report history. It adds no third-party
service or package.

## Decision 5: publish once and retain a retryable outbox

Execution continues updating its ignored local report after each Harbor job,
but it publishes only after normal completion or a handled stop. This preserves
partial and failed evidence without causing one commit and Pages deployment per
job.

Publication failure does not rewrite a successful benchmark as a model failure.
The validated local report remains in a pending outbox, the CLI prints the exact
publication failure and retry command, and `harness-test report sync` retries
all pending reports in one commit. A later run attempts pending synchronization
before publishing its own terminal report. A hard-killed process is therefore
recoverable without manufacturing completion data.

Malformed, stale, conflicting, or destination-mismatched reports stay local and
fail closed. The publisher never deletes a remote report and never force-pushes
the data branch.

## Decision 6: make history the useful dashboard default

The landing page will lead with run-history totals, latest run status, latest
harness commit, and evidence-quality counts rather than zero finalized results.
All six views consume a normalized combination of public run reports and
decision-grade results:

- **Latest** shows the most recent report and its jobs.
- **Trends** plots correctness, workflow, efficiency policy, runtime, tokens,
  and API-equivalent cost over time with provider, arm, task, profile, and
  evidence filters.
- **Comparisons** pairs A0/A2 observations within a run and computes cross-run
  deltas only inside an equal compatibility series.
- **Task matrix** shows every reported task and visually distinguishes missing,
  failed, and incompatible cells.
- **Run detail** exposes the allowlisted job summary and evidence limitations.
- **Quality versus efficiency** plots all available points while distinguishing
  diagnostic-only evidence from comparable and reviewed evidence.

When a decision-grade result refers to a job already present in run history,
the normalized view enriches that observation with its review and release
decision; it never counts the job twice.

Methodology boundaries and evidence badges remain visible in charts, tables,
tooltips, and empty states. The UI may show an overall development trajectory,
but it must not label cross-series movement as a measured regression or
improvement. API-equivalent cost remains explicitly distinct from incremental
subscription spend.

## Decision 7: validate each trust boundary

The report generator and historical backfill validate against the canonical
schema before writing. The publisher revalidates before external transfer and
scans values for secret-like text and local paths. The Pages loader validates
every data-branch report and fails the build on unknown or malformed content.
The browser receives only the resulting allowlisted JSON attachment.

Publication uses the existing authenticated GitHub CLI and standard Git
operations. Credentials are never placed in command arguments, report content,
logs, or workflow artifacts. The canonical repository and data branch are
declared inputs, not free-form values sourced from a report.

## Error handling

- A report-generation failure preserves the original benchmark error and adds
  a reporting note, matching the current runner behavior.
- A publication or workflow-dispatch failure preserves the local outbox and prints a
  retry command; it does not alter scores or infrastructure classification.
- A data-branch conflict triggers one fresh fetch and normal non-force retry.
- An older snapshot cannot overwrite a newer remote report.
- A Pages validation failure prevents deployment and leaves the last healthy
  dashboard live.
- Historical ambiguity stops that cohort's backfill and reports the exact
  mapping problem without skipping it silently.

## Testing strategy

Implementation follows targeted TDD:

1. Schema tests prove version 2 accepts each evidence class and rejects unknown,
   private, path-like, or secret-like data.
2. Backfill tests cover identified, legacy, partial, failed, ambiguous, and
   missing-provenance fixtures without touching trajectory files.
3. Publisher tests use temporary repositories and a fake GitHub runner to prove
   one batched commit, monotonic updates, no force push, clean caller worktree,
   pending-outbox retention, and one workflow dispatch.
4. Pages workflow and loader tests prove `main` code combines with
   `dashboard-data` reports and fails closed on invalid input.
5. Dashboard tests prove every view handles all evidence classes and never
   computes a delta across unequal or null series keys.
6. One production build and browser pass verify the 21-report/182-job backfill,
   responsive rendering, filters, labels, links, and absence of runtime errors.

Run focused tests while editing. Run the complete deterministic repository gate
once at the checkpoint, after all implementation and backfill changes settle.
Start no provider model session for this work.

## Rollout

1. Implement schema version 2, normalization, backfill, publication, workflow,
   and dashboard support on the feature branch.
2. Generate and inspect the 21 historical reports locally.
3. Run focused checks, one dashboard browser pass, independent review, and one
   full deterministic checkpoint.
4. Merge code to `main` through a pull request.
5. Initialize `dashboard-data`, publish the validated backfill in one commit,
   and dispatch one Pages deployment through the default-branch workflow.
6. Verify the public dashboard contains 21 cohorts and 182 job summaries and
   that incompatible evidence is visibly separated.
7. Execute no new model run merely to test publication; future approved runs
   exercise the automatic path naturally.

## Completion criteria

- The public dashboard is non-empty and shows all 21 recoverable historical
  cohorts covering exactly 182 job summaries.
- Failed, partial, quarantined, unreviewed, legacy, and obsolete-methodology
  evidence is visible and unmistakably labeled.
- Formal deltas are calculated only inside non-null equal series keys.
- A future terminal run produces one local safe report, one data-branch update,
  and one Pages dispatch without dirtying the code worktree.
- A publication failure is locally recoverable through one batched sync.
- The decision-grade sanitizer remains strict and unchanged in meaning.
- No raw Harbor artifact or private value reaches Git, Actions artifacts, or the
  browser.
- Focused checks, the single full checkpoint, Pages deployment, and browser QA
  all pass without starting a provider model session.
