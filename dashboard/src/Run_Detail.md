---
theme: dashboard
title: Run detail
toc: false
---

# Run detail

Inspect one allowlisted run report, including incomplete jobs, evidence limitations, provenance, and any linked decision-grade results.

```js
import {
  completionLabel,
  evidenceLabel,
  formatObservedCost,
  latestRun,
  observationTokens,
  runObservations,
  seriesLabel
} from "./components/Run_History.js";
import {
  deliveryLabel,
  formatScore,
  formatSeconds,
  formatTimestamp
} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const runReports = report.run_reports;
const observations = runObservations(report.run_reports, report.results);
const reportsById = new Map(runReports.map((run) => [run.run_id, run]));
const newest = latestRun(runReports);
```

```js
const selectedId = view(Inputs.select(runReports.length ? runReports.map((run) => run.run_id) : [null], {
  label: "Run report",
  value: newest?.run_id ?? null,
  format: (id) => {
    const run = reportsById.get(id);
    return run == null ? "No public-safe run reports" : `${run.run_id} · ${run.status} · ${formatTimestamp(run.finished_at ?? run.updated_at)}`;
  }
}));
```

```js
const selected = selectedId == null ? null : reportsById.get(selectedId);
const selectedJobs = selected == null
  ? []
  : observations.filter((item) => item.runId === selected.run_id);
const linkedResults = selected == null
  ? []
  : report.results.filter((result) => result.run.manifest_digest === selected.manifest_digest);
const limitations = selected?.evidence.limitations ?? [];
const commits = [...new Set(selectedJobs.map((job) => job.harnessCommit).filter((commit) => commit != null))];
```

```js
selected
  ? html`<div>
      <div class="grid grid-cols-4">
        <div class="card"><h2>Status</h2><span class="big">${selected.status}</span></div>
        <div class="card"><h2>Evidence</h2><span class="big" style="font-size:1.3rem">${evidenceLabel(selected)}</span></div>
        <div class="card"><h2>Completion</h2><span class="big" style="font-size:1.1rem">${completionLabel(selected)}</span></div>
        <div class="card"><h2>Finished (UTC)</h2><span class="big" style="font-size:1.1rem">${formatTimestamp(selected.finished_at ?? selected.updated_at)}</span></div>
      </div>
      <p><strong>Source:</strong> ${selected.source.kind.replaceAll("-", " ")}${selected.source.label == null ? "" : ` · ${selected.source.label}`}</p>
    </div>`
  : html`<div class="note">No public-safe run reports have been published.</div>`
```

## Jobs

```js
selectedJobs.length
  ? Inputs.table(selectedJobs.map((job) => ({
      provider: job.provider,
      agent_version: job.agentVersion,
      model: job.model,
      effort: job.effort,
      arm: job.arm,
      role: job.role,
      task: job.task,
      pack: job.taskPack,
      status: job.jobStatus,
      evidence: evidenceLabel(job),
      comparison: seriesLabel(job),
      correctness: formatScore(job.dimensions.correctness),
      workflow: formatScore(job.dimensions.workflow),
      efficiency_policy: formatScore(job.dimensions.efficiency_policy),
      runtime: formatSeconds(job.runtimeSeconds),
      tokens: observationTokens(job)?.toLocaleString("en-US") ?? "Unavailable",
      cached_tokens: job.cachedTokens?.toLocaleString("en-US") ?? "Unavailable",
      observed_cost: formatObservedCost(job.observedCost)
    })))
  : html`<div class="note">No job summaries are available for this run.</div>`
```

## Evidence limitations

```js
selected
  ? limitations.length
    ? html`<ul>${limitations.map((limitation) => html`<li>${limitation.replaceAll("-", " ")}</li>`)}</ul>`
    : html`<div class="note">No report-level limitations were recorded. This does not make unreviewed evidence decision-grade.</div>`
  : html`<div class="note">Unavailable</div>`
```

## Provenance and usage

```js
selected
  ? html`<div>
      ${Inputs.table([{
        report_id: selected.report_id,
        run_id: selected.run_id,
        manifest: selected.manifest_digest,
        manifest_schema: selected.manifest_schema_version,
        profile: selected.profile,
        source: selected.source.kind,
        harness_commit: commits.length === 0 ? "Unavailable" : commits.length === 1 ? commits[0] : "Multiple commits",
        admission_estimate: selected.admission_estimate_usd == null ? "Unavailable" : `$${selected.admission_estimate_usd.toFixed(2)}`,
        observed_cost: formatObservedCost(selected.observed_api_equivalent_cost_usd)
      }])}
      <p class="note">The admission estimate is a conservative planning ceiling. Observed API-equivalent usage is measured telemetry. Incremental subscription spend is not captured and must not be inferred from either value.</p>
    </div>`
  : html`<div class="note">Unavailable</div>`
```

## Linked decision-grade results

```js
linkedResults.length
  ? Inputs.table(linkedResults.map((result) => ({
      result_id: result.result_id,
      delivery: deliveryLabel(result),
      task: result.task.id,
      correctness: formatScore(result.dimensions.correctness),
      workflow: formatScore(result.dimensions.workflow),
      efficiency_policy: formatScore(result.dimensions.efficiency_policy),
      release: result.run.release_decision,
      finalized: formatTimestamp(result.run.finalized_at)
    })))
  : html`<div class="note">This report has no linked reviewed, finalized public result. Its development-history evidence is not a release decision.</div>`
```

```js
linkedResults.length
  ? html`<ul>${linkedResults.flatMap((result) => result.source_links).map((link) => html`<li><a href=${link.url}>${link.label}</a>${link.digest == null ? "" : ` · ${link.digest}`}</li>`)}</ul>`
  : html`<div></div>`
```
