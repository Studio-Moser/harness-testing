---
theme: dashboard
title: Task matrix
toc: false
---

# Task matrix

Task-level quality, infrastructure, and efficiency counters. Every unavailable metric stays explicitly unavailable.

```js
import {
  deliveryLabel,
  formatCost,
  formatCount,
  formatScore,
  formatSeconds,
  totalRuntime,
  totalTokens
} from "./components/Results.js";

const report = await FileAttachment("./data/Public_Results.json").json();
const rows = report.results.map((result) => ({
  task: result.task.id,
  pack: result.task.pack,
  delivery: deliveryLabel(result),
  role: result.arm.role,
  correctness: formatScore(result.dimensions.correctness),
  workflow: formatScore(result.dimensions.workflow),
  efficiency_policy: formatScore(result.dimensions.efficiency_policy),
  infrastructure: result.infrastructure.status,
  runtime: formatSeconds(totalRuntime(result)),
  tokens: totalTokens(result) == null ? "Unavailable" : formatCount(totalTokens(result)),
  cost: formatCost(result.efficiency.cost_usd),
  commands: formatCount(result.efficiency.commands),
  targeted_tests: formatCount(result.efficiency.targeted_tests),
  package_tests: formatCount(result.efficiency.package_tests),
  comprehensive_tests: formatCount(result.efficiency.comprehensive_tests),
  premature_suites: formatCount(result.efficiency.premature_comprehensive_tests),
  duplicate_commands: formatCount(result.efficiency.duplicate_successful_commands),
  retries: formatCount(result.efficiency.retries),
  timeouts: formatCount(result.efficiency.timeouts)
}));
```

```js
rows.length
  ? Inputs.table(rows, {
      columns: [
        "task",
        "pack",
        "delivery",
        "role",
        "correctness",
        "workflow",
        "efficiency_policy",
        "infrastructure",
        "runtime",
        "tokens",
        "cost",
        "commands",
        "targeted_tests",
        "package_tests",
        "comprehensive_tests",
        "premature_suites",
        "duplicate_commands",
        "retries",
        "timeouts"
      ]
    })
  : html`<div class="note">No finalized task results are available.</div>`
```
