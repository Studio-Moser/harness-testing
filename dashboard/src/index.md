---
theme: dashboard
title: Latest
toc: false
---

# Harness Testing

Latest results from frozen test repositories. Local builds also show sanitized, unreviewed run status; public builds contain reviewed results only. Raw Harbor jobs, prompts, tool output, reasoning, trajectories, and host paths are never included.

```js
import {
  deliveryLabel,
  formatCost,
  formatScore,
  formatSeconds,
  formatTimestamp,
  latestResults,
  totalRuntime,
  totalTokens
} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const results = report.results;
const localRuns = report.local_runs;
const currentRun = localRuns.at(-1) ?? null;
const currentJobs = currentRun?.jobs ?? [];
const currentFinalized = currentRun == null
  ? 0
  : results.filter((result) => result.run.manifest_digest === currentRun.manifest_digest).length;
const latest = latestResults(results);
const latestFinishedAt = results.at(-1)?.run.finished_at ?? null;
const passing = latest.filter((result) => result.run.release_decision === "pass").length;
const held = latest.filter((result) => result.run.release_decision === "hold").length;
const infrastructureFailures = latest.filter((result) => result.infrastructure.status !== "passed").length;
```

## Current local run

```js
currentRun
  ? html`<div>
      <div class="grid grid-cols-4">
        <div class="card"><h2>Status</h2><span class="big">${currentRun.status}</span></div>
        <div class="card"><h2>Completed jobs</h2><span class="big">${currentRun.completed_jobs} / ${currentRun.expected_jobs}</span></div>
        <div class="card"><h2>Completed trials</h2><span class="big">${currentRun.completed_trials} / ${currentRun.expected_trials}</span></div>
        <div class="card"><h2>Finalized results</h2><span class="big">${currentFinalized} / ${currentRun.expected_trials}</span></div>
      </div>
      <p class="note">Dollar amounts are API-equivalent telemetry; they do not represent incremental subscription charges.</p>
      ${Inputs.table(
        currentJobs.map((job) => ({
          provider: job.provider,
          arm: job.arm,
          role: job.role,
          task: job.task,
          status: job.status,
          correctness: formatScore(job.dimensions.correctness),
          workflow: formatScore(job.dimensions.workflow),
          efficiency_policy: formatScore(job.dimensions.efficiency_policy),
          runtime: formatSeconds(job.runtime_seconds),
          tokens: job.efficiency.prompt_tokens == null || job.efficiency.completion_tokens == null
            ? "Unavailable"
            : (job.efficiency.prompt_tokens + job.efficiency.completion_tokens).toLocaleString("en-US"),
          api_equivalent_cost: formatCost(job.efficiency.api_equivalent_cost_usd)
        })),
        {
          columns: [
            "provider",
            "arm",
            "role",
            "task",
            "status",
            "correctness",
            "workflow",
            "efficiency_policy",
            "runtime",
            "tokens",
            "api_equivalent_cost"
          ]
        }
      )}
    </div>`
  : html`<div class="note">No local execution report exists yet. The next run will create one automatically.</div>`
```

<div class="grid grid-cols-4">
  <div class="card">
    <h2>Finalized results</h2>
    <span class="big">${results.length}</span>
  </div>
  <div class="card">
    <h2>Latest finish (UTC)</h2>
    <span class="big" style="font-size: 1.3rem;">${formatTimestamp(latestFinishedAt)}</span>
  </div>
  <div class="card">
    <h2>Pass / hold</h2>
    <span class="big">${passing} / ${held}</span>
  </div>
  <div class="card">
    <h2>Infrastructure failures</h2>
    <span class="big">${infrastructureFailures}</span>
  </div>
</div>

## Latest finalized comparison

```js
latest.length
  ? Inputs.table(
      latest.map((result) => ({
        provider: result.provider.name,
        delivery: deliveryLabel(result),
        task: result.task.id,
        role: result.arm.role,
        correctness: formatScore(result.dimensions.correctness),
        workflow: formatScore(result.dimensions.workflow),
        efficiency_policy: formatScore(result.dimensions.efficiency_policy),
        runtime: formatSeconds(totalRuntime(result)),
        tokens: totalTokens(result)?.toLocaleString("en-US") ?? "Unavailable",
        cost: formatCost(result.efficiency.cost_usd),
        decision: result.run.release_decision,
        infrastructure: result.infrastructure.status
      })),
      {
        columns: [
          "provider",
          "delivery",
          "task",
          "role",
          "correctness",
          "workflow",
          "efficiency_policy",
          "runtime",
          "tokens",
          "cost",
          "decision",
          "infrastructure"
        ]
      }
    )
  : html`<div class="note">No reviewed, finalized public results have been published yet.</div>`
```

Superpowers delivery is provider-specific: Claude is **hook-capable**; Codex is **skills-only**.
