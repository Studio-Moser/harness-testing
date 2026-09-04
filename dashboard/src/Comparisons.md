---
theme: dashboard
title: Comparisons
toc: false
---

# Current versus candidate

Latest finalized results by provider, arm, and task. Arms are shown independently; this report does not collapse quality and efficiency into a composite rank.

```js
import * as Plot from "@observablehq/plot";
import {
  deliveryLabel,
  formatCost,
  formatScore,
  formatSeconds,
  latestResults,
  totalRuntime,
  totalTokens
} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const latest = latestResults(report.results);
const scores = latest.flatMap((result) => [
  {
    provider: result.provider.agent,
    arm: result.arm.id,
    role: result.arm.role,
    task: result.task.id,
    dimension: "Correctness",
    value: result.dimensions.correctness
  },
  {
    provider: result.provider.agent,
    arm: result.arm.id,
    role: result.arm.role,
    task: result.task.id,
    dimension: "Workflow",
    value: result.dimensions.workflow
  },
  {
    provider: result.provider.agent,
    arm: result.arm.id,
    role: result.arm.role,
    task: result.task.id,
    dimension: "Efficiency policy",
    value: result.dimensions.efficiency_policy
  }
]).filter((point) => point.value != null);
```

```js
latest.length
  ? resize((width) => Plot.plot({
      width,
      height: 360,
      x: {label: "Arm"},
      y: {domain: [0, 1], grid: true, label: "Score"},
      fx: {label: "Provider"},
      color: {legend: true},
      symbol: {legend: true},
      marks: [
        Plot.ruleY([0, 1]),
        Plot.dot(scores, {
          x: "arm",
          y: "value",
          fx: "provider",
          fill: "role",
          symbol: "dimension",
          r: 6,
          tip: true,
          title: (point) => `${point.task}\n${point.dimension}: ${point.value}`
        })
      ]
    }))
  : html`<div class="note">No finalized comparisons are available.</div>`
```

## Comparison table

```js
latest.length
  ? Inputs.table(
      latest.map((result) => ({
        provider: result.provider.name,
        delivery: deliveryLabel(result),
        skill_mode: result.skill_evaluation.mode,
        skill: result.skill_evaluation.name ?? "None",
        invocation: result.skill_evaluation.invocation,
        task: result.task.id,
        role: result.arm.role,
        correctness: formatScore(result.dimensions.correctness),
        workflow: formatScore(result.dimensions.workflow),
        efficiency_policy: formatScore(result.dimensions.efficiency_policy),
        runtime: formatSeconds(totalRuntime(result)),
        tokens: totalTokens(result)?.toLocaleString("en-US") ?? "Unavailable",
        cost: formatCost(result.efficiency.cost_usd),
        release: result.run.release_decision
      }))
    )
  : html`<div class="note">No finalized comparisons are available.</div>`
```

Superpowers delivery is **hook-capable on Claude** and **skills-only on Codex**.
