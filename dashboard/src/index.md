---
theme: dashboard
title: Latest
toc: false
---

# Harness Testing

Development history from frozen test repositories. Every value below comes from a public-safe run report; reviewed decision-grade results remain a separate, stricter evidence lane.

```js
import {
  completionLabel,
  coverageStates,
  evidenceLabel,
  evidenceState,
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
  formatTimestamp,
  latestResults
} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const runReports = report.run_reports;
const observations = runObservations(report.run_reports, report.results);
const currentRun = latestRun(runReports);
const currentJobs = currentRun == null
  ? []
  : observations.filter((observation) => observation.runId === currentRun.run_id);
const reviewedResults = latestResults(report.results);
const evidenceOrder = ["reviewed", "unreviewed", "quarantined", "partial", "failed"];
const evidenceCounts = new Map(evidenceOrder.map((state) => [state, 0]));
for (const run of runReports) {
  const review = evidenceState(run);
  evidenceCounts.set(review, (evidenceCounts.get(review) ?? 0) + 1);
  for (const coverage of coverageStates(run)) {
    evidenceCounts.set(coverage, (evidenceCounts.get(coverage) ?? 0) + 1);
  }
}
const latestCommits = currentRun == null
  ? []
  : [...new Set(currentRun.jobs.map((job) => job.harness_commit).filter((commit) => commit != null))];
const latestCommit = latestCommits.length === 0
  ? "Unavailable"
  : latestCommits.length === 1
    ? latestCommits[0]
    : "Multiple commits";
```

```js
runReports.length
  ? html`<div>
      <div class="grid grid-cols-4">
        <div class="card"><h2>Recoverable runs</h2><span class="big">${runReports.length}</span></div>
        <div class="card"><h2>Job observations</h2><span class="big">${observations.length}</span></div>
        <div class="card"><h2>Latest run</h2><span class="big" style="font-size:1.25rem;overflow-wrap:anywhere">${currentRun.run_id}</span><div>${currentRun.status} · ${completionLabel(currentRun)}</div></div>
        <div class="card"><h2>Latest finish (UTC)</h2><span class="big" style="font-size:1.25rem">${formatTimestamp(currentRun.finished_at ?? currentRun.updated_at)}</span></div>
      </div>
      <p class="note" style="overflow-wrap:anywhere"><strong>Latest harness commit:</strong> ${latestCommit}</p>
    </div>`
  : html`<div class="note">No public-safe run reports have been published.</div>`
```

## Evidence status

Reviewed, unreviewed, and quarantined count evidence decisions. Partial and failed count execution coverage, so those categories can overlap.

<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(8rem,1fr))">
${evidenceOrder.map((state) => html`<div class="card"><h2>${state.replace(/^./, (letter) => letter.toUpperCase())}</h2><span class="big">${evidenceCounts.get(state)}</span></div>`)}
</div>

## Latest run jobs

```js
currentRun
  ? html`<div>
      <p><strong>${evidenceLabel(currentRun)}</strong> · ${currentRun.source.kind.replaceAll("-", " ")} · ${currentRun.profile} profile</p>
      ${Inputs.table(
        currentJobs.map((job) => ({
          provider: job.provider,
          arm: job.arm,
          role: job.role,
          task: job.task,
          status: job.jobStatus,
          evidence: evidenceLabel(job),
          series: seriesLabel(job),
          correctness: formatScore(job.dimensions.correctness),
          workflow: formatScore(job.dimensions.workflow),
          efficiency_policy: formatScore(job.dimensions.efficiency_policy),
          runtime: formatSeconds(job.runtimeSeconds),
          tokens: observationTokens(job)?.toLocaleString("en-US") ?? "Unavailable",
          observed_cost: formatObservedCost(job.observedCost)
        })),
        {
          columns: [
            "provider",
            "arm",
            "role",
            "task",
            "status",
            "evidence",
            "series",
            "correctness",
            "workflow",
            "efficiency_policy",
            "runtime",
            "tokens",
            "observed_cost"
          ]
        }
      )}
      <p class="note">Observed API-equivalent usage: ${formatObservedCost(currentRun.observed_api_equivalent_cost_usd)}. Admission estimate: ${currentRun.admission_estimate_usd == null ? "Unavailable" : `$${currentRun.admission_estimate_usd.toFixed(2)}`}. Incremental subscription spend is not captured and must not be inferred from either value.</p>
    </div>`
  : html`<div class="note">No public-safe run reports have been published.</div>`
```

## Decision-grade results

```js
reviewedResults.length
  ? Inputs.table(
      reviewedResults.map((result) => ({
        provider: result.provider.name,
        delivery: deliveryLabel(result),
        task: result.task.id,
        correctness: formatScore(result.dimensions.correctness),
        workflow: formatScore(result.dimensions.workflow),
        efficiency_policy: formatScore(result.dimensions.efficiency_policy),
        decision: result.run.release_decision,
        finished: formatTimestamp(result.run.finished_at)
      }))
    )
  : html`<div class="note">No reviewed, finalized public results have been published yet. Development-history scores above are not release decisions.</div>`
```

Raw Harbor jobs, prompts, tool output, reasoning, trajectories, host paths, and credentials are never included in this dashboard.
