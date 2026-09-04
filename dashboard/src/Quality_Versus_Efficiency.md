---
theme: dashboard
title: Quality versus efficiency
toc: false
---

# Quality versus efficiency

Only correct trials appear here. Runtime, tokens, cost, and workflow remain separate signals; there is intentionally no composite ranking.

```js
import * as Plot from "@observablehq/plot";
import {
  deliveryLabel,
  formatCost,
  formatScore,
  formatSeconds,
  totalRuntime,
  totalTokens
} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const correct = report.results.filter((result) => result.dimensions.correctness === 1);
const comparable = correct.map((result) => ({
  runtime: totalRuntime(result),
  tokens: totalTokens(result),
  cost: result.efficiency.cost_usd,
  workflow: result.dimensions.workflow === 1 ? "Workflow pass" : "Workflow violation",
  provider: result.provider.agent,
  arm: result.arm.id,
  task: result.task.id
})).filter((point) => point.runtime != null && point.tokens != null);
```

```js
comparable.length
  ? resize((width) => Plot.plot({
      width,
      height: 440,
      grid: true,
      x: {label: "Total runtime (seconds)"},
      y: {label: "Prompt plus completion tokens"},
      color: {legend: true},
      symbol: {legend: true},
      marks: [
        Plot.dot(comparable, {
          x: "runtime",
          y: "tokens",
          fill: "workflow",
          symbol: "provider",
          r: 7,
          tip: true,
          title: (point) => `${point.task}\n${point.provider} ${point.arm}\nCost: ${point.cost == null ? "Unavailable" : `$${point.cost.toFixed(4)}`}`
        })
      ]
    }))
  : html`<div class="note">No correct trials with both runtime and token telemetry are available.</div>`
```

## Correct-trial details

```js
correct.length
  ? Inputs.table(
      correct.map((result) => ({
        task: result.task.id,
        delivery: deliveryLabel(result),
        workflow: formatScore(result.dimensions.workflow),
        efficiency_policy: formatScore(result.dimensions.efficiency_policy),
        runtime: formatSeconds(totalRuntime(result)),
        tokens: totalTokens(result)?.toLocaleString("en-US") ?? "Unavailable",
        cost: formatCost(result.efficiency.cost_usd),
        comprehensive_tests: result.efficiency.comprehensive_tests ?? "Unavailable",
        premature_suites: result.efficiency.premature_comprehensive_tests ?? "Unavailable"
      }))
    )
  : html`<div class="note">No correct finalized trials are available.</div>`
```
