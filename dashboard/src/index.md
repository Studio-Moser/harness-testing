---
theme: dashboard
title: Latest
toc: false
---

# Harness Testing

Latest reviewed results from frozen test repositories. This site contains sanitized summaries only; raw Harbor jobs, prompts, tool output, reasoning, trajectories, and host paths are never published.

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

const report = FileAttachment("./data/Public_Results.json").json();
const results = report.results;
const latest = latestResults(results);
const latestFinishedAt = results.at(-1)?.run.finished_at ?? null;
const passing = latest.filter((result) => result.run.release_decision === "pass").length;
const held = latest.filter((result) => result.run.release_decision === "hold").length;
const infrastructureFailures = latest.filter((result) => result.infrastructure.status !== "passed").length;
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
